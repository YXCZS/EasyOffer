from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Protocol

from app.corpus.config import CorpusConfig
from app.corpus.models import ChildChunk, ParentUnit, ParsedBlock, ParsedDocument, SourceEntry


QUESTION_RE = re.compile(
    r"^(?:(?:Q(?:uestion)?\s*\d+\s*[.:：、)]?)|(?:Q(?:uestion)?\s*[:：])|"
    r"(?:问题\s*\d*|第[一二三四五六七八九十百\d]+[题问])\s*[:：]?)",
    re.IGNORECASE,
)
NUMBERED_RE = re.compile(r"^\d+[.、)]\s*")
QUESTION_CUES = (
    "什么", "如何", "怎么", "为什么", "为何", "区别", "原理", "流程", "作用",
    "场景", "哪些", "是否", "能否", "何时", "怎样", "请说明", "请解释", "谈谈",
)
ANSWER_RE = re.compile(r"^(?:A(?:nswer)?\s*\d*|答案|解析|解答|总结)\s*[:：]", re.IGNORECASE)
STRUCTURAL_KINDS = {"table", "code", "formula", "image", "chart", "list", "reference"}


def _is_question_line(line: str) -> bool:
    """Recognize interview questions without treating code placeholders as questions."""
    value = line.strip()
    if not value:
        return False
    if QUESTION_RE.match(value):
        return True
    if NUMBERED_RE.match(value) and any(cue in value for cue in QUESTION_CUES):
        return True
    if not value.endswith(("?", "？")):
        return False
    # PDF text extraction frequently leaves SQL placeholders, generic types,
    # and ternary expressions ending in '?'. Require interview-language cues
    # or enough Chinese text before considering a trailing question mark real.
    if any(cue in value for cue in QUESTION_CUES):
        return True
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", value))
    return chinese_chars >= 6 and not re.search(r"[=<>()[\]{};]", value)


class BoundaryClassifier(Protocol):
    def classify(self, text: str) -> list[dict[str, Any]]: ...


class DeepSeekBoundaryClassifier:
    """Optional boundary-only classifier. It never returns rewritten content."""

    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)

    def classify(self, text: str) -> list[dict[str, Any]]:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        cache_path = self.cache_dir / f"{digest}.json"
        if cache_path.exists():
            return self._validate(json.loads(cache_path.read_text(encoding="utf-8")), len(text))
        from app.llm.deepseek import _chat_model, _message_json
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你只识别技术面试资料的语义边界，不得改写正文。只返回 JSON："
                    "{units:[{start:int,end:int,type:'qa|section|paragraph',title:string}]}。"
                    "start/end 必须是原文字符偏移，区间不可重叠且原文切片必须保持不变。",
                ),
                ("user", "原文：\n{text}"),
            ]
        )
        message = (prompt | _chat_model(0, timeout=20, max_retries=0)).invoke({"text": text})
        units = self._validate(_message_json(message), len(text))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"units": units}, ensure_ascii=False, indent=2), encoding="utf-8")
        return units

    @staticmethod
    def _validate(payload: Any, text_length: int) -> list[dict[str, Any]]:
        raw_units = payload.get("units") if isinstance(payload, dict) else None
        if not isinstance(raw_units, list):
            raise ValueError("boundary classifier returned invalid units")
        output: list[dict[str, Any]] = []
        previous_end = 0
        for item in raw_units:
            start = int(item.get("start", -1))
            end = int(item.get("end", -1))
            unit_type = str(item.get("type") or "paragraph")
            if start != previous_end or end <= start or end > text_length:
                raise ValueError("boundary classifier returned invalid offsets")
            if unit_type not in {"qa", "section", "paragraph"}:
                raise ValueError("boundary classifier returned invalid type")
            output.append({"start": start, "end": end, "type": unit_type, "title": str(item.get("title") or "")})
            previous_end = end
        if not output:
            raise ValueError("boundary classifier returned no units")
        if output[0]["start"] != 0 or output[-1]["end"] != text_length:
            raise ValueError("boundary classifier left uncovered text")
        return output


