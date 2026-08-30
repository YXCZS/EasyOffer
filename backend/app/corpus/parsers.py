from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import re
from collections import Counter
from pathlib import Path

from app.corpus.models import ParsedBlock, ParsedDocument, SourceEntry
from app.core.config import get_settings
from app.services.mineru_service import MinerUParser, MinerUStructuredResult


logger = logging.getLogger(__name__)


class CorpusParseError(ValueError):
    pass


MOJIBAKE_MARKERS = ("锟斤拷", "ï¿½", "Ã", "Â", "�")


def clean_text(text: str) -> tuple[str, list[str]]:
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    warnings: list[str] = []
    cleaned = re.sub(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]", " ", raw)
    if cleaned != raw:
        warnings.append("control_characters_removed")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if any(marker in cleaned for marker in MOJIBAKE_MARKERS):
        warnings.append("possible_mojibake")
    return cleaned, warnings


def _remove_repeated_page_edges(pages: list[str]) -> tuple[list[str], list[str]]:
    if len(pages) < 3:
        return pages, []
    edges: list[str] = []
    page_lines: list[list[str]] = []
    for page in pages:
        lines = [line.strip() for line in page.splitlines() if line.strip()]
        page_lines.append(lines)
        if lines:
            edges.extend([lines[0], lines[-1]])
    threshold = max(3, int(len(pages) * 0.6))
    repeated = {line for line, count in Counter(edges).items() if count >= threshold and len(line) < 120}
    if not repeated:
        return pages, []
    output = ["\n".join(line for line in lines if line not in repeated) for lines in page_lines]
    return output, ["repeated_headers_or_footers_removed"]


def _blocks_from_text(text: str, *, page: int | None = None) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    section: list[str] = []
    cursor = 0
    for raw in re.split(r"\n\s*\n", text):
        value = raw.strip()
        if not value:
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", value)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()
            section = section[: level - 1] + [title]
            kind = "heading"
            block_text = title
            heading_level = level
        else:
            if value.startswith("```") and value.endswith("```"):
                kind = "code"
            elif value.startswith("$$") and value.endswith("$$"):
                kind = "formula"
            elif re.search(r"!\[[^]]*]\([^)]+\)", value):
                kind = "image"
            elif len(value.splitlines()) >= 2 and all("|" in line for line in value.splitlines()):
                kind = "table"
            elif all(re.match(r"^(?:[-*+] |\d+[.)] )", line.strip()) for line in value.splitlines() if line.strip()):
                kind = "list"
            else:
                kind = "paragraph"
            block_text = value
            heading_level = None
        start = text.find(raw, cursor)
        cursor = max(cursor, start + len(raw))
        blocks.append(
            ParsedBlock(
                text=block_text,
                kind=kind,
                page_start=page,
                page_end=page,
                section_path=list(section),
                start_index=max(0, start),
                heading_level=heading_level,
            )
        )
    return blocks


def _parse_markdown(path: Path, source: SourceEntry) -> ParsedDocument:
    raw = path.read_text(encoding="utf-8", errors="replace")
    text, warnings = clean_text(raw)
    if not text:
        raise CorpusParseError("empty_document")
    return ParsedDocument(source=source, text=text, blocks=_blocks_from_text(text), warnings=warnings)


def _parse_docx(path: Path, source: SourceEntry) -> ParsedDocument:
    import docx2txt

    try:
        raw = docx2txt.process(str(path)) or ""
    except Exception as exc:
        raise CorpusParseError(f"unreadable_docx:{type(exc).__name__}") from exc
    text, warnings = clean_text(raw)
    if not text:
        raise CorpusParseError("empty_document")
    return ParsedDocument(source=source, text=text, blocks=_blocks_from_text(text), warnings=warnings)


