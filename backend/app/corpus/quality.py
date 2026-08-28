from __future__ import annotations

from dataclasses import dataclass, field
import re

from app.corpus.config import CorpusConfig


@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: str
    document_id: str
    chunk_id: str | None = None


@dataclass(frozen=True)
class QualityReview:
    passed: bool
    issues: list[QualityIssue] = field(default_factory=list)


def review_records(records: list[dict], config: CorpusConfig) -> QualityReview:
    issues: list[QualityIssue] = []
    if not records:
        return QualityReview(False, [QualityIssue("no_chunks", "error", "")])
    versions: dict[str, set[str]] = {}
    for row in records:
        document_id = str(row.get("document_id") or "")
        chunk_id = str(row.get("chunk_id") or "") or None
        text = str(row.get("text") or "").strip()
        versions.setdefault(document_id, set()).add(str(row.get("document_version") or ""))
        if len(text) < 20:
            issues.append(QualityIssue("content_too_short", "error", document_id, chunk_id))
        if any(marker in text for marker in ("锟斤拷", "ï¿½", "�")):
            issues.append(QualityIssue("possible_mojibake", "error", document_id, chunk_id))
        if not row.get("source_name") and not row.get("source_url"):
            issues.append(QualityIssue("missing_source", "error", document_id, chunk_id))
        if not row.get("role_tags"):
            issues.append(QualityIssue("missing_role_tags", "error", document_id, chunk_id))
        if row.get("license_status") != "approved":
            issues.append(QualityIssue("license_not_approved", "error", document_id, chunk_id))
        if float(row.get("structure_confidence") or 0) < config.structure_confidence_threshold:
            issues.append(QualityIssue("low_structure_confidence", "warning", document_id, chunk_id))
        # A question parent is only required to contain an answer when its
        # text actually looks like an interview question. PDF extraction can
        # otherwise create short continuation/code fragments labelled as
        # questions (for example SQL '?' placeholders).
        looks_like_question = (
            re.search(r"(?:什么|如何|怎么|为什么|为何|区别|原理|流程|作用|场景|哪些|是否|能否|何时|怎样|请(?:说明|解释)|谈谈)", text)
            or re.search(r"(?:问题|question)\s*\d*\s*[:：]", text, re.IGNORECASE)
        )
        if row.get("parent_type") == "question" and looks_like_question and not re.search(r"(?:答案|解答|解析|answer)", text, re.IGNORECASE):
            issues.append(QualityIssue("answer_missing", "error", document_id, chunk_id))
        required = (
            "chunk_id", "document_id", "document_version", "corpus_version", "parent_id",
            "technology", "content_hash", "review_status", "status",
        )
        if any(not row.get(field) for field in required):
            issues.append(QualityIssue("metadata_incomplete", "error", document_id, chunk_id))
    for document_id, document_versions in versions.items():
        if len(document_versions) > 1:
            issues.append(QualityIssue("document_version_conflict", "error", document_id))
    return QualityReview(not any(item.severity == "error" for item in issues), issues)
