from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.corpus.file_detection import FileTypeDetectionError, detect_file_type, preflight_pdf, render_pdf_pages
from app.corpus.models import ParsedDocument, SourceEntry
from app.corpus.chunking import build_child_chunks, build_parent_units
from app.corpus.config import CorpusConfig
from app.corpus.models import ParsedBlock
from app.corpus.visual import VisualAnalysisError, enrich_document_visuals, extract_docx_images, validate_table_analysis, validate_visual_payload
from tests.corpus_fixtures import write_blank_pdf, write_text_pdf


def _source(path: Path, content_type: str) -> SourceEntry:
    return SourceEntry(
        document_id="visual-fixture",
        path=str(path),
        source_name=path.name,
        technology="RAG",
        role_tags=["backend"],
        document_version="v1",
        language="zh-CN",
        content_type=content_type,
        license_status="approved",
        target_corpus_version="personal",
    )


def test_file_detection_rejects_fake_pdf_and_accepts_png(tmp_path):
    with pytest.raises(FileTypeDetectionError, match="magic_bytes_mismatch"):
        detect_file_type("fake.pdf", "application/pdf", b"not a pdf")
    png = tmp_path / "image.png"
    from PIL import Image
    Image.new("RGB", (10, 10), "white").save(png)
    assert detect_file_type(png.name, "image/png", png.read_bytes()) == "image"


def test_file_detection_rejects_encrypted_pdf(tmp_path):
    from pypdf import PdfWriter
    pdf = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret")
    with pdf.open("wb") as output:
        writer.write(output)
    with pytest.raises(FileTypeDetectionError, match="encrypted_pdf"):
        detect_file_type(pdf.name, "application/pdf", pdf.read_bytes())


def test_pdf_preflight_classifies_text_and_scanned_pages(tmp_path):
    text_pdf = write_text_pdf(tmp_path / "text.pdf", "RAG retrieval and generation " * 4)
    profile = preflight_pdf(text_pdf)
    assert profile.content_profile == "text_pdf"
    assert profile.pages[0].profile == "text_page"
    blank_pdf = write_blank_pdf(tmp_path / "scan.pdf")
    scan_profile = preflight_pdf(blank_pdf)
    assert scan_profile.content_profile == "scanned_pdf"
    assert scan_profile.ocr_required is True


def test_pdf_preflight_classifies_mixed_document(tmp_path):
    from pypdf import PdfReader, PdfWriter
    text_pdf = write_text_pdf(tmp_path / "text-page.pdf", "RAG retrieval and generation " * 4)
    blank_pdf = write_blank_pdf(tmp_path / "scan-page.pdf")
    writer = PdfWriter()
    for source in (text_pdf, blank_pdf):
        reader = PdfReader(str(source))
        writer.add_page(reader.pages[0])
    mixed = tmp_path / "mixed.pdf"
    with mixed.open("wb") as output:
        writer.write(output)
    profile = preflight_pdf(mixed)
    assert profile.content_profile == "mixed_pdf"
    assert [page.profile for page in profile.pages] == ["text_page", "scanned_page"]


def test_parse_source_passes_dynamic_ocr_for_scanned_pdf(tmp_path, monkeypatch):
    from app.corpus.parsers import parse_source
    from app.services.mineru_service import MinerUParser, MinerUStructuredResult

    pdf = write_blank_pdf(tmp_path / "scan.pdf")
    seen = {}

    async def fake_parse(*_args, **kwargs):
        seen["is_ocr"] = kwargs.get("is_ocr")
        return MinerUStructuredResult("扫描文本", "", [], 1, "v2")

    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "mineru_enabled", True)
    monkeypatch.setattr(settings, "mineru_api_token", "configured")
    monkeypatch.setattr(MinerUParser, "parse_structured", fake_parse)
    monkeypatch.setattr(settings, "document_visual_enabled", False)
    parsed = parse_source(_source(pdf, "pdf"))
    assert seen["is_ocr"] is True
    assert parsed.metadata["pdf_preflight"]["content_profile"] == "scanned_pdf"


def test_scanned_pdf_keeps_rendered_pages_when_mineru_is_unavailable(tmp_path, monkeypatch):
    from app.corpus.parsers import parse_source
    from app.services.mineru_service import MinerUParser

    pdf = write_blank_pdf(tmp_path / "scan-fallback.pdf")

    async def failed_parse(*_args, **_kwargs):
        raise RuntimeError("temporary upstream failure")

    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "mineru_enabled", True)
    monkeypatch.setattr(settings, "mineru_api_token", "configured")
    monkeypatch.setattr(settings, "document_visual_enabled", False)
    monkeypatch.setattr(settings, "mineru_artifact_dir", str(tmp_path / "artifacts"))
    monkeypatch.setattr(MinerUParser, "parse_structured", failed_parse)
    parsed = parse_source(_source(pdf, "pdf"))
    assert parsed.parser_name == "pdf-page-render-fallback"
    assert len(parsed.blocks) == parsed.page_count
    assert parsed.blocks[0].metadata["ocr_status"] == "degraded"
    assert Path(parsed.blocks[0].media_path).exists()