def _content_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _split_block(block: ParsedBlock) -> list[tuple[str, str, float]]:
    lines = [line.strip() for line in block.text.splitlines() if line.strip()]
    if not lines:
        return []
    groups: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        question_line = _is_question_line(line)
        # Keep a rhetorical follow-up immediately after a question in the same
        # Q&A unit. A real next question appears after answer content exists.
        if question_line and current and not (len(current) == 1 and _is_question_line(current[0])):
            groups.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        groups.append(current)
    output: list[tuple[str, str, float]] = []
    for group in groups:
        text = "\n".join(group)
        has_question = (
            _is_question_line(group[0])
        )
        has_answer = any(ANSWER_RE.match(line) for line in group[1:]) or (has_question and len(group) > 1)
        if has_question and has_answer:
            output.append((text, "qa", 0.95))
        elif has_question:
            output.append((text, "question", 0.60))
        else:
            output.append((text, "section" if block.section_path else "paragraph", 0.55 if block.section_path else 0.35))
    return output


def build_parent_units(
    parsed: ParsedDocument,
    config: CorpusConfig,
    classifier: BoundaryClassifier | None = None,
) -> list[ParentUnit]:
    parsed.rejected_blocks.clear()
    document_hash = _content_hash(parsed.text)
    candidates: list[tuple[str, str, float, ParsedBlock]] = []
    for block_index, block in enumerate(parsed.blocks):
        if block.kind == "heading":
            parsed.rejected_blocks.append({"block_index": block_index, "reason": "heading_context_only", "start_index": block.start_index})
            continue
        if block.kind in STRUCTURAL_KINDS:
            candidates.append((block.text, block.kind, 0.99, block))
            continue
        split_candidates = _split_block(block)
        if not split_candidates:
            parsed.rejected_blocks.append({"block_index": block_index, "reason": "empty_or_unrecognized", "start_index": block.start_index})
            continue
        for split_index, (text, parent_type, confidence) in enumerate(split_candidates):
            cross_page_continuation = (
                candidates
                and split_index == 0
                and parent_type in {"paragraph", "section"}
                and block.page_start is not None
                and candidates[-1][3].page_end is not None
                and block.page_start == candidates[-1][3].page_end + 1
            )
            if (
                candidates
                and parent_type in {"paragraph", "section"}
                and (candidates[-1][1] == "question" or cross_page_continuation)
                and not (QUESTION_RE.match(text) or text.endswith(("?", "？")))
            ):
                previous_text, previous_type, previous_confidence, previous_block = candidates[-1]
                combined = f"{previous_text}\n{text}".strip()
                candidates[-1] = (
                    combined,
                    "qa" if previous_type in {"question", "qa"} and len(combined) >= 40 else previous_type,
                    max(previous_confidence, 0.82),
                    ParsedBlock(
                        text=combined,
                        kind=previous_block.kind,
                        page_start=previous_block.page_start,
                        page_end=block.page_end,
                        section_path=previous_block.section_path,
                        start_index=previous_block.start_index,
                        heading_level=previous_block.heading_level,
                        bbox=previous_block.bbox,
                        media_path=previous_block.media_path,
                        mineru_node_path=previous_block.mineru_node_path,
                        metadata=previous_block.metadata,
                        visual_type=previous_block.visual_type,
                        visual_status=previous_block.visual_status,
                        visual_confidence=previous_block.visual_confidence,
                    ),
                )
            else:
                candidates.append((text, parent_type, confidence, block))
    if not candidates and parsed.text:
        candidates.append((parsed.text, "paragraph", 0.25, ParsedBlock(parsed.text)))

    has_structural_blocks = any(block.kind in STRUCTURAL_KINDS for block in parsed.blocks)
    if config.boundary_classifier_enabled and classifier is not None and candidates and not has_structural_blocks:
        if min(item[2] for item in candidates) < config.structure_confidence_threshold:
            try:
                classified = classifier.classify(parsed.text)
                candidates = []
                for item in classified:
                    text = parsed.text[item["start"] : item["end"]]
                    overlaps = [
                        block for block in parsed.blocks
                        if block.kind != "heading"
                        and block.start_index < item["end"]
                        and block.start_index + len(block.text) > item["start"]
                    ]
                    template = overlaps[0] if overlaps else ParsedBlock(text=text, start_index=item["start"])
                    candidates.append(
                        (
                            text,
                            item["type"],
                            0.75,
                            ParsedBlock(
                                text=text,
                                kind=template.kind,
                                page_start=template.page_start,
                                page_end=template.page_end,
                                section_path=template.section_path,
                                start_index=item["start"],
                                heading_level=template.heading_level,
                                bbox=template.bbox,
                                media_path=template.media_path,
                                mineru_node_path=template.mineru_node_path,
                                metadata=template.metadata,
                                visual_type=template.visual_type,
                                visual_status=template.visual_status,
                                visual_confidence=template.visual_confidence,
                            ),
                        )
                    )
            except Exception:
                pass

    parents: list[ParentUnit] = []
    for index, (text, parent_type, confidence, block) in enumerate(candidates):
        content_hash = _content_hash(text)
        parent_id = hashlib.sha256(
            f"{parsed.source.document_id}:{parsed.source.document_version}:{index}:{content_hash}".encode("utf-8")
        ).hexdigest()
        first_line = text.splitlines()[0].strip()
        title = re.sub(r"^(?:问题|Q\d*)\s*[:：]?", "", first_line, flags=re.IGNORECASE)[:200]
        parents.append(
            ParentUnit(
                parent_id=parent_id,
                document_id=parsed.source.document_id,
                document_version=parsed.source.document_version,
                parent_index=index,
                parent_type=parent_type,
                title=title,
                text=text,
                section_path=block.section_path,
                page_start=block.page_start,
                page_end=block.page_end,
                start_index=block.start_index,
                document_hash=document_hash,
                content_hash=content_hash,
                structure_confidence=confidence,
                heading_level=block.heading_level,
                bbox=block.bbox,
                media_path=block.media_path,
                mineru_node_path=block.mineru_node_path,
                structure_metadata=block.metadata,
                visual_type=block.visual_type or str(block.metadata.get("visual_type") or ""),
                visual_status=block.visual_status or str(block.metadata.get("visual_status") or ""),
                visual_confidence=block.visual_confidence if block.visual_confidence is not None else block.metadata.get("confidence"),
            )
        )
    return parents


