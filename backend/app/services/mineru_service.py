from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
import zipfile
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings


class MinerUParseError(ValueError):
    pass


_NOISE_TYPES = {
    "header",
    "footer",
    "page_header",
    "page_footer",
    "page_number",
    "page_footnote",
}
_KIND_MAP = {
    "title": "heading",
    "heading": "heading",
    "paragraph": "paragraph",
    "text": "paragraph",
    "list": "list",
    "list_item": "list",
    "code": "code",
    "code_block": "code",
    "table": "table",
    "equation": "formula",
    "equation_block": "formula",
    "formula": "formula",
    "image": "image",
    "figure": "image",
    "chart": "chart",
    "ref_text": "reference",
}


@dataclass(frozen=True)
class MinerUStructuredBlock:
    text: str
    kind: str
    page_start: int | None = None
    page_end: int | None = None
    section_path: list[str] = field(default_factory=list)
    start_index: int = 0
    heading_level: int | None = None
    bbox: list[float] | None = None
    media_path: str = ""
    node_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MinerUStructuredResult:
    text: str
    markdown: str
    blocks: list[MinerUStructuredBlock]
    page_count: int | None
    schema_version: str
    warnings: list[str] = field(default_factory=list)


def _safe_archive(bundle: zipfile.ZipFile) -> list[str]:
    names = bundle.namelist()
    for name in names:
        target = Path(name)
        if target.is_absolute() or ".." in target.parts:
            raise MinerUParseError("MinerU returned an unsafe ZIP path")
    return names


def _normalized_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return None


def _join_text(parts: list[str], *, separator: str = "\n") -> str:
    return separator.join(part.strip() for part in parts if str(part).strip()).strip()