def test_scanned_pdf_with_mineru_disabled_returns_degraded_page_blocks(tmp_path, monkeypatch):
    from app.corpus.parsers import parse_source

    pdf = write_blank_pdf(tmp_path / "scan-disabled.pdf")
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "mineru_enabled", False)
    monkeypatch.setattr(settings, "mineru_api_token", None)
    monkeypatch.setattr(settings, "mineru_artifact_dir", str(tmp_path / "artifacts"))

    parsed = parse_source(_source(pdf, "pdf"))
    assert parsed.parser_name == "pdf-page-render-fallback"
    assert parsed.parser_schema == "scanned-pages"
    assert parsed.blocks[0].metadata["ocr_status"] == "degraded"
    assert Path(parsed.blocks[0].media_path).exists()


def test_scanned_pdf_pages_are_rendered_with_stable_names(tmp_path):
    pdf = write_blank_pdf(tmp_path / "scan.pdf")
    rendered = render_pdf_pages(pdf, tmp_path / "pages")
    assert len(rendered) == 1
    assert rendered[0].name == "page-0001.png"
    assert rendered[0].read_bytes().startswith(b"\x89PNG")


def test_docx_media_extraction_is_confined_to_word_media(tmp_path):
    docx = tmp_path / "with-image.docx"
    with ZipFile(docx, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
        archive.writestr("word/media/image1.png", b"png-bytes")
        archive.writestr("word/../escape.png", b"should-not-extract")
    images = extract_docx_images(docx, tmp_path / "media")
    assert [item.name for item in images] == ["image1.png"]
    assert (tmp_path / "media" / "image1.png").read_bytes() == b"png-bytes"


def test_rtf_doc_extension_is_supported_by_type_detection_and_local_fallback(tmp_path, monkeypatch):
    from app.corpus.parsers import parse_source
    doc = tmp_path / "legacy.doc"
    doc.write_bytes(b"{\\rtf1\\ansi AI \\u25968?\\par RAG \\u25216?}")
    assert detect_file_type(doc.name, "application/msword", doc.read_bytes()) == "doc"
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "mineru_enabled", False)
    parsed = parse_source(_source(doc, "doc"))
    assert parsed.parser_schema == "rtf"
    assert "AI" in parsed.text


def test_rtf_named_docx_is_classified_as_compatible_word_document(tmp_path, monkeypatch):
    """Suffixes are hints; this common exporter output must not be rejected."""
    from app.corpus.parsers import parse_source
    docx = tmp_path / "exported-by-word.docx"
    docx.write_bytes(b"{\\rtf1\\ansi RAG \\par retrieval augmented generation}")
    assert detect_file_type(
        docx.name,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        docx.read_bytes(),
    ) == "doc"
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "mineru_enabled", False)
    parsed = parse_source(_source(docx, "doc"))
    assert parsed.parser_schema == "rtf"
    assert "retrieval augmented generation" in parsed.text


def test_visual_payload_requires_schema_and_clamps_confidence():
    result = validate_visual_payload(
        {
            "visual_type": "flowchart",
            "title": "RAG",
            "summary": "retrieve then generate",
            "elements": [{"text": "retrieve"}],
            "relations": [{"from": "retrieve", "to": "generate", "relation": "feeds"}],
            "uncertainties": [],
            "confidence": 2,
        },
        model_version="qwen-vl-plus",
    )
    assert result.confidence == 1
    with pytest.raises(VisualAnalysisError, match="visual_analysis_invalid"):
        validate_visual_payload({"summary": "missing fields"}, model_version="qwen-vl-plus")


def test_table_validation_rejects_inconsistent_rows_and_numeric_loss():
    analysis = validate_visual_payload({
        "visual_type": "table", "title": "指标", "summary": "", "elements": [{"text": "召回率"}],
        "relations": [], "uncertainties": [], "confidence": 0.8,
        "headers": ["指标", "值"], "rows": [["召回率"]], "merged_cells": [],
    }, model_version="qwen-vl-plus")
    assert validate_table_analysis(analysis, ocr_text="召回率 0.95") is False


