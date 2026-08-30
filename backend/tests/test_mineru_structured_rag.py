import asyncio
import io
import json
import zipfile
from pathlib import Path

from app.corpus.chunking import build_child_chunks, build_parent_units
from app.corpus.config import CorpusConfig
from app.corpus.models import SourceEntry
from app.corpus.parsers import parse_source, parsed_document_from_mineru
from app.services.knowledge_service import process_document
from app.services.mineru_service import MinerUParser, MinerUStructuredBlock, MinerUStructuredResult
from tests.corpus_fixtures import write_text_pdf


def _archive(name: str, payload) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr(f"result/{name}", json.dumps(payload, ensure_ascii=False))
        bundle.writestr("result/full.md", "# fallback\n\nshould not be used")
    return output.getvalue()


def _source() -> SourceEntry:
    return SourceEntry(
        document_id="mineru-fixture",
        path="fixture.pdf",
        source_name="MinerU fixture",
        technology="RAG",
        role_tags=["ai"],
        document_version="v1",
        content_type="pdf",
        license_status="approved",
        target_corpus_version="test-v1",
    )


def test_v2_archive_preserves_structural_nodes_and_locations():
    payload = [
        [
            {
                "type": "title",
                "content": {"title_content": [{"type": "text", "content": "Agentic RAG"}], "level": 1},
                "bbox": [10, 20, 300, 60],
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {"type": "text", "content": "路由器根据证据充分度选择检索源"},
                        {"type": "equation_inline", "content": "score=max(v,w)"},
                    ]
                },
                "bbox": [10, 70, 500, 130],
            },
            {
                "type": "table",
                "content": {"table_body": "<table><tr><td>Milvus</td></tr></table>"},
                "bbox": [10, 140, 500, 300],
            },
            {
                "type": "image",
                "content": {
                    "image_source": {"path": "images/router.jpg"},
                    "content": "",
                    "image_caption": [{"type": "text", "content": "检索路由流程图"}],
                },
                "bbox": [10, 310, 500, 600],
            },
        ],
        [
            {
                "type": "equation",
                "content": {"equation_content": [{"type": "text", "content": "R = alpha * V + beta * W"}]},
                "bbox": [20, 30, 480, 90],
            }
        ],
    ]

    result = MinerUParser.parse_archive(_archive("paper_content_list_v2.json", payload))

    assert [block.kind for block in result.blocks] == ["heading", "paragraph", "table", "image", "formula"]
    assert result.blocks[0].heading_level == 1
    assert result.blocks[1].section_path == ["Agentic RAG"]
    assert result.blocks[1].page_start == 1
    assert result.blocks[-1].page_start == 2
    assert result.blocks[2].bbox == [10.0, 140.0, 500.0, 300.0]
    assert result.blocks[3].media_path == "images/router.jpg"
    assert "检索路由流程图" in result.blocks[3].text
    assert "score=max(v,w)" in result.blocks[1].text
    assert result.page_count == 2
    assert result.schema_version == "v2"


def test_mineru_artifacts_persist_archive_normalized_json_and_media(tmp_path, monkeypatch):
    payload = [[{
        "type": "image",
        "content": {"image_source": {"path": "images/router.jpg"}, "image_caption": [{"content": "路由图"}]},
        "bbox": [1, 2, 3, 4],
    }]]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr("result/paper_content_list_v2.json", json.dumps(payload, ensure_ascii=False))
        bundle.writestr("result/images/router.jpg", b"image-bytes")
    archive = output.getvalue()
    parsed = MinerUParser.parse_archive(archive)
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "mineru_artifact_dir", str(tmp_path / "artifacts"))

    persisted = MinerUParser.persist_artifacts(archive, parsed, document_id="doc-artifact")

    media_path = persisted.blocks[0].media_path
    assert media_path.endswith("images\\router.jpg") or media_path.endswith("images/router.jpg")
    assert Path(media_path).read_bytes() == b"image-bytes"
    root = Path(media_path).parents[2]
    assert (root / "result.zip").exists()
    normalized = json.loads((root / "structured.json").read_text(encoding="utf-8"))
    assert normalized["blocks"][0]["metadata"]["mineru_media_path"] == "images/router.jpg"