def _line_aware_segments(text: str, chunk_size: int, overlap: int) -> list[tuple[str, int]]:
    lines = text.splitlines(keepends=True)
    if not lines:
        return [(text, 0)]
    output: list[tuple[str, int]] = []
    start_line = 0
    offsets: list[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line)
    while start_line < len(lines):
        size = 0
        end_line = start_line
        while end_line < len(lines) and (size + len(lines[end_line]) <= chunk_size or end_line == start_line):
            size += len(lines[end_line])
            end_line += 1
        segment = "".join(lines[start_line:end_line]).strip()
        if segment:
            output.append((segment, offsets[start_line]))
        if end_line >= len(lines):
            break
        overlap_chars = 0
        next_start = end_line
        while next_start > start_line and overlap_chars < overlap:
            next_start -= 1
            overlap_chars += len(lines[next_start])
        start_line = max(start_line + 1, next_start)
    return output


def _table_segments(text: str, chunk_size: int) -> list[tuple[str, int]]:
    rows = re.findall(r"<tr\b[^>]*>.*?</tr>", text, flags=re.IGNORECASE | re.DOTALL)
    if not rows:
        return _line_aware_segments(text, chunk_size, 0)
    prefix_match = re.search(r"<table\b[^>]*>", text, flags=re.IGNORECASE)
    prefix = prefix_match.group(0) if prefix_match else "<table>"
    header = rows[0] if re.search(r"<th\b", rows[0], flags=re.IGNORECASE) else ""
    groups: list[list[str]] = []
    current: list[str] = []
    for row in rows:
        candidate = prefix + header + "".join(current) + row + "</table>"
        if current and len(candidate) > chunk_size:
            groups.append(current)
            current = [row]
        else:
            current.append(row)
    if current:
        groups.append(current)
    output: list[tuple[str, int]] = []
    cursor = 0
    for group in groups:
        body = "".join(group)
        segment = prefix + (header if header and group[0] != header else "") + body + "</table>"
        start = text.find(group[0], cursor)
        output.append((segment, max(0, start)))
        cursor = max(cursor, start + len(body))
    return output


