from __future__ import annotations

import re
from typing import Any, Protocol


class CorpusStore(Protocol):
    def upsert(self, records: list[dict[str, Any]]) -> int: ...
    def query(self, filter_expr: str = "", limit: int = 10000) -> list[dict[str, Any]]: ...
    def update(self, filter_expr: str, **fields: Any) -> int: ...
    def count(self, filter_expr: str = "") -> int: ...
    def search(self, query: str, k: int, *, role: str | None = None, corpus_version: str | None = None, status: str | None = None) -> list[Any]: ...
    def smoke(self, corpus_version: str) -> bool: ...


def _matches(row: dict[str, Any], expression: str) -> bool:
    if not expression:
        return True
    for clause in re.split(r"\s+and\s+", expression):
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*==\s*'((?:\\'|[^'])*)'", clause.strip())
        if match:
            expected = match.group(2).replace("\\'", "'")
            if str(row.get(match.group(1), "")) != expected:
                return False
            continue
        raise ValueError(f"unsupported in-memory filter: {clause}")
    return True


class InMemoryCorpusStore:
    def __init__(self):
        self._rows: dict[str, dict[str, Any]] = {}
        self.fail_next_smoke = False

    @property
    def rows(self) -> list[dict[str, Any]]:
        return list(self._rows.values())

    def upsert(self, records: list[dict[str, Any]]) -> int:
        for record in records:
            self._rows[str(record["chunk_id"])] = dict(record)
        return len(records)

    def query(self, filter_expr: str = "", limit: int = 10000) -> list[dict[str, Any]]:
        return [dict(row) for row in self._rows.values() if _matches(row, filter_expr)][:limit]

    def update(self, filter_expr: str, **fields: Any) -> int:
        count = 0
        for key, row in list(self._rows.items()):
            if _matches(row, filter_expr):
                self._rows[key] = {**row, **fields}
                count += 1
        return count

    def count(self, filter_expr: str = "") -> int:
        return len(self.query(filter_expr))

    def search(self, query: str, k: int, *, role: str | None = None, corpus_version: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        terms = [term.lower() for term in re.split(r"\s+", query) if term]
        candidates = self.rows
        if corpus_version:
            candidates = [row for row in candidates if row.get("corpus_version") == corpus_version]
        effective_status = status or "published"
        candidates = [row for row in candidates if row.get("status") == effective_status]
        if role:
            candidates = [row for row in candidates if role in row.get("role_tags", []) or "general" in row.get("role_tags", [])]
        for row in candidates:
            text = str(row.get("embedding_text") or row.get("text") or "").lower()
            row["score"] = sum(1 for term in terms if term in text) / max(1, len(terms))
        return sorted(candidates, key=lambda row: row["score"], reverse=True)[:k]

    def smoke(self, corpus_version: str) -> bool:
        if self.fail_next_smoke:
            self.fail_next_smoke = False
            return False
        return self.count(f"corpus_version == '{corpus_version}' and status == 'published'") > 0


class MilvusCorpusStore:
    def __init__(self):
        from app.services.knowledge_service import get_public_vector_store

        self.store = get_public_vector_store()

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")

    def upsert(self, records: list[dict[str, Any]]) -> int:
        self.store.upsert_public_chunks(records)
        return len(records)

    def query(self, filter_expr: str = "", limit: int = 10000) -> list[dict[str, Any]]:
        return self.store.query_public_chunks(filter_expr, limit=limit)

    def update(self, filter_expr: str, **fields: Any) -> int:
        return self.store.update_public_chunks(filter_expr, **fields)

    def count(self, filter_expr: str = "") -> int:
        return len(self.query(filter_expr))

    def search(self, query: str, k: int, *, role: str | None = None, corpus_version: str | None = None, status: str | None = None) -> list[Any]:
        return self.store.search(
            query,
            k,
            role=role,
            corpus_version=corpus_version,
            status=status or "published",
        )

    def smoke(self, corpus_version: str) -> bool:
        rows = self.query(f"corpus_version == '{self._escape(corpus_version)}' and status == 'published'", limit=1)
        if not rows:
            return False
        query = str(rows[0].get("technology") or rows[0].get("text") or "技术面试")
        return bool(self.search(query, 1, corpus_version=corpus_version, status="published"))
