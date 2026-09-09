from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import re
import time
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

import httpx

from app.corpus.models import ParsedBlock, ParsedDocument
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class VisualAnalysisError(ValueError):
    """The visual provider returned an unusable or unavailable result."""


@dataclass(frozen=True)
class VisualAnalysis:
    visual_type: str
    title: str
    summary: str
    elements: list[dict[str, Any]]
    relations: list[dict[str, Any]]
    uncertainties: list[str]
    confidence: float
    model_version: str
    status: str = "ready"
    page: int | None = None
    bbox: list[float] | None = None
    headers: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    merged_cells: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "visual_type": self.visual_type,
            "title": self.title,
            "summary": self.summary,
            "elements": self.elements,
            "relations": self.relations,
            "uncertainties": self.uncertainties,
            "confidence": self.confidence,
            "model_version": self.model_version,
            "status": self.status,
            "page": self.page,
            "bbox": self.bbox,
            "headers": self.headers or [],
            "rows": self.rows or [],
            "merged_cells": self.merged_cells or [],
        }

    @property
    def evidence_text(self) -> str:
        parts = [self.title.strip(), self.summary.strip()]
        for item in self.elements:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("label") or "").strip())
        for item in self.relations:
            if isinstance(item, dict):
                source = item.get("from") or item.get("source") or ""
                target = item.get("to") or item.get("target") or ""
                relation = item.get("relation") or item.get("label") or ""
                parts.append(f"{source} {relation} {target}".strip())
        return "\n".join(item for item in parts if item)


def _extract_json(value: str) -> dict[str, Any]:
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise VisualAnalysisError("visual_analysis_invalid")
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise VisualAnalysisError("visual_analysis_invalid") from exc
    if not isinstance(payload, dict):
        raise VisualAnalysisError("visual_analysis_invalid")
    return payload


def validate_visual_payload(payload: dict[str, Any], *, model_version: str) -> VisualAnalysis:
    required = ("visual_type", "title", "summary", "elements", "relations", "uncertainties", "confidence")
    if any(key not in payload for key in required):
        raise VisualAnalysisError("visual_analysis_invalid")
    if not isinstance(payload["elements"], list) or not isinstance(payload["relations"], list):
        raise VisualAnalysisError("visual_analysis_invalid")
    if not isinstance(payload["uncertainties"], list):
        raise VisualAnalysisError("visual_analysis_invalid")
    try:
        confidence = min(1.0, max(0.0, float(payload["confidence"])))
    except (TypeError, ValueError) as exc:
        raise VisualAnalysisError("visual_analysis_invalid") from exc
    headers = payload.get("headers") or []
    rows = payload.get("rows") or []
    merged_cells = payload.get("merged_cells") or []
    if not isinstance(headers, list) or not isinstance(rows, list) or not isinstance(merged_cells, list):
        raise VisualAnalysisError("visual_analysis_invalid")
    bbox = payload.get("bbox")
    if bbox is not None and (not isinstance(bbox, list) or len(bbox) != 4):
        raise VisualAnalysisError("visual_analysis_invalid")
    return VisualAnalysis(
        visual_type=str(payload["visual_type"])[:40],
        title=str(payload["title"])[:200],
        summary=str(payload["summary"])[:4000],
        elements=[item for item in payload["elements"] if isinstance(item, dict)],
        relations=[item for item in payload["relations"] if isinstance(item, dict)],
        uncertainties=[str(item)[:300] for item in payload["uncertainties"]],
        confidence=confidence,
        model_version=model_version,
        page=int(payload["page"]) if payload.get("page") is not None else None,
        bbox=[float(item) for item in bbox] if bbox is not None else None,
        headers=[str(item) for item in headers],
        rows=[item for item in rows if isinstance(item, list)],
        merged_cells=[item for item in merged_cells if isinstance(item, dict)],
    )