def test_legacy_archive_preserves_table_formula_and_heading_hierarchy():
    payload = [
        {"type": "text", "text": "RAG", "text_level": 1, "bbox": [1, 2, 3, 4], "page_idx": 0},
        {"type": "text", "text": "Retrieval", "text_level": 2, "bbox": [1, 5, 3, 8], "page_idx": 0},
        {
            "type": "table",
            "table_caption": ["召回对比"],
            "table_body": "<table><tr><td>向量</td></tr></table>",
            "bbox": [1, 9, 300, 200],
            "page_idx": 0,
        },
        {"type": "equation", "text": "$$sim(q,d)$$", "text_format": "latex", "bbox": [1, 20, 30, 40], "page_idx": 1},
        {"type": "footer", "text": "copyright", "page_idx": 1},
    ]

    result = MinerUParser.parse_archive(_archive("paper_content_list.json", payload))

    assert [block.kind for block in result.blocks] == ["heading", "heading", "table", "formula"]
    assert result.blocks[2].section_path == ["RAG", "Retrieval"]
    assert "<table>" in result.blocks[2].text
    assert result.blocks[3].metadata["text_format"] == "latex"
    assert result.schema_version == "legacy"


def test_v2_flat_or_wrapped_pages_keep_explicit_page_numbers():
    payload = {
        "pages": [
            {"type": "paragraph", "content": {"paragraph_content": [{"content": "page two"}]}, "page_idx": 1, "bbox": [1, 2, 3, 4]},
            {"type": "paragraph", "content": {"paragraph_content": [{"content": "page four"}]}, "page_number": 4, "bbox": [5, 6, 7, 8]},
        ]
    }

    result = MinerUParser.parse_archive(_archive("paper_content_list_v2.json", payload))

    assert [block.page_start for block in result.blocks] == [2, 4]
    assert result.page_count == 4


def test_legacy_page_count_includes_noise_only_last_page():
    payload = [
        {"type": "text", "text": "content", "page_idx": 0},
        {"type": "page_number", "text": "3", "page_idx": 2},
    ]

    result = MinerUParser.parse_archive(_archive("paper_content_list.json", payload))

    assert result.page_count == 3


def test_structural_nodes_remain_distinct_parent_child_types():
    payload = [[
        {"type": "title", "content": {"title_content": [{"content": "RAG"}], "level": 1}, "bbox": [0, 0, 100, 20]},
        {"type": "table", "content": {"table_body": "<table><tr><td>dense</td></tr></table>"}, "bbox": [0, 30, 100, 100]},
        {"type": "code", "content": {"code_content": [{"content": "retriever.invoke(query)\nrerank(results)"}]}, "bbox": [0, 110, 100, 180]},
        {"type": "equation", "content": {"equation_content": [{"content": "score = dense + web"}]}, "bbox": [0, 190, 100, 240]},
    ]]
    result = MinerUParser.parse_archive(_archive("paper_content_list_v2.json", payload))
    source = _source()
    parsed = parsed_document_from_mineru(result, source)

    parents = build_parent_units(parsed, CorpusConfig())
    chunks = build_child_chunks(parents, source, CorpusConfig())

    assert [parent.parent_type for parent in parents] == ["table", "code", "formula"]
    assert {chunk.knowledge_type for chunk in chunks} == {"table", "code", "formula"}
    assert all(chunk.section_path == ["RAG"] for chunk in chunks)
    assert all(chunk.bbox for chunk in chunks)
    assert all(chunk.mineru_node_path for chunk in chunks)


def test_public_parse_source_uses_mineru_structured_result(tmp_path, monkeypatch):
    path = tmp_path / "public.pdf"
    path.write_bytes(b"fixture")
    source = _source().model_copy(update={"path": str(path)})
    result = MinerUStructuredResult(
        text="RAG\n\n<table><tr><td>Milvus</td></tr></table>",
        markdown="",
        blocks=[
            MinerUStructuredBlock("RAG", "heading", 1, 1, ["RAG"], 0, 1, [0, 0, 10, 10], "", "0.0"),
            MinerUStructuredBlock(
                "<table><tr><td>Milvus</td></tr></table>",
                "table",
                1,
                1,
                ["RAG"],
                5,
                None,
                [0, 20, 100, 100],
                "",
                "0.1",
                {"mineru_type": "table"},
            ),
        ],
        page_count=1,
        schema_version="v2",
    )

    async def fake_parse(*_args, **_kwargs):
        return result

    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "mineru_enabled", True)
    monkeypatch.setattr(settings, "mineru_api_token", "configured")
    monkeypatch.setattr(MinerUParser, "parse_structured", fake_parse)

    parsed = parse_source(source)

    assert parsed.parser_name == "mineru"
    assert parsed.parser_schema == "v2"
    assert parsed.blocks[1].kind == "table"
    assert parsed.blocks[1].bbox == [0, 20, 100, 100]


