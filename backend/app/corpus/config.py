from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_GATES = {
    "hit_at_5": {"operator": "min", "value": 0.85},
    "mrr_at_5": {"operator": "min", "value": 0.70},
    "ndcg_at_5": {"operator": "min", "value": 0.75},
    "role_contamination_rate": {"operator": "max", "value": 0.05},
    "duplicate_result_rate": {"operator": "max", "value": 0.10},
    "parent_recovery_rate": {"operator": "min", "value": 1.0},
    "source_traceability_rate": {"operator": "min", "value": 1.0},
    "answer_integrity_rate": {"operator": "min", "value": 1.0},
}


@dataclass(frozen=True)
class CorpusConfig:
    runtime_root: Path = Path("data/public-corpus")
    review_root: Path = Path("corpus/reviews")
    pipeline_revision: str = "mineru-structured-v2"
    pilot_technologies: tuple[str, ...] = ("Redis", "MySQL", "RAG", "Milvus")
    parent_min_chars: int = 120
    parent_max_chars: int = 1800
    child_chunk_size: int = 850
    child_chunk_overlap: int = 100
    max_chunks_per_document: int = 5000
    structure_confidence_threshold: float = 0.55
    near_duplicate_hamming_distance: int = 3
    duplicate_content_ratio_threshold: float = 0.50
    boundary_classifier_enabled: bool = False
    gates: dict[str, dict[str, float | str]] = field(
        default_factory=lambda: {key: dict(value) for key, value in DEFAULT_GATES.items()}
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "runtime_root", Path(self.runtime_root))
        object.__setattr__(self, "review_root", Path(self.review_root))
        if self.child_chunk_overlap < 0 or self.child_chunk_overlap >= self.child_chunk_size:
            raise ValueError("child_chunk_overlap must be smaller than child_chunk_size")
        if self.parent_max_chars < self.child_chunk_size:
            raise ValueError("parent_max_chars must be at least child_chunk_size")
        if not 0 <= self.duplicate_content_ratio_threshold <= 1:
            raise ValueError("duplicate_content_ratio_threshold must be between 0 and 1")
        if not self.pipeline_revision.strip():
            raise ValueError("pipeline_revision must not be empty")

    @classmethod
    def load(cls, path: str | Path | None = None) -> "CorpusConfig":
        if path is None:
            return cls()
        import yaml

        config_path = Path(path)
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("corpus config must be a mapping")
        values: dict[str, Any] = dict(raw)
        for field_name in ("runtime_root", "review_root"):
            if field_name in values:
                root = Path(values[field_name])
                values[field_name] = root if root.is_absolute() else (config_path.parent / root).resolve()
        if "pilot_technologies" in values:
            values["pilot_technologies"] = tuple(values["pilot_technologies"])
        return cls(**values)