def test_visual_feature_flag_keeps_media_block_without_provider(tmp_path, monkeypatch):
    image = tmp_path / "diagram.png"
    image.write_bytes(b"image")
    parsed = ParsedDocument(source=_source(image, "image"), text="", blocks=[])
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "document_visual_enabled", False)
    result = asyncio.run(enrich_document_visuals(parsed, image, document_id="visual-fixture", media_root=tmp_path / "assets"))
    assert result.blocks[0].metadata["visual_status"] == "skipped"
    assert result.metadata["visual_assets"] == 1


def test_qwen_vl_client_validates_openai_compatible_json(monkeypatch):
    from app.corpus.visual import QwenVLClient

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({
                "visual_type": "text_image", "title": "OCR", "summary": "RAG",
                "elements": [{"text": "RAG"}], "relations": [], "uncertainties": [], "confidence": 0.9,
            })}}]}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            return Response()

    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(settings, "document_visual_max_retries", 0)
    result = asyncio.run(QwenVLClient(client_factory=lambda **_kwargs: Client()).analyze(b"png", mode="ocr"))
    assert result.visual_type == "text_image"


def test_qwen_vl_client_sends_dashscope_workspace_header(monkeypatch):
    from app.corpus.visual import QwenVLClient
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(settings, "dashscope_workspace_id", "ws-paid")
    monkeypatch.setattr(settings, "document_visual_max_retries", 0)
    seen = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({
                "visual_type": "text_image", "title": "OCR", "summary": "ok",
                "elements": [{"text": "RAG"}], "relations": [], "uncertainties": [], "confidence": 0.9,
            })}}]}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, _url, headers=None, **_kwargs):
            seen.update(headers or {})
            return Response()

    result = asyncio.run(QwenVLClient(client_factory=lambda **_kwargs: Client()).analyze(b"png", mode="ocr"))
    assert result.visual_type == "text_image"
    assert seen["X-DashScope-WorkSpace"] == "ws-paid"


def test_qwen_vl_client_uses_workspace_regional_endpoint(monkeypatch):
    from app.corpus.visual import QwenVLClient

    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(settings, "dashscope_workspace_id", "ws-paid")
    monkeypatch.setattr(settings, "dashscope_region", "cn-beijing")
    monkeypatch.setattr(settings, "document_visual_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setattr(settings, "document_visual_max_retries", 0)
    seen = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({
                "visual_type": "text_image", "title": "OCR", "summary": "ok",
                "elements": [{"text": "RAG"}], "relations": [], "uncertainties": [], "confidence": 0.9,
            })}}]}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, **_kwargs):
            seen["url"] = url
            return Response()

    result = asyncio.run(QwenVLClient(client_factory=lambda **_kwargs: Client()).analyze(b"png", mode="ocr"))
    assert result.visual_type == "text_image"
    assert seen["url"] == "https://ws-paid.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"


def test_qwen_vl_client_falls_back_to_generic_endpoint_on_connect_error(monkeypatch):
    from app.corpus.visual import QwenVLClient
    import httpx

    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(settings, "dashscope_workspace_id", "ws-paid")
    monkeypatch.setattr(settings, "dashscope_region", "cn-beijing")
    monkeypatch.setattr(settings, "document_visual_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setattr(settings, "document_visual_max_retries", 0)
    seen = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({
                "visual_type": "text_image", "title": "OCR", "summary": "ok",
                "elements": [{"text": "RAG"}], "relations": [], "uncertainties": [], "confidence": 0.9,
            })}}]}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, **_kwargs):
            seen.append(url)
            if len(seen) == 1:
                raise httpx.ConnectError("workspace DNS unavailable")
            return Response()

    result = asyncio.run(QwenVLClient(client_factory=lambda **_kwargs: Client()).analyze(b"png", mode="ocr"))
    assert result.visual_type == "text_image"
    assert seen == [
        "https://ws-paid.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions",
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    ]


def test_visual_summary_is_indexed_as_text_with_traceability(tmp_path):
    image = tmp_path / "flowchart.png"
    image.write_bytes(b"image")
    source = _source(image, "image")
    parsed = ParsedDocument(
        source=source,
        text="RAG retrieve then generate",
        blocks=[ParsedBlock(
            "retrieve -> generate", "chart", media_path=str(image),
            metadata={"visual_type": "flowchart", "summary": "先检索再生成", "visual_status": "ready"},
            visual_type="flowchart", visual_status="ready", visual_confidence=0.92,
        )],
    )
    chunks = build_child_chunks(build_parent_units(parsed, CorpusConfig()), source, CorpusConfig())
    assert chunks[0].visual_type == "flowchart"
    assert "视觉摘要：先检索再生成" in chunks[0].embedding_text
    assert chunks[0].media_path.endswith("flowchart.png")
