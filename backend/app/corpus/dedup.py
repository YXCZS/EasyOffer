from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.corpus.models import ChildChunk


@dataclass(frozen=True)
class DuplicateRecord:
    chunk_id: str
    duplicate_of: str
    kind: str


@dataclass(frozen=True)
class DeduplicationResult:
    kept: list[ChildChunk]
    duplicates: list[DuplicateRecord]


def _canonical(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.lower())


def _simhash(text: str) -> int:
    canonical = _canonical(text)
    tokens = [canonical[index : index + 5] for index in range(max(1, len(canonical) - 4))]
    if not tokens:
        tokens = [canonical]
    weights = [0] * 64
    for token in tokens:
        value = int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "big")
        for bit in range(64):
            weights[bit] += 1 if value & (1 << bit) else -1
    fingerprint = 0
    for bit, weight in enumerate(weights):
        if weight >= 0:
            fingerprint |= 1 << bit
    return fingerprint


def deduplicate_chunks(chunks: list[ChildChunk], near_distance: int = 3) -> DeduplicationResult:
    exact: dict[str, ChildChunk] = {}
    buckets: dict[int, list[tuple[int, ChildChunk]]] = {}
    kept: list[ChildChunk] = []
    duplicates: list[DuplicateRecord] = []
    for chunk in sorted(
        chunks,
        key=lambda item: (item.authority_priority, item.document_id, item.child_index, item.chunk_id),
    ):
        canonical_hash = hashlib.sha256(_canonical(chunk.evidence_text).encode("utf-8")).hexdigest()
        if canonical_hash in exact:
            duplicates.append(DuplicateRecord(chunk.chunk_id, exact[canonical_hash].chunk_id, "exact"))
            continue
        fingerprint = _simhash(chunk.evidence_text)
        bucket = fingerprint >> 48
        near = next(
            (
                existing
                for existing_fingerprint, existing in buckets.get(bucket, [])
                if (fingerprint ^ existing_fingerprint).bit_count() <= near_distance
            ),
            None,
        )
        if near is not None:
            duplicates.append(DuplicateRecord(chunk.chunk_id, near.chunk_id, "near"))
            continue
        exact[canonical_hash] = chunk
        buckets.setdefault(bucket, []).append((fingerprint, chunk))
        kept.append(chunk)
    return DeduplicationResult(kept=kept, duplicates=duplicates)