def validate_table_analysis(analysis: VisualAnalysis, *, ocr_text: str = "") -> bool:
    """Conservative cross-check for table output; never invents cells."""
    if analysis.visual_type not in {"table", "chart", "flowchart"}:
        return True
    if not analysis.elements:
        return False
    if analysis.visual_type == "table":
        if analysis.headers and analysis.rows and any(len(row) != len(analysis.headers) for row in analysis.rows):
            return False
        has_row_like = any(any(key in item for key in ("row", "cells", "columns", "text", "label")) for item in analysis.elements)
        if not has_row_like and not analysis.rows:
            return False
    # When OCR found numeric tokens, require at least one matching token in
    # the structured result. This catches malformed table JSON without
    # rejecting non-numeric prose tables.
    numbers = set(re.findall(r"\d+(?:\.\d+)?", ocr_text))
    if numbers:
        rendered = json.dumps(analysis.elements, ensure_ascii=False)
        if not any(number in rendered for number in numbers):
            return False
    return True


class QwenVLClient:
    """Small OpenAI-compatible DashScope Qwen-VL client for document assets."""

    def __init__(self, *, client_factory=httpx.AsyncClient):
        self.client_factory = client_factory

    async def analyze(self, image: bytes, *, mode: str, context: str = "") -> VisualAnalysis:
        settings = get_settings()
        api_key = settings.dashscope_api_key
        if not api_key:
            raise VisualAnalysisError("visual_provider_not_configured")
        encoded = base64.b64encode(image).decode("ascii")
        prompt = (
            "你是文档视觉解析器。只返回 JSON，不要 Markdown。"
            "字段必须为 visual_type,title,summary,elements,relations,uncertainties,confidence,page,bbox,headers,rows,merged_cells。"
            "保留无法确认的信息到 uncertainties，不要猜测。"
        )
        if mode == "ocr":
            prompt += "这是文字图片，请准确转写可见文字；visual_type 使用 text_image。"
        else:
            prompt += "这是技术图表、流程图或复杂表格，请恢复节点、行列和关系。"
        if context:
            prompt += f"章节上下文：{context[:1000]}"
        payload = {
            "model": settings.document_visual_model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
                ],
            }],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        # DashScope recommends a workspace-scoped regional endpoint for Model
        # Studio calls.  Keep explicit proxy/custom endpoints unchanged while
        # deriving the official endpoint from workspace + region when the
        # generic public URL is configured.
        configured_endpoint = str(settings.document_visual_base_url or "").strip().rstrip("/")
        preferred_endpoint = dashscope_visual_endpoint(settings).rstrip("/")
        endpoint_bases = [preferred_endpoint]
        # Some DashScope workspaces do not expose the regional subdomain (or
        # DNS is unavailable in a private network). Keep the documented
        # generic endpoint as a connection fallback while retaining the
        # workspace header for request routing.
        if configured_endpoint and configured_endpoint not in endpoint_bases:
            endpoint_bases.append(configured_endpoint)
        timeout = httpx.Timeout(settings.document_visual_timeout_seconds)
        headers = {"Authorization": f"Bearer {api_key}"}
        workspace_id = str(settings.dashscope_workspace_id or "").strip()
        if workspace_id:
            # DashScope's OpenAI-compatible API uses the same workspace header
            # as the native SDK's ``workspace=...`` parameter.
            headers["X-DashScope-WorkSpace"] = workspace_id
        last_error: Exception | None = None
        for endpoint_index, endpoint_base in enumerate(endpoint_bases):
            endpoint = endpoint_base + "/chat/completions"
            for attempt in range(max(1, settings.document_visual_max_retries + 1)):
                try:
                    async with self.client_factory(timeout=timeout) as client:
                        response = await client.post(endpoint, headers=headers, json=payload)
                        response.raise_for_status()
                        body = response.json()
                        content = body["choices"][0]["message"]["content"]
                        if isinstance(content, list):
                            content = "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
                        return validate_visual_payload(_extract_json(str(content)), model_version=settings.document_visual_model)
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    try:
                        body = exc.response.json()
                        error_payload = body.get("error") or {}
                        code = str(error_payload.get("code") or "")
                        message = str(error_payload.get("message") or "")
                    except Exception:
                        code = ""
                        message = ""
                    quota_text = f"{code} {message}".lower()
                    if status in {401, 403} and any(token in quota_text for token in ("quota", "allocation", "free tier", "insufficient_quota")):
                        last_error = VisualAnalysisError("visual_quota_exhausted")
                    elif status in {401, 403}:
                        last_error = VisualAnalysisError("visual_provider_unauthorized")
                    elif status == 429:
                        last_error = VisualAnalysisError("visual_provider_rate_limited")
                    else:
                        last_error = VisualAnalysisError("visual_provider_http_error")
                    # HTTP errors are authoritative; do not retry a second
                    # endpoint because it would hide auth/quota misconfiguration.
                    break
                except (httpx.HTTPError, KeyError, IndexError, TypeError, VisualAnalysisError) as exc:
                    last_error = exc
                    if attempt < settings.document_visual_max_retries:
                        await asyncio.sleep(min(0.5 * (attempt + 1), 2.0))
                    elif endpoint_index < len(endpoint_bases) - 1:
                        logger.info("visual_endpoint_fallback endpoint_index=%d failure_type=%s", endpoint_index, type(exc).__name__)
                        break
        if isinstance(last_error, VisualAnalysisError):
            raise last_error
        raise VisualAnalysisError("visual_analysis_failed") from last_error


