from __future__ import annotations

import pytest

from app.corpus.chunking import DeepSeekBoundaryClassifier, build_child_chunks, build_parent_units
from app.corpus.config import CorpusConfig
from app.corpus.dedup import deduplicate_chunks
from app.corpus.models import ParsedBlock, ParsedDocument, SourceEntry
from app.corpus.parsers import CorpusParseError, clean_text, parse_source
from tests.corpus_fixtures import write_blank_pdf, write_docx, write_malformed_pdf, write_text_pdf


def source_for(path, content_type: str = "markdown") -> SourceEntry:
    return SourceEntry(
        document_id="fixture",
        path=str(path),
        source_name="fixture",
        technology="Redis",
        role_tags=["backend"],
        document_version="v1",
        language="zh-CN",
        content_type=content_type,
        license_status="approved",
        target_corpus_version="pilot-v1",
    )


def test_markdown_and_docx_parsers_keep_structure_and_location(tmp_path):
    markdown = tmp_path / "redis.md"
    markdown.write_text(
        "# Redis 持久化\n\n问题：RDB 和 AOF 有什么区别？\n答案：RDB 是快照，AOF 记录写命令。",
        encoding="utf-8",
    )
    docx = write_docx(tmp_path / "mysql.docx", ["MySQL 索引", "问题：什么是覆盖索引？", "答案：查询字段可由索引直接提供。"])

    parsed_md = parse_source(source_for(markdown))
    parsed_docx = parse_source(source_for(docx, "docx"))

    assert parsed_md.blocks[0].kind == "heading"
    assert parsed_md.blocks[0].section_path == ["Redis 持久化"]
    assert "RDB" in parsed_md.text
    assert parsed_docx.blocks
    assert "覆盖索引" in parsed_docx.text


def test_blank_pdf_is_reported_as_scanned_or_empty(tmp_path):
    blank_pdf = write_blank_pdf(tmp_path / "scan.pdf")

    with pytest.raises(CorpusParseError, match="scanned_or_empty_pdf"):
        parse_source(source_for(blank_pdf, "pdf"))


def test_malformed_pdf_is_reported_without_external_services(tmp_path):
    malformed_pdf = write_malformed_pdf(tmp_path / "malformed.pdf")

    with pytest.raises(CorpusParseError, match="unreadable_pdf"):
        parse_source(source_for(malformed_pdf, "pdf"))


def test_deterministic_text_pdf_preserves_page_location(tmp_path):
    pdf = write_text_pdf(tmp_path / "redis.pdf", "Redis RDB snapshot persistence answer")

    parsed = parse_source(source_for(pdf, "pdf"))

    assert parsed.page_count == 1
    assert "RDB snapshot" in parsed.text
    assert parsed.blocks[0].page_start == 1
    assert parsed.blocks[0].page_end == 1


def test_markdown_fixture_recognizes_heading_list_and_code(tmp_path):
    markdown = tmp_path / "structured.md"
    markdown.write_text(
        "# Redis\n\n- RDB snapshot\n- AOF command log\n\n```text\nSET key value\n```",
        encoding="utf-8",
    )

    parsed = parse_source(source_for(markdown))

    assert [block.kind for block in parsed.blocks] == ["heading", "list", "code"]
    assert all(block.section_path == ["Redis"] for block in parsed.blocks)


def test_clean_text_removes_control_noise_without_rewriting_content():
    value, warnings = clean_text("Redis\x00  RDB 机制\n\n\nAOF 写入")

    assert value == "Redis RDB 机制\n\nAOF 写入"
    assert "control_characters_removed" in warnings