def _content_text(value: Any) -> str:
    """Render MinerU inline content without discarding formulas or line breaks."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        rendered: list[str] = []
        for item in value:
            text = _content_text(item)
            if text:
                rendered.append(text)
        return "".join(rendered).strip()
    if not isinstance(value, dict):
        return str(value).strip()

    item_type = str(value.get("type") or "").lower()
    direct = value.get("content")
    if isinstance(direct, str) and direct.strip():
        if item_type in {"equation", "equation_inline", "formula"}:
            return direct.strip()
        return direct.strip()
    for key in (
        "text",
        "title_content",
        "paragraph_content",
        "code_content",
        "equation_content",
        "table_body",
        "table_content",
        "table_caption",
        "table_footnote",
        "image_content",
        "image_caption",
        "image_footnote",
        "chart_content",
        "chart_caption",
        "chart_footnote",
        "list_content",
        "caption",
        "footnote",
        "items",
    ):
        if key in value:
            text = _content_text(value[key])
            if text:
                return text
    if isinstance(direct, (list, dict)):
        return _content_text(direct)
    return ""


def _field_text(block: dict[str, Any], *keys: str) -> str:
    parts = [_content_text(block.get(key)) for key in keys if key in block]
    return _join_text(parts)


def _find_media_path(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            found = _find_media_path(item)
            if found:
                return found
        return ""
    if not isinstance(value, dict):
        return ""
    for key in ("img_path", "image_path", "image_url", "media_path", "path"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip() and (
            key != "path" or re.search(r"\.(?:png|jpe?g|webp|gif|bmp|tiff?)$", candidate, re.IGNORECASE)
        ):
            return candidate.strip()
    if str(value.get("type") or "").lower() in {"image", "figure", "chart"}:
        candidate = value.get("content")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    for candidate in value.values():
        found = _find_media_path(candidate)
        if found:
            return found
    return ""


def _render_block(block: dict[str, Any], kind: str) -> str:
    content = block.get("content")
    if kind == "table":
        return _field_text(
            block,
            "table_caption",
            "table_body",
            "table_content",
            "table_footnote",
        ) or _content_text(content)
    if kind in {"image", "chart"}:
        return _field_text(
            block,
            "content",
            "image_caption",
            "image_footnote",
            "chart_caption",
            "chart_footnote",
            "caption",
            "footnote",
        )
    if kind == "formula":
        return _field_text(block, "text", "equation_content", "formula") or _content_text(content)
    if kind == "code":
        return _field_text(block, "text", "code_body", "code_content") or _content_text(content)
    return _field_text(block, "text") or _content_text(content)


def _metadata(block: dict[str, Any], raw_type: str) -> dict[str, Any]:
    ignored = {"bbox", "content", "text", "table_body", "table_content", "code_body", "code_content"}
    value = {key: item for key, item in block.items() if key not in ignored}
    value["mineru_type"] = raw_type
    if raw_type in {"image", "figure", "chart"} and "content" in block:
        # Image nodes often carry nested OCR/caption/asset children. Preserve
        # that structure in parsed.json even when only their textual rendering
        # is sent to the embedding model.
        value["mineru_content"] = block["content"]
    return value


def _legacy_blocks(payload: Any) -> tuple[list[dict[str, Any]], int | None]:
    if not isinstance(payload, list):
        raise MinerUParseError("MinerU legacy content list must be an array")
    output: list[dict[str, Any]] = []
    max_page = -1
    for index, raw in enumerate(payload):
        if not isinstance(raw, dict):
            continue
        page_idx = raw.get("page_idx")
        try:
            page = int(page_idx) + 1 if page_idx is not None else None
        except (TypeError, ValueError):
            page = None
        if page is not None:
            max_page = max(max_page, page)
        raw_type = str(raw.get("type") or "paragraph").lower()
        if raw_type in _NOISE_TYPES:
            continue
        kind = _KIND_MAP.get(raw_type, "paragraph")
        level = raw.get("text_level")
        if raw_type == "text" and level is not None:
            kind = "heading"
        try:
            heading_level = int(level) if level is not None else None
        except (TypeError, ValueError):
            heading_level = None
        output.append(
            {
                "text": _render_block(raw, kind),
                "kind": kind,
                "page": page,
                "heading_level": heading_level,
                "bbox": _normalized_bbox(raw.get("bbox")),
                "media_path": _find_media_path(raw),
                "node_path": str(index),
                "metadata": _metadata(raw, raw_type),
            }
        )
    return output, max_page if max_page >= 0 else None


def _v2_blocks(payload: Any) -> tuple[list[dict[str, Any]], int | None]:
    if isinstance(payload, dict):
        payload = payload.get("pages") or payload.get("content_list") or payload.get("blocks")
    if not isinstance(payload, list):
        raise MinerUParseError("MinerU v2 content list must be an array")
    nested_pages = all(isinstance(page, list) for page in payload)
    pages = payload if nested_pages else [payload]
    output: list[dict[str, Any]] = []
    max_page = 0
    for page_index, page_blocks in enumerate(pages, start=1):
        for block_index, raw in enumerate(page_blocks):
            if not isinstance(raw, dict):
                continue
            explicit_page = raw.get("page_number")
            if explicit_page is None and raw.get("page_idx") is not None:
                try:
                    explicit_page = int(raw["page_idx"]) + 1
                except (TypeError, ValueError):
                    explicit_page = None
            try:
                block_page = int(explicit_page) if explicit_page is not None else page_index
            except (TypeError, ValueError):
                block_page = page_index
            max_page = max(max_page, block_page)
            raw_type = str(raw.get("type") or "paragraph").lower()
            if raw_type in _NOISE_TYPES:
                continue
            kind = _KIND_MAP.get(raw_type, "paragraph")
            content = raw.get("content") if isinstance(raw.get("content"), dict) else {}
            level = content.get("level", raw.get("level"))
            try:
                heading_level = int(level) if level is not None else None
            except (TypeError, ValueError):
                heading_level = None
            media_path = _find_media_path(raw)
            output.append(
                {
                    "text": _render_block(raw, kind),
                    "kind": kind,
                    "page": block_page,
                    "heading_level": heading_level,
                    "bbox": _normalized_bbox(raw.get("bbox")),
                    "media_path": media_path,
                    "node_path": f"{block_page - 1}.{block_index}",
                    "metadata": _metadata(raw, raw_type),
                }
            )
    return output, max(max_page, len(pages) if nested_pages else 0) or None


def _finalize_blocks(raw_blocks: list[dict[str, Any]]) -> tuple[str, list[MinerUStructuredBlock], list[str]]:
    section: list[str] = []
    blocks: list[MinerUStructuredBlock] = []
    warnings: list[str] = []
    cursor = 0
    for raw in raw_blocks:
        text = str(raw.get("text") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        kind = str(raw.get("kind") or "paragraph")
        if kind == "heading":
            level = max(1, int(raw.get("heading_level") or 1))
            section = section[: level - 1] + [text]
        if not text:
            if kind in {"image", "chart"} and raw.get("media_path"):
                text = f"[{kind}: {raw['media_path']}]"
                warnings.append("media_node_without_caption")
            else:
                warnings.append(f"empty_{kind}_node_skipped")
                continue
        block = MinerUStructuredBlock(
            text=text,
            kind=kind,
            page_start=raw.get("page"),
            page_end=raw.get("page"),
            section_path=list(section),
            start_index=cursor,
            heading_level=raw.get("heading_level"),
            bbox=raw.get("bbox"),
            media_path=str(raw.get("media_path") or ""),
            node_path=str(raw.get("node_path") or ""),
            metadata=dict(raw.get("metadata") or {}),
        )
        blocks.append(block)
        cursor += len(text) + 2
    text = "\n\n".join(block.text for block in blocks)
    return text, blocks, list(dict.fromkeys(warnings))


def _markdown_fallback(markdown: str) -> MinerUStructuredResult:
    blocks: list[dict[str, Any]] = []
    for index, value in enumerate(re.split(r"\n\s*\n", markdown)):
        text = value.strip()
        if not text:
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", text)
        if heading:
            kind = "heading"
            level = len(heading.group(1))
            text = heading.group(2).strip()
        elif text.startswith("```") and text.endswith("```"):
            kind = "code"
            level = None
        else:
            kind = "paragraph"
            level = None
        blocks.append(
            {
                "text": text,
                "kind": kind,
                "page": None,
                "heading_level": level,
                "bbox": None,
                "media_path": "",
                "node_path": str(index),
                "metadata": {"mineru_type": "markdown_fallback"},
            }
        )
    text, structured, warnings = _finalize_blocks(blocks)
    if not text:
        raise MinerUParseError("MinerU result is empty")
    return MinerUStructuredResult(text, markdown.strip(), structured, None, "markdown", warnings)


class MinerUParser:
    """MinerU asynchronous client plus a schema-preserving archive adapter."""

    def __init__(self, *, client_factory=httpx.AsyncClient):
        self.client_factory = client_factory

    @staticmethod
    def _api_url(base_url: str, path: str) -> str:
        return f"{base_url.rstrip('/')}/{path.lstrip('/')}"

    @staticmethod
    def parse_archive(archive: bytes) -> MinerUStructuredResult:
        try:
            with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                names = _safe_archive(bundle)
                markdown_name = next((name for name in names if Path(name).name == "full.md"), None)
                markdown = bundle.read(markdown_name).decode("utf-8", errors="replace") if markdown_name else ""
                v2_name = next((name for name in names if Path(name).name.endswith("_content_list_v2.json")), None)
                legacy_name = next(
                    (
                        name
                        for name in names
                        if Path(name).name.endswith("_content_list.json")
                        and not Path(name).name.endswith("_content_list_v2.json")
                    ),
                    None,
                )
                if v2_name:
                    payload = json.loads(bundle.read(v2_name).decode("utf-8"))
                    raw_blocks, page_count = _v2_blocks(payload)
                    schema = "v2"
                elif legacy_name:
                    payload = json.loads(bundle.read(legacy_name).decode("utf-8"))
                    raw_blocks, page_count = _legacy_blocks(payload)
                    schema = "legacy"
                elif markdown:
                    return _markdown_fallback(markdown)
                else:
                    raise MinerUParseError("MinerU archive contains no supported structured result")
        except zipfile.BadZipFile as exc:
            raise MinerUParseError("MinerU result is not a valid ZIP archive") from exc
        except json.JSONDecodeError as exc:
            raise MinerUParseError("MinerU structured JSON is invalid") from exc

        text, blocks, warnings = _finalize_blocks(raw_blocks)
        if not text:
            if markdown:
                fallback = _markdown_fallback(markdown)
                return MinerUStructuredResult(
                    fallback.text,
                    fallback.markdown,
                    fallback.blocks,
                    fallback.page_count,
                    fallback.schema_version,
                    [*warnings, "structured_result_empty_markdown_fallback", *fallback.warnings],
                )
            raise MinerUParseError("MinerU structured result is empty")
        return MinerUStructuredResult(text, markdown.strip(), blocks, page_count, schema, warnings)

    @staticmethod
    def persist_artifacts(
        archive: bytes,
        result: MinerUStructuredResult,
        *,
        document_id: str,
    ) -> MinerUStructuredResult:
        settings = get_settings()
        artifact_key = hashlib.sha256(document_id.encode("utf-8")).hexdigest()[:24]
        root = (Path(settings.mineru_artifact_dir).resolve() / artifact_key).resolve()
        root.mkdir(parents=True, exist_ok=True)
        archive_path = root / "result.zip"
        archive_tmp = root / "result.zip.tmp"
        archive_tmp.write_bytes(archive)
        archive_tmp.replace(archive_path)

        updated_blocks: list[MinerUStructuredBlock] = []
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            names = _safe_archive(bundle)
            for block in result.blocks:
                if not block.media_path:
                    updated_blocks.append(block)
                    continue
                original = Path(block.media_path)
                member = next(
                    (
                        name
                        for name in names
                        if Path(name).as_posix() == original.as_posix()
                        or Path(name).as_posix().endswith("/" + original.as_posix())
                    ),
                    None,
                )
                if member is None:
                    updated_blocks.append(block)
                    continue
                relative = Path(*original.parts)
                target = (root / "assets" / relative).resolve()
                if root not in target.parents:
                    raise MinerUParseError("MinerU media path escaped the artifact directory")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.read(member))
                metadata = dict(block.metadata)
                metadata["mineru_media_path"] = block.media_path
                metadata["artifact_path"] = str(target)
                updated_blocks.append(replace(block, media_path=str(target), metadata=metadata))

        updated = replace(result, blocks=updated_blocks)
        normalized_path = root / "structured.json"
        normalized_tmp = root / "structured.json.tmp"
        normalized_tmp.write_text(
            json.dumps(
                {
                    "schema_version": updated.schema_version,
                    "page_count": updated.page_count,
                    "warnings": updated.warnings,
                    "blocks": [asdict(block) for block in updated.blocks],
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        normalized_tmp.replace(normalized_path)
        return updated

    @staticmethod
    def _extract_markdown(archive: bytes) -> str:
        """Compatibility helper; preserves Markdown line structure."""
        result = MinerUParser.parse_archive(archive)
        return result.markdown or result.text

    async def parse_structured(
        self,
        path: str,
        *,
        document_id: str,
        original_name: str,
        is_ocr: bool | None = None,
    ) -> MinerUStructuredResult:
        settings = get_settings()
        token = settings.mineru_api_token
        if not token:
            raise RuntimeError("MINERU_API_TOKEN is not configured")
        extension = Path(original_name).suffix.lower()
        model_version = "MinerU-HTML" if extension in {".html", ".htm"} else settings.mineru_model_version
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        request_data = {
            "files": [{"name": Path(original_name).name, "data_id": document_id}],
            "model_version": model_version,
            "is_ocr": settings.mineru_enable_ocr if is_ocr is None else bool(is_ocr),
            "enable_formula": settings.mineru_enable_formula,
            "enable_table": settings.mineru_enable_table,
            "language": "ch",
        }
        started = asyncio.get_running_loop().time()
        timeout = max(30.0, float(settings.mineru_timeout_seconds))
        async with self.client_factory(timeout=httpx.Timeout(min(timeout, 60.0))) as client:
            response = await client.post(
                self._api_url(settings.mineru_api_base_url, "/api/v4/file-urls/batch"),
                headers={**headers, "Content-Type": "application/json"},
                json=request_data,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != 0:
                raise RuntimeError(f"MinerU task creation failed: {payload.get('msg', 'unknown error')}")
            data = payload.get("data") or {}
            batch_id = str(data.get("batch_id") or "")
            file_urls = data.get("file_urls") or []
            if not batch_id or not file_urls:
                raise RuntimeError("MinerU task response is missing batch_id or file_urls")
            upload = await client.put(file_urls[0], content=Path(path).read_bytes(), headers={"Accept": "*/*"})
            upload.raise_for_status()

            result_url = self._api_url(settings.mineru_api_base_url, f"/api/v4/extract-results/batch/{batch_id}")
            while True:
                if asyncio.get_running_loop().time() - started > timeout:
                    raise TimeoutError("MinerU parsing timed out")
                result_response = await client.get(result_url, headers=headers)
                result_response.raise_for_status()
                result_payload = result_response.json()
                if result_payload.get("code") != 0:
                    raise RuntimeError(f"MinerU task query failed: {result_payload.get('msg', 'unknown error')}")
                results = (result_payload.get("data") or {}).get("extract_result") or []
                current = next(
                    (item for item in results if str(item.get("file_name", "")) == Path(original_name).name),
                    results[0] if results else None,
                )
                state = str((current or {}).get("state") or "pending").lower()
                if state == "done":
                    zip_url = str((current or {}).get("full_zip_url") or "")
                    if not zip_url:
                        raise RuntimeError("MinerU task completed without full_zip_url")
                    archive_response = None
                    download_error: Exception | None = None
                    download_attempts = max(1, int(settings.mineru_download_retries) + 1)
                    for attempt in range(download_attempts):
                        try:
                            # Result ZIPs can be much larger than the polling
                            # responses. Use a dedicated timeout and retry
                            # transient proxy/TLS disconnects.
                            async with self.client_factory(
                                timeout=httpx.Timeout(float(settings.mineru_download_timeout_seconds))
                            ) as download_client:
                                archive_response = await download_client.get(zip_url)
                                archive_response.raise_for_status()
                            break
                        except (httpx.HTTPError, OSError) as exc:
                            download_error = exc
                            if attempt < download_attempts - 1:
                                await asyncio.sleep(min(1.0 * (attempt + 1), 4.0))
                    if archive_response is None:
                        raise RuntimeError("MinerU result download failed") from download_error
                    parsed = self.parse_archive(archive_response.content)
                    return self.persist_artifacts(
                        archive_response.content,
                        parsed,
                        document_id=document_id,
                    )
                if state == "failed":
                    raise RuntimeError(f"MinerU parsing failed: {(current or {}).get('err_msg') or 'unknown error'}")
                await asyncio.sleep(max(1.0, float(settings.mineru_poll_interval_seconds)))

    async def parse(self, path: str, *, document_id: str, original_name: str) -> str:
        result = await self.parse_structured(path, document_id=document_id, original_name=original_name)
        return result.markdown or result.text