class OCRProvider:
    """Document OCR facade. The default implementation uses Qwen-VL so the
    provider can be replaced by PaddleOCR without changing the ingestion flow.
    """

    def __init__(self, client: QwenVLClient | None = None):
        self.client = client or QwenVLClient()

    async def recognize(self, image: bytes) -> VisualAnalysis:
        return await self.client.analyze(image, mode="ocr")


def dashscope_visual_endpoint(settings: Any) -> str:
    """Return the official regional endpoint for OpenAI-compatible vision calls.

    DashScope documents Workspace-specific subdomains for regional Model Studio
    requests. Keep an explicitly configured non-generic URL intact so tests and
    deployments using a proxy remain supported.
    """
    configured = str(settings.document_visual_base_url or "").strip().rstrip("/")
    workspace = str(settings.dashscope_workspace_id or "").strip()
    region = str(settings.dashscope_region or "cn-beijing").strip()
    generic_hosts = {
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    }
    if workspace and (not configured or configured in generic_hosts):
        return f"https://{workspace}.{region}.maas.aliyuncs.com/compatible-mode/v1"
    return configured


def extract_docx_images(path: str | Path, output_dir: str | Path) -> list[Path]:
    """Extract only Word media members, preventing ZIP path traversal."""
    source = Path(path)
    target = Path(output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    result: list[Path] = []
    with zipfile.ZipFile(source) as archive:
        for name in archive.namelist():
            member = Path(name)
            if not name.startswith("word/media/") or member.name in {"", ".", ".."}:
                continue
            destination = (target / member.name).resolve()
            if target not in destination.parents:
                raise VisualAnalysisError("unsafe_media_path")
            destination.write_bytes(archive.read(name))
            result.append(destination)
    return result


_VISUAL_HINTS = (
    "流程图", "架构图", "时序图", "关系图", "类图", "状态图", "拓扑图",
    "图表", "柱状图", "折线图", "饼图", "散点图", "复杂表格", "表格",
    "chart", "diagram", "flowchart", "figure", "table", "graph",
)


def _path_key(path: str | Path) -> str:
    try:
        return str(Path(path).resolve()).lower()
    except (OSError, RuntimeError):
        return str(path).lower()


def _classify_image_mode(
    path: Path,
    *,
    block_kind: str = "",
    metadata: dict[str, Any] | None = None,
    ocr_text: str = "",
    source_type: str = "",
) -> tuple[str, str]:
    """Prefer MinerU structure/context; use filename only as a legacy fallback."""
    metadata = metadata or {}
    kind = str(block_kind or "").lower().strip()
    mineru_type = str(metadata.get("mineru_type") or metadata.get("type") or "").lower().strip()
    source = str(source_type or metadata.get("source_type") or "").lower().strip()
    context = " ".join(
        str(metadata.get(key) or "")
        for key in ("caption", "title", "image_caption", "chart_caption", "table_caption", "mineru_content")
    )
    context = f"{context} {ocr_text}".lower()
    if source == "scanned_pdf_page":
        return "ocr", "scanned_pdf_page"
    if kind in {"chart", "table"} or mineru_type in {"chart", "figure", "table"}:
        return "visual", f"structured_node:{mineru_type or kind}"
    if any(hint in context for hint in _VISUAL_HINTS):
        return "visual", "caption_or_context_hint"
    name = path.stem.lower()
    if any(token in name for token in ("chart", "flow", "table", "figure", "diagram")):
        return "visual", "filename_fallback"
    return "ocr", "default_ocr"


def classify_image_mode(
    path: Path,
    *,
    block_kind: str = "",
    metadata: dict[str, Any] | None = None,
    ocr_text: str = "",
    source_type: str = "",
) -> str:
    return _classify_image_mode(
        path,
        block_kind=block_kind,
        metadata=metadata,
        ocr_text=ocr_text,
        source_type=source_type,
    )[0]


def _image_mode(path: Path, **kwargs: Any) -> str:
    return classify_image_mode(path, **kwargs)


def _decorative_reason(path: Path) -> str | None:
    if any(token in path.stem.lower() for token in ("logo", "avatar", "icon", "decoration", "背景")):
        return "decorative_filename"
    try:
        from PIL import Image
        with Image.open(path) as image:
            if image.width < 64 or image.height < 64:
                return "decorative_small_image"
    except Exception:
        return None
    return None


async def enrich_document_visuals(
    parsed: ParsedDocument,
    path: str | Path,
    *,
    document_id: str,
    media_root: str | Path,
    client: QwenVLClient | None = None,
) -> ParsedDocument:
    """Attach image blocks while isolating provider failures from text ingestion."""
    settings = get_settings()
    image_context: dict[str, dict[str, Any]] = {}
    image_context_by_name: dict[str, dict[str, Any] | None] = {}
    # MinerU stores DOCX media under the artifact directory while the DOCX
    # extractor writes the same members under a per-document media directory.
    # Keep exact-path matching as the primary key and add a basename fallback
    # only when that basename is unique within this document.
    for block in parsed.blocks:
        if not block.media_path:
            continue
        details = {
            "ocr_text": block.text,
            "bbox": block.bbox,
            "block_kind": block.kind,
            "page": block.page_start,
            "metadata": dict(block.metadata),
            "source_type": block.metadata.get("source_type", ""),
        }
        image_context[_path_key(block.media_path)] = details
        basename = Path(block.media_path).name.lower()
        if basename in image_context_by_name:
            image_context_by_name[basename] = None
        else:
            image_context_by_name[basename] = details
    if parsed.source.content_type == "docx":
        images = extract_docx_images(path, Path(media_root) / document_id / "word-media")
    elif parsed.source.content_type == "image":
        images = [Path(path)]
    else:
        images = [Path(block.media_path) for block in parsed.blocks if block.media_path and Path(block.media_path).exists()]
    images = images[: max(0, int(settings.document_visual_max_images))]
    if not images:
        return parsed
    client = client or QwenVLClient()
    started = time.perf_counter()
    semaphore = asyncio.Semaphore(max(1, settings.document_visual_max_concurrency))

    async def one(image_path: Path) -> ParsedBlock:
        metadata: dict[str, Any] = {
            "media_path": str(image_path),
            "visual_status": "skipped",
            "visual_type": "unknown",
            "source_document_id": document_id,
        }
        details = image_context.get(_path_key(image_path)) or image_context_by_name.get(image_path.name.lower()) or {}
        mode, route_reason = _classify_image_mode(
            image_path,
            block_kind=str(details.get("block_kind") or ""),
            metadata=details.get("metadata") or {},
            ocr_text=str(details.get("ocr_text") or ""),
            source_type=str(details.get("source_type") or ""),
        )
        metadata["visual_route"] = mode
        metadata["visual_route_reason"] = route_reason
        decorative_reason = _decorative_reason(image_path)
        if decorative_reason:
            metadata["visual_skip_reason"] = decorative_reason
            return ParsedBlock(f"[image: {image_path.name}]", "image", media_path=str(image_path), metadata=metadata, visual_status="skipped")
        if not settings.document_visual_enabled:
            metadata["visual_skip_reason"] = "feature_disabled"
            return ParsedBlock(f"[image: {image_path.name}]", "image", media_path=str(image_path), metadata=metadata, visual_status="skipped")
        try:
            content = image_path.read_bytes()
            async with semaphore:
                context = " > ".join(parsed.blocks[-1].section_path) if parsed.blocks else ""
                if details.get("ocr_text"):
                    context += f" OCR文本：{str(details['ocr_text'])[:2000]}"
                if details.get("bbox"):
                    context += f" bbox：{details['bbox']}"
                analysis = await client.analyze(content, mode=mode, context=context)
            if mode == "visual" and not validate_table_analysis(analysis, ocr_text=str(details.get("ocr_text") or "")):
                raise VisualAnalysisError("visual_analysis_invalid")
            metadata.update(analysis.as_dict())
            metadata["visual_status"] = analysis.status
            text = analysis.evidence_text or f"[image: {image_path.name}]"
            kind = "chart" if analysis.visual_type in {"chart", "flowchart", "table"} else "image"
            return ParsedBlock(text, kind, media_path=str(image_path), metadata=metadata, visual_type=analysis.visual_type, visual_status=analysis.status, visual_confidence=analysis.confidence)
        except Exception as exc:
            logger.warning("visual_analysis_failed document_id=%s path=%s failure_type=%s", document_id, image_path.name, type(exc).__name__)
            metadata.update({"visual_status": "degraded", "visual_error": str(exc)[:120] or "visual_analysis_failed"})
            return ParsedBlock(f"[image: {image_path.name}]", "image", media_path=str(image_path), metadata=metadata, visual_status="degraded")

    blocks = await asyncio.gather(*(one(image) for image in images))
    enriched = list(parsed.blocks)
    base_index = len(parsed.text) + 2
    existing_by_media = {
        str(Path(block.media_path).resolve()): index
        for index, block in enumerate(enriched)
        if block.media_path
    }
    for index, block in enumerate(blocks):
        media_key = str(Path(block.media_path).resolve()) if block.media_path else ""
        updated = replace(block, start_index=base_index + index * (len(block.text) + 2))
        existing_index = existing_by_media.get(media_key)
        if existing_index is None:
            enriched.append(updated)
        else:
            # MinerU/PDF fallback may already have created a traceable image
            # block. Replace it in place so visual enrichment never duplicates
            # a page or asset in the vector index.
            original = enriched[existing_index]
            enriched[existing_index] = replace(
                updated,
                metadata={**original.metadata, **updated.metadata},
                page_start=original.page_start,
                page_end=original.page_end,
                section_path=original.section_path,
                start_index=original.start_index,
                bbox=original.bbox,
            )
    metadata = dict(parsed.metadata)
    metadata["visual_assets"] = len(blocks)
    metadata["visual_metrics"] = {
        "asset_count": len(blocks),
        "ready_count": sum(block.metadata.get("visual_status") == "ready" for block in blocks),
        "degraded_count": sum(block.metadata.get("visual_status") == "degraded" for block in blocks),
        "skipped_count": sum(block.metadata.get("visual_status") == "skipped" for block in blocks),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    logger.info("document_visual_completed document_id=%s assets=%d ready=%d degraded=%d elapsed_ms=%s", document_id, len(blocks), metadata["visual_metrics"]["ready_count"], metadata["visual_metrics"]["degraded_count"], metadata["visual_metrics"]["elapsed_ms"])
    warnings = list(parsed.warnings)
    if any(block.metadata.get("visual_status") == "degraded" for block in blocks):
        warnings.append("visual_analysis_degraded")
    return replace(parsed, blocks=enriched, text=parsed.text + "\n\n" + "\n\n".join(block.text for block in blocks), metadata=metadata, warnings=list(dict.fromkeys(warnings)))


__all__ = ["OCRProvider", "QwenVLClient", "VisualAnalysis", "VisualAnalysisError", "classify_image_mode", "extract_docx_images", "enrich_document_visuals", "validate_visual_payload"]