def test_complete_qa_is_one_parent_and_oversized_parent_has_stable_children(tmp_path):
    markdown = tmp_path / "redis.md"
    long_answer = "RDB 使用快照保存数据，AOF 记录写命令并支持重写。" * 80
    markdown.write_text(f"# Redis\n\n问题：Redis 如何持久化？\n答案：{long_answer}", encoding="utf-8")
    parsed = parse_source(source_for(markdown))
    config = CorpusConfig(parent_max_chars=1800, child_chunk_size=700, child_chunk_overlap=100)

    parents = build_parent_units(parsed, config)
    children = build_child_chunks(parents, source_for(markdown), config)
    repeated = build_child_chunks(parents, source_for(markdown), config)

    qa_parents = [item for item in parents if item.parent_type == "qa"]
    assert len(qa_parents) == 1
    assert "问题：Redis 如何持久化" in qa_parents[0].text
    assert len(children) > 1
    assert {item.parent_id for item in children} == {qa_parents[0].parent_id}
    assert [item.chunk_id for item in children] == [item.chunk_id for item in repeated]
    assert [item.document_hash for item in children] == [item.document_hash for item in repeated]
    assert [item.parent_hash for item in children] == [item.parent_hash for item in repeated]
    assert len({item.document_hash for item in children}) == 1
    assert {item.parent_hash for item in children} == {qa_parents[0].content_hash}
    assert all(item.embedding_text != item.evidence_text for item in children)
    assert all(item.start_index >= 0 for item in children)


def test_unlabelled_pdf_style_question_and_answer_are_grouped_across_page_blocks(tmp_path):
    markdown = tmp_path / "redis.md"
    markdown.write_text(
        "Redis 持久化有哪些方案？\nRDB 保存时间点快照，AOF 记录写命令。\n\n"
        "AOF 为什么需要重写？\n重写可以压缩历史命令，并以当前数据状态生成新文件。",
        encoding="utf-8",
    )

    parents = build_parent_units(parse_source(source_for(markdown)), CorpusConfig())

    assert [parent.parent_type for parent in parents] == ["qa", "qa"]
    assert "RDB 保存时间点快照" in parents[0].text
    assert "重写可以压缩" in parents[1].text


def test_numbered_interview_questions_are_kept_but_numbered_promotions_are_not_questions(tmp_path):
    markdown = tmp_path / "mysql.md"
    markdown.write_text(
        "1. MySQL 的 MVCC 是如何实现的\n通过 ReadView 和 undo log 提供一致性读。\n\n"
        "2. 编程导航学习网站：学编程、做项目、拿 Offer！",
        encoding="utf-8",
    )

    parents = build_parent_units(parse_source(source_for(markdown)), CorpusConfig())

    assert parents[0].parent_type == "qa"
    assert "ReadView" in parents[0].text
    assert parents[1].parent_type != "question"


def test_q_prefixed_code_and_metrics_are_not_interview_questions(tmp_path):
    markdown = tmp_path / "java.md"
    markdown.write_text(
        "Java 虚拟线程适合 I/O 密集型服务。\nQPS 提升取决于等待时间。\n\n"
        "Queue<Integer> queue = new ArrayDeque<>();\nqueue.offer(1);",
        encoding="utf-8",
    )

    parents = build_parent_units(parse_source(source_for(markdown)), CorpusConfig())

    assert all(parent.parent_type != "question" for parent in parents)


def test_pdf_page_leading_continuation_is_merged_into_previous_question(tmp_path):
    source = source_for(tmp_path / "unused.pdf", "pdf")
    parsed = ParsedDocument(
        source=source,
        text="Java 中 CMS 和 G1 如何保持并发正确性？\n它们使用写屏障维护标记关系。",
        blocks=[
            ParsedBlock("Java 中 CMS 和 G1 如何保持并发正确性？", page_start=1, page_end=1),
            ParsedBlock("它们使用写屏障维护标记关系。", page_start=2, page_end=2),
        ],
        page_count=2,
    )

    parents = build_parent_units(parsed, CorpusConfig())

    assert len(parents) == 1
    assert parents[0].parent_type == "qa"
    assert parents[0].page_start == 1
    assert parents[0].page_end == 2
    assert "写屏障" in parents[0].text