def test_personal_document_pipeline_upserts_structured_deduplicated_chunks(tmp_path, monkeypatch):
    path = tmp_path / "personal.pdf"
    path.write_bytes(b"fixture")
    result = MinerUStructuredResult(
        text="RAG\n\n<table><tr><td>dense retrieval</td></tr></table>",
        markdown="",
        blocks=[
            MinerUStructuredBlock("RAG", "heading", 1, 1, ["RAG"], 0, 1, [0, 0, 100, 20], "", "0.0"),
            MinerUStructuredBlock(
                "<table><tr><td>dense retrieval</td></tr></table>",
                "table",
                1,
                1,
                ["RAG"],
                5,
                None,
                [0, 30, 100, 100],
                "images/table.jpg",
                "0.1",
                {"mineru_type": "table"},
            ),
        ],
        page_count=1,
        schema_version="v2",
    )
    captured = {}

    async def fake_get(*_args):
        return {"storage_path": str(path), "original_name": "personal.pdf", "mime_type": "application/pdf"}

    async def fake_parse(*_args, **_kwargs):
        return result

    async def fake_ready(_connection, _user_id, _document_id, count, model):
        captured["ready"] = (count, model)

    async def fake_failed(*_args):
        raise AssertionError("structured processing must not fail")

    class Store:
        def upsert_document(self, document_id, source_name, chunks):
            captured["upsert"] = (document_id, source_name, chunks)

    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "mineru_enabled", True)
    monkeypatch.setattr("app.services.knowledge_service.knowledge_repository.get_document", fake_get)
    monkeypatch.setattr("app.services.knowledge_service.knowledge_repository.set_ready", fake_ready)
    monkeypatch.setattr("app.services.knowledge_service.knowledge_repository.set_failed", fake_failed)
    monkeypatch.setattr("app.services.knowledge_service.MinerUParser.parse_structured", fake_parse)
    monkeypatch.setattr("app.services.knowledge_service.get_vector_store", lambda _user_id: Store())

    asyncio.run(process_document(object(), 7, "doc-personal"))

    document_id, source_name, chunks = captured["upsert"]
    assert document_id == "doc-personal"
    assert source_name == "personal.pdf"
    assert len(chunks) == 1
    assert chunks[0]["knowledge_type"] == "table"
    assert chunks[0]["section_path"] == ["RAG"]
    assert chunks[0]["bbox"] == [0, 30, 100, 100]
    assert chunks[0]["mineru_node_path"] == "0.1"
    assert captured["ready"][0] == 1


def test_sync_parse_source_is_safe_inside_running_event_loop(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# RAG\n\nretrieval context", encoding="utf-8")
    source = _source().model_copy(update={"path": str(path), "content_type": "markdown"})

    async def call_sync_parser():
        return parse_source(source)

    parsed = asyncio.run(call_sync_parser())

    assert parsed.blocks[0].kind == "heading"
    assert parsed.blocks[1].section_path == ["RAG"]


def test_personal_pdf_uses_local_fallback_when_mineru_token_is_missing(tmp_path, monkeypatch):
    path = write_text_pdf(tmp_path / "fallback.pdf", "RAG retrieval augmented generation interview knowledge")
    captured = {}

    async def fake_get(*_args):
        return {"storage_path": str(path), "original_name": "fallback.pdf", "mime_type": "application/pdf"}

    async def fake_ready(_connection, _user_id, _document_id, count, _model):
        captured["ready"] = count

    async def forbidden_mineru(*_args, **_kwargs):
        raise AssertionError("MinerU must not be called without a token")

    class Store:
        def upsert_document(self, _document_id, _source_name, chunks):
            captured["chunks"] = chunks

    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "mineru_enabled", True)
    monkeypatch.setattr(settings, "mineru_api_token", None)
    monkeypatch.setattr("app.services.knowledge_service.knowledge_repository.get_document", fake_get)
    monkeypatch.setattr("app.services.knowledge_service.knowledge_repository.set_ready", fake_ready)
    monkeypatch.setattr("app.services.knowledge_service.MinerUParser.parse_structured", forbidden_mineru)
    monkeypatch.setattr("app.services.knowledge_service.get_vector_store", lambda _user_id: Store())

    asyncio.run(process_document(object(), 7, "doc-fallback"))

    assert captured["ready"] > 0
    assert captured["chunks"][0]["knowledge_type"] in {"paragraph", "section"}