def _parse_pdf(path: Path, source: SourceEntry) -> ParsedDocument:
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise CorpusParseError("encrypted_pdf")
        raw_pages = [(page.extract_text() or "") for page in reader.pages]
    except CorpusParseError:
        raise
    except Exception as exc:
        raise CorpusParseError(f"unreadable_pdf:{type(exc).__name__}") from exc
    pages, edge_warnings = _remove_repeated_page_edges(raw_pages)
    cleaned_pages: list[str] = []
    warnings = list(edge_warnings)
    for page in pages:
        cleaned, page_warnings = clean_text(page)
        cleaned_pages.append(cleaned)
        warnings.extend(page_warnings)
    if not any(cleaned_pages):
        raise CorpusParseError("scanned_or_empty_pdf")
    blocks: list[ParsedBlock] = []
    offset = 0
    for page_index, page_text in enumerate(cleaned_pages, start=1):
        for block in _blocks_from_text(page_text, page=page_index):
            blocks.append(
                ParsedBlock(
                    text=block.text,
                    kind=block.kind,
                    page_start=page_index,
                    page_end=page_index,
                    section_path=block.section_path,
                    start_index=offset + block.start_index,
                    heading_level=block.heading_level,
                    bbox=block.bbox,
                    media_path=block.media_path,
                    mineru_node_path=block.mineru_node_path,
                    metadata=block.metadata,
                )
            )
        offset += len(page_text) + 2
    text = "\n\n".join(page for page in cleaned_pages if page)
    return ParsedDocument(
        source=source,
        text=text,
        blocks=blocks,
        page_count=len(raw_pages),
        warnings=list(dict.fromkeys(warnings)),
    )


def parsed_document_from_mineru(result: MinerUStructuredResult, source: SourceEntry) -> ParsedDocument:
    return ParsedDocument(
        source=source,
        text=result.text,
        blocks=[
            ParsedBlock(
                text=block.text,
                kind=block.kind,
                page_start=block.page_start,
                page_end=block.page_end,
                section_path=list(block.section_path),
                start_index=block.start_index,
                heading_level=block.heading_level,
                bbox=list(block.bbox) if block.bbox else None,
                media_path=block.media_path,
                mineru_node_path=block.node_path,
                metadata=dict(block.metadata),
            )
            for block in result.blocks
        ],
        page_count=result.page_count,
        warnings=list(result.warnings),
        parser_name="mineru",
        parser_schema=result.schema_version,
        metadata={"markdown_available": bool(result.markdown)},
    )


def _parse_source_locally(source: SourceEntry) -> ParsedDocument:
    path = source.resolved_path
    if path is None:
        raise CorpusParseError("remote_source_not_cached")
    if not path.exists() or not path.is_file():
        raise CorpusParseError("source_file_not_found")
    if source.content_type == "pdf":
        return _parse_pdf(path, source)
    if source.content_type == "docx":
        return _parse_docx(path, source)
    if source.content_type == "markdown":
        return _parse_markdown(path, source)
    raise CorpusParseError("remote_source_not_cached")


async def parse_source_async(source: SourceEntry) -> ParsedDocument:
    path = source.resolved_path
    if path is None:
        raise CorpusParseError("remote_source_not_cached")
    if not path.exists() or not path.is_file():
        raise CorpusParseError("source_file_not_found")

    settings = get_settings()
    mineru_types = {"pdf", "docx", "ppt", "pptx", "xls", "xlsx", "html", "image"}
    if settings.mineru_enabled and settings.mineru_api_token and source.content_type in mineru_types:
        try:
            result = await MinerUParser().parse_structured(
                str(path),
                document_id=source.document_id,
                original_name=path.name,
            )
            return parsed_document_from_mineru(result, source)
        except Exception as exc:
            logger.warning(
                "public_mineru_parse_failed document_id=%s failure_type=%s",
                source.document_id,
                type(exc).__name__,
            )
            if source.content_type not in {"pdf", "docx"}:
                raise CorpusParseError(f"mineru_failed:{type(exc).__name__}") from exc
            parsed = _parse_source_locally(source)
            parsed.warnings.append(f"mineru_unavailable_local_fallback:{type(exc).__name__}")
            return parsed
    if source.content_type in mineru_types and source.content_type not in {"pdf", "docx"}:
        reason = "disabled" if not settings.mineru_enabled else "token_missing"
        raise CorpusParseError(f"mineru_unavailable:{reason}")
    parsed = _parse_source_locally(source)
    if source.content_type in {"pdf", "docx"} and (not settings.mineru_enabled or not settings.mineru_api_token):
        reason = "disabled" if not settings.mineru_enabled else "token_missing"
        parsed.warnings.append(f"mineru_unavailable_local_fallback:{reason}")
    return parsed


def parse_source(source: SourceEntry) -> ParsedDocument:
    """Synchronous corpus entry point, safe even when called under an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(parse_source_async(source))
    # CorpusPipeline is synchronous. If an async host invokes it, isolate the
    # MinerU coroutine in a worker thread instead of nesting asyncio.run().
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="mineru-parser") as executor:
        return executor.submit(lambda: asyncio.run(parse_source_async(source))).result()