def _segments_for_parent(parent: ParentUnit, config: CorpusConfig, splitter: Any) -> list[tuple[str, int]]:
    if parent.parent_type in {"formula", "image", "chart"}:
        return [(parent.text, 0)]
    if len(parent.text) <= config.child_chunk_size:
        return [(parent.text, 0)]
    if parent.parent_type == "table":
        return _table_segments(parent.text, config.child_chunk_size)
    if parent.parent_type in {"code", "list", "reference"}:
        return _line_aware_segments(parent.text, config.child_chunk_size, config.child_chunk_overlap)
    docs = splitter.create_documents([parent.text], metadatas=[{"parent_id": parent.parent_id}])
    return [
        (doc.page_content.strip(), int(doc.metadata.get("start_index", 0)))
        for doc in docs
        if doc.page_content.strip()
    ]


def build_child_chunks(
    parents: list[ParentUnit],
    source: SourceEntry,
    config: CorpusConfig,
) -> list[ChildChunk]:
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.child_chunk_size,
        chunk_overlap=config.child_chunk_overlap,
        add_start_index=True,
        length_function=len,
        separators=["\n\n", "\n", "。", "！", "？", ";", "；", "，", ",", " ", ""],
    )
    output: list[ChildChunk] = []
    for parent in parents:
        segments = _segments_for_parent(parent, config, splitter)
        for child_index, (text, relative_start) in enumerate(segments):
            content_hash = _content_hash(text)
            chunk_id = hashlib.sha256(
                f"{source.document_id}:{source.document_version}:{parent.parent_index}:{child_index}:{content_hash}".encode("utf-8")
            ).hexdigest()
            section = " > ".join(parent.section_path)
            structure_label = f"Structure type: {parent.parent_type}"
            embedding_text = "\n".join(
                part
                for part in (
                    f"技术：{source.technology}",
                    f"标题：{parent.title}" if parent.title else "",
                    f"章节：{section}" if section else "",
                    structure_label,
                    f"正文：{text}",
                )
                if part
            )
            visual_summary = str(parent.structure_metadata.get("summary") or "").strip()
            if visual_summary:
                embedding_text += f"\n视觉摘要：{visual_summary}"
            output.append(
                ChildChunk(
                    chunk_id=chunk_id,
                    document_id=source.document_id,
                    document_version=source.document_version,
                    corpus_version=source.target_corpus_version,
                    parent_id=parent.parent_id,
                    parent_type=parent.parent_type,
                    child_index=child_index,
                    start_index=parent.start_index + relative_start,
                    evidence_text=text,
                    embedding_text=embedding_text,
                    document_hash=parent.document_hash,
                    parent_hash=parent.content_hash,
                    content_hash=content_hash,
                    technology=source.technology,
                    role_tags=source.role_tags,
                    knowledge_type=parent.parent_type,
                    section_path=parent.section_path,
                    source_name=source.source_name,
                    source_url=source.source_url or "",
                    reference_urls=[item.url for item in source.references],
                    page_start=parent.page_start,
                    page_end=parent.page_end,
                    language=source.language,
                    license_status=source.license_status,
                    authority_priority=source.authority_priority,
                    structure_confidence=parent.structure_confidence,
                    heading_level=parent.heading_level,
                    bbox=parent.bbox,
                    media_path=parent.media_path,
                    mineru_node_path=parent.mineru_node_path,
                    structure_metadata=parent.structure_metadata,
                    visual_type=parent.visual_type,
                    visual_status=parent.visual_status,
                    visual_confidence=parent.visual_confidence,
                )
            )
    if len(output) > config.max_chunks_per_document:
        raise ValueError("document chunk count exceeds configured limit")
    return output
