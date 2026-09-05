"""Build a clean, source-grounded Golden Dataset v3 without model calls.

The old v2 dataset bound a whole QA parent as the reference answer.  Some
parents contain the next question, and one parent is truncated.  This script
keeps the original v2 immutable, extracts one atomic QA answer, normalizes OCR
radicals, and replaces only the truncated sample with another real parent from
the same technology family.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLDEN = ROOT / "corpus/benchmarks/golden-v2.yaml"
DEFAULT_CHUNKS = ROOT / "data/public-corpus/runs/ingest-d00b1b84c826b3bf/chunks.jsonl"
DEFAULT_OUTPUT = ROOT / "corpus/benchmarks/golden-v3.yaml"


# MinerU/OCR output occasionally contains Kangxi/CJK radicals instead of the
# normal Chinese character.  These are deterministic display/text repairs;
# they do not add or rewrite technical content.
RADICALS = str.maketrans({
    "⽤": "用", "⼀": "一", "⽐": "比", "⽅": "方", "⾥": "里",
    "⾏": "行", "⾃": "自", "⼤": "大", "⽂": "文", "⼊": "入",
    "⾼": "高", "⽣": "生", "⼝": "口", "⽽": "而", "⼦": "子",
    "⼼": "心", "⻓": "长", "⼯": "工", "⽀": "支", "⽬": "目",
    "⼏": "几", "⻅": "见", "⽹": "网", "⾯": "面", "⼩": "小",
    "⽇": "日", "⽴": "立", "⼿": "手", "⾛": "走", "⼰": "己",
    "⼲": "干", "⼈": "人", "⼒": "力", "⽆": "无", "⼚": "厂",
    "⿊": "黑", "⽗": "父", "⽌": "止", "⾮": "非", "⼆": "二",
    "⾝": "身", "⽰": "示", "⼴": "广", "⽩": "白", "⾄": "至",
    "⾔": "言", "⾦": "金", "⾊": "色", "⼜": "又", "⽔": "水",
    "⾳": "音", "⼣": "夕", "⻣": "骨", "⼑": "刀", "⼉": "儿",
    "⽕": "火", "⻛": "风", "⻬": "齐", "⻉": "贝", "⻔": "门",
    "⻆": "角", "⻢": "马", "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff",
})

QUESTION_STARTS = (
    "什么", "为何", "为什么", "如何", "怎样", "哪些", "哪几", "哪种",
    "你了解", "你使用", "你使⽤", "简述", "说说", "请描述", "请问",
    "是否", "能详细", "谈谈", "介绍", "区别", "有哪", "有哪些", "能不能",
    "怎么", "可以", "请解释", "请说明",
)


def clean_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).translate(RADICALS)
    # OCR often inserts spaces inside Latin identifiers: M yBatis, J ava,
    # AutoG PT, Docum ent.  Collapse only ASCII-to-ASCII spaces.
    text = re.sub(r"(?<=[A-Za-z0-9])\s+(?=[A-Za-z0-9])", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def load_parents(path: Path) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sources = [path]
    # The run-level file can omit the first child of a split parent while the
    # per-document files retain the complete structured chunk set.  Merge both
    # views and deduplicate by chunk_id so titles and full answers are kept.
    documents_dir = path.parent / "documents"
    if documents_dir.is_dir():
        sources.extend(sorted(documents_dir.rglob("chunks.jsonl")))
    seen_chunks: set[str] = set()
    for source in sources:
        for line in source.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("corpus_version") != "full-authorized-v1":
                    continue
                chunk_id = str(row.get("chunk_id") or "")
                if chunk_id and chunk_id in seen_chunks:
                    continue
                if chunk_id:
                    seen_chunks.add(chunk_id)
                grouped[str(row["parent_id"])].append(row)
    parents: dict[str, dict[str, Any]] = {}
    for parent_id, rows in grouped.items():
        rows.sort(key=lambda row: int(row.get("child_index", row.get("chunk_index", 0))))
        first = rows[0]
        embedding_text = clean_text(first.get("embedding_text", ""))
        # ``clean_text`` normalizes some full-width punctuation in the OCR
        # output, so accept both Chinese and ASCII separators here.
        title_match = re.search(r"标题[:：]([^\n]+)", embedding_text)
        parents[parent_id] = {
            "parent_id": parent_id,
            "text": "\n".join(clean_text(row.get("text") or row.get("evidence_text")) for row in rows).strip(),
            "document_id": first.get("document_id", ""),
            "technology": clean_text(first.get("technology", "")),
            "role_tags": first.get("role_tags") or ["general"],
            "source_name": clean_text(first.get("source_name", "")),
            "source_url": first.get("source_url", ""),
            "page_start": first.get("page_start"),
            "page_end": first.get("page_end"),
            "parent_type": first.get("parent_type") or first.get("knowledge_type") or "paragraph",
            "title": title_match.group(1).strip() if title_match else "",
            "license_status": first.get("license_status"),
            "corpus_version": first.get("corpus_version"),
        }
    return parents


def role(tags: Any) -> str:
    values = tags if isinstance(tags, list) else str(tags).strip("|").split("|")
    return next((clean_text(item) for item in values if clean_text(item) not in {"", "general"}), "backend")


def is_next_question(line: str) -> bool:
    line = clean_text(line)
    if not line or len(line) > 180 or ("？" not in line and "?" not in line):
        return False
    if line.startswith(QUESTION_STARTS):
        return True
    # Technical headings such as “Spring Bean 一共有几种作用域？” may not
    # begin with an interrogative word but are still clear next QA headings.
    return bool(re.search(r"(是什么|有什么|有哪几种|有哪些|有几种|一共有|如何|区别|作用|原理).*[？?]", line)) and not line.startswith(("GET ", "SELECT ", "代码"))


def atomic_answer(parent_text: str, question: str) -> tuple[str, str]:
    lines = [clean_text(line) for line in parent_text.splitlines() if clean_text(line)]
    query_body = clean_text(question.split(": ", 1)[-1])
    start = next((idx for idx, line in enumerate(lines) if query_body[:36] in line or line[:36] in query_body), 0)
    selected = lines[start:]
    for offset, line in enumerate(selected[1:], 1):
        if is_next_question(line):
            selected = selected[:offset]
            break
    return lines[start], "\n".join(selected).strip()


def is_malformed_question(question: str) -> bool:
    """Reject extraction artifacts that are code fragments, not questions."""
    value = clean_text(question)
    if not value:
        return True
    # A source heading normally contains a question mark.  Code fragments such
    # as ``postProcessBeanFactory(beanFactory);`` must never become a query.
    if "?" not in value and "？" not in value:
        return bool(re.search(r"[();{}=]", value))
    return False


def source_meta(parent: dict[str, Any]) -> str:
    page = f"page {parent['page_start']}" if parent.get("page_start") not in (None, -1) else ""
    return "; ".join(item for item in (parent.get("source_name"), page) if item)


def build_query(query_id: str, old: dict[str, Any], parent: dict[str, Any], question: str, answer: str) -> dict[str, Any]:
    technology = clean_text(parent["technology"] or old.get("topic"))
    question = clean_text(question)
    answer = clean_text(answer)
    # Keep the original user-facing wording, but normalize OCR artifacts.
    display_query = f"{technology}: {question}"
    source = source_meta(parent) or "公共知识库"
    reference = f"根据 {source}：\n{answer}"
    point = question.rstrip("？?").strip()
    return {
        "query_id": query_id,
        "scenario_type": "stable_technical",
        "topic": technology,
        "query": display_query,
        "role": role(parent["role_tags"]),
        "difficulty": "medium",
        "expected_technologies": [technology],
        "relevance": {parent["parent_id"]: 2},
        "expected_knowledge_points": [technology, point],
        "reference_answer": reference,
        "reference_context_ids": [parent["parent_id"]],
        "reference_contexts": [f"来源：{source}\n{answer}"],
        "expected_route": "public_kb",
        "expected_tools": ["public_milvus_search"],
        "expected_citations": [parent["parent_id"]],
        "safety_tags": [],
        "knowledge_scope": "public",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    old = yaml.safe_load(args.golden.read_text(encoding="utf-8"))
    parents = load_parents(args.chunks)
    used: set[str] = set()
    queries: list[dict[str, Any]] = []
    replacement_needed = False
    for item in old["queries"]:
        parent_id = str(item["reference_context_ids"][0])
        parent = parents[parent_id]
        # The legacy g-027 binding pointed at a similarly named Java-top-200
        # fragment whose first child was missing from the run-level file.  The
        # published corpus contains the authoritative, complete Spring parent;
        # bind the benchmark to that exact published parent instead of silently
        # evaluating an unsearchable historical id.
        if item["query_id"] == "g-027":
            spring_parent = next(
                (
                    candidate
                    for candidate in parents.values()
                    if candidate.get("document_id") == "mianshiya-spring"
                    and clean_text(candidate.get("title", "")).startswith("说说 Spring 启动过程")
                ),
                None,
            )
            if spring_parent is not None:
                parent = spring_parent
                parent_id = str(parent["parent_id"])
        question, answer = atomic_answer(parent["text"], item["query"])
        # One source row had its heading lost during ingestion and the old
        # benchmark used the first code line as the query.  Recover the real
        # title from MinerU's structured embedding text.
        if is_malformed_question(item.get("query", "")) and parent.get("title"):
            question, answer = atomic_answer(parent["text"], parent["title"])
        # g-005 is an actually truncated source parent; it must not become a
        # false reference answer.  Replace it with a complete real AI parent.
        if item["query_id"] == "g-005" and (len(answer) < 400 or not answer[-1] in "。！？.!?"):
            replacement_needed = True
            candidates = [p for p in parents.values() if p["technology"] == "AI 大模型" and p["parent_id"] not in used and len(p["text"]) >= 450]
            candidate = next(p for p in candidates if p["parent_id"] != parent_id)
            question, answer = atomic_answer(candidate["text"], candidate["text"].splitlines()[0])
            parent = candidate
        # Source paragraphs frequently end with a numbered bullet or code
        # token rather than punctuation.  Length is the hard guard here; the
        # known truncated sample was already replaced above.
        if len(answer) < 180:
            raise RuntimeError(f"atomic answer is suspicious: {item['query_id']} len={len(answer)}")
        used.add(parent["parent_id"])
        queries.append(build_query(item["query_id"], item, parent, question, answer))
    if len(queries) != 100 or len({q["query_id"] for q in queries}) != 100:
        raise RuntimeError("golden-v3 must contain exactly 100 unique samples")
    args.output.write_text(yaml.safe_dump({
        "benchmark_version": "golden-v3",
        "embedding_model": old.get("embedding_model", "text-embedding-v4"),
        "top_k": old.get("top_k", 5),
        "queries": queries,
    }, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "count": len(queries), "unique_parents": len(used), "replacement_g005": replacement_needed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