def test_rhetorical_question_in_answer_stays_with_interview_question(tmp_path):
    markdown = tmp_path / "jvm.md"
    markdown.write_text(
        "Java 中 CMS 和 G1 如何维持并发正确性？\n"
        "用户线程和 GC 同时运行，怎么保证标记不漏不重？\n"
        "CMS 使用增量更新，G1 使用 SATB 和写屏障。",
        encoding="utf-8",
    )

    parents = build_parent_units(parse_source(source_for(markdown)), CorpusConfig())

    assert len(parents) == 1
    assert parents[0].parent_type == "qa"
    assert "SATB" in parents[0].text


def test_exact_and_near_duplicate_chunks_are_reported(tmp_path):
    markdown = tmp_path / "redis.md"
    markdown.write_text("# Redis\n\n问题：什么是 RDB？\n答案：RDB 是 Redis 的快照持久化机制。", encoding="utf-8")
    source = source_for(markdown)
    parsed = parse_source(source)
    children = build_child_chunks(build_parent_units(parsed, CorpusConfig()), source, CorpusConfig())

    result = deduplicate_chunks([*children, children[0]])

    assert len(result.kept) == len(children)
    assert result.duplicates


def test_boundary_classifier_reads_valid_content_hash_cache(tmp_path):
    text = "普通技术段落"
    import hashlib
    import json

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    (cache_dir / f"{digest}.json").write_text(
        json.dumps({"units": [{"start": 0, "end": len(text), "type": "section", "title": "技术"}]}),
        encoding="utf-8",
    )

    assert DeepSeekBoundaryClassifier(cache_dir).classify(text)[0]["type"] == "section"


def test_invalid_boundary_classifier_falls_back_to_deterministic_rules(tmp_path):
    class InvalidClassifier:
        def classify(self, text):
            raise ValueError("invalid structured output")

    markdown = tmp_path / "weak.md"
    markdown.write_text("这是一个没有明显标题的 Redis 技术段落，说明缓存数据和过期策略。", encoding="utf-8")
    parsed = parse_source(source_for(markdown))
    config = CorpusConfig(boundary_classifier_enabled=True)

    expected = build_parent_units(parsed, CorpusConfig(boundary_classifier_enabled=False))
    actual = build_parent_units(parsed, config, InvalidClassifier())

    assert [(item.text, item.parent_type) for item in actual] == [(item.text, item.parent_type) for item in expected]


def test_parent_build_records_non_searchable_heading_as_rejected_block(tmp_path):
    markdown = tmp_path / "heading.md"
    markdown.write_text("# Redis\n\n问题：什么是 RDB？\n答案：RDB 是快照。", encoding="utf-8")

    parsed = parse_source(source_for(markdown))
    parents = build_parent_units(parsed, CorpusConfig())

    assert len(parents) == 1
    assert parsed.rejected_blocks == [{"block_index": 0, "reason": "heading_context_only", "start_index": 0}]


def test_boundary_classifier_must_cover_all_text_without_gaps():
    with pytest.raises(ValueError, match="invalid offsets|uncovered text"):
        DeepSeekBoundaryClassifier._validate(
            {"units": [{"start": 1, "end": 4, "type": "paragraph", "title": ""}]},
            4,
        )


def test_classifier_parent_keeps_original_location_metadata(tmp_path):
    markdown = tmp_path / "structured.md"
    markdown.write_text("# Redis\n\n普通 Redis 技术说明，包含持久化和过期策略。", encoding="utf-8")
    parsed = parse_source(source_for(markdown))

    class FullTextClassifier:
        def classify(self, text):
            return [{"start": 0, "end": len(text), "type": "section", "title": "Redis"}]

    parents = build_parent_units(
        parsed,
        CorpusConfig(boundary_classifier_enabled=True, structure_confidence_threshold=0.99),
        FullTextClassifier(),
    )

    assert parents[0].section_path == ["Redis"]
    assert parents[0].start_index == 0
