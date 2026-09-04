"""Bind evaluation datasets to the published full-authorized-v1 corpus.

The generated artifacts contain only public corpus evidence.  No model call is
made here: a reviewer can reproduce the exact mapping from the immutable
ingest JSONL and the selected corpus version.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHUNKS = ROOT / "data/public-corpus/runs/ingest-d00b1b84c826b3bf/chunks.jsonl"
DEFAULT_SOURCE = ROOT / "corpus/benchmarks/full-authorized-v1-source-grounded.yaml"
DEFAULT_GOLDEN = ROOT / "corpus/benchmarks/golden-v2.yaml"


def _load_rows(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [row for row in rows if row.get("corpus_version") == "full-authorized-v1" and row.get("status") == "unpublished"]
    if not rows:
        raise RuntimeError(f"no staged rows for full-authorized-v1 in {path}")
    return rows


def _parents(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["parent_id"])].append(row)
    result: dict[str, dict[str, Any]] = {}
    for parent_id, children in grouped.items():
        children.sort(key=lambda item: int(item.get("child_index", item.get("chunk_index", 0))))
        first = children[0]
        text = "\n".join(str(item.get("text") or item.get("evidence_text") or "").strip() for item in children).strip()
        result[parent_id] = {
            "parent_id": parent_id,
            "text": text,
            "document_id": first.get("document_id", ""),
            "technology": first.get("technology", ""),
            "role_tags": first.get("role_tags") or ["general"],
            "source_name": first.get("source_name", ""),
            "source_url": first.get("source_url", ""),
            "page_start": first.get("page_start"),
            "page_end": first.get("page_end"),
            "section_path": first.get("section_path") or [],
            "parent_type": first.get("parent_type") or first.get("knowledge_type") or "paragraph",
        }
    return result


def _role(tags: Any) -> str:
    values = tags if isinstance(tags, list) else [item for item in str(tags).strip("|").split("|") if item]
    return next((str(item) for item in values if item and item != "general"), "backend")


def _question(text: str, technology: str, parent_id: str) -> str:
    # Most public records are Q&A parents.  Keep the source wording so the
    # query is a faithful, deterministic test of the production retriever.
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    first = re.sub(r"^(问题|标题|正文)\s*[:：]\s*", "", first).strip()
    first = first[:180]
    return f"{technology}: {first}" if first else f"{technology} parent {parent_id[:12]}"


def _reference(parent: dict[str, Any]) -> tuple[str, str]:
    text = parent["text"]
    source = "; ".join(
        item for item in (
            str(parent.get("source_name") or ""),
            f"page {parent['page_start']}" if parent.get("page_start") not in (None, -1) else "",
            " > ".join(parent.get("section_path") or []) if isinstance(parent.get("section_path"), list) else str(parent.get("section_path") or ""),
        ) if item
    )
    answer = f"根据 {source or '公共知识库'}：{text}"[:8000]
    context = f"来源：{source or '公共知识库'}\n{text}"[:12000]
    return answer, context


def _base_query(query_id: str, parent: dict[str, Any], scenario: str = "stable_technical") -> dict[str, Any]:
    question = _question(parent["text"], str(parent["technology"]), str(parent["parent_id"]))
    answer, context = _reference(parent)
    role = _role(parent["role_tags"])
    technology = str(parent["technology"])
    return {
        "query_id": query_id,
        "scenario_type": scenario,
        "topic": technology,
        "query": question,
        "role": role,
        "difficulty": "medium",
        "expected_technologies": [technology],
        "relevance": {str(parent["parent_id"]): 2},
        "expected_knowledge_points": [technology],
        "reference_answer": answer,
        "reference_context_ids": [str(parent["parent_id"])],
        "reference_contexts": [context],
        "expected_route": "public_kb",
        "expected_tools": ["public_milvus_search"],
        "expected_citations": [str(parent["parent_id"])],
        "safety_tags": [],
        "knowledge_scope": "public",
    }


def bind_source_grounded(rows: list[dict[str, Any]], source_path: Path) -> None:
    raw = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    parents = _parents(rows)
    bound = []
    missing = []
    for item in raw.get("queries", []):
        document_id = next(iter((item.get("relevance") or {})), "")
        candidates = [p for p in parents.values() if p["document_id"] == document_id]
        query_text = str(item.get("query") or "")
        selected = next((p for p in candidates if any(term.lower() in p["text"].lower() for term in query_text.split() if len(term) > 2)), None)
        selected = selected or (candidates[0] if candidates else None)
        if selected is None:
            missing.append(item.get("query_id"))
            bound.append(item)
            continue
        answer, context = _reference(selected)
        updated = dict(item)
        updated["relevance"] = {selected["parent_id"]: 2}
        updated["reference_answer"] = answer
        updated["reference_context_ids"] = [selected["parent_id"]]
        updated["reference_contexts"] = [context]
        updated["expected_route"] = "public_kb"
        updated["expected_tools"] = ["public_milvus_search"]
        updated["expected_citations"] = [selected["parent_id"]]
        updated["knowledge_scope"] = "public"
        bound.append(updated)
    if missing:
        raise RuntimeError("could not bind historical samples: " + ", ".join(str(x) for x in missing))
    source_path.write_text(yaml.safe_dump({**raw, "queries": bound}, allow_unicode=True, sort_keys=False), encoding="utf-8")


def bind_golden(rows: list[dict[str, Any]], golden_path: Path) -> None:
    parents = _parents(rows)
    by_technology: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for parent in parents.values():
        # Q&A parents are the most useful evidence for interview retrieval;
        # retain a paragraph only when a technology has too few Q&A parents.
        by_technology[str(parent["technology"])].append(parent)
    selected: list[dict[str, Any]] = []
    for technology in sorted(by_technology):
        candidates = sorted(by_technology[technology], key=lambda p: (p["parent_type"] != "qa", p["parent_id"]))
        selected.extend(candidates[:5])
    if len(selected) < 100:
        remaining = sorted(parents.values(), key=lambda p: (p["parent_type"] != "qa", p["parent_id"]))
        seen = {p["parent_id"] for p in selected}
        selected.extend(p for p in remaining if p["parent_id"] not in seen)
    selected = selected[:100]
    if len(selected) != 100:
        raise RuntimeError(f"published corpus contains only {len(selected)} usable parents")
    queries = [_base_query(f"g-{index:03d}", parent) for index, parent in enumerate(selected, 1)]
    golden_path.write_text(yaml.safe_dump({
        "benchmark_version": "golden-v2",
        "embedding_model": "text-embedding-v4",
        "top_k": 5,
        "queries": queries,
    }, allow_unicode=True, sort_keys=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--source-grounded", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    args = parser.parse_args()
    rows = _load_rows(args.chunks)
    bind_source_grounded(rows, args.source_grounded)
    bind_golden(rows, args.golden)
    print(json.dumps({"corpus_version": "full-authorized-v1", "rows": len(rows), "golden_samples": 100}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
