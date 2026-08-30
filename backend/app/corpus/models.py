from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator


LicenseStatus = Literal["approved", "local-evaluation-only", "rejected"]
ContentType = Literal[
    "pdf",
    "docx",
    "ppt",
    "pptx",
    "xls",
    "xlsx",
    "html",
    "image",
    "markdown",
    "webpage",
]


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=1000)
    title: str = Field(min_length=1, max_length=300)
    content_version: str = Field(min_length=1, max_length=120)
    retrieved_at: date
    license_decision: str = Field(min_length=1, max_length=300)


class SourceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    path: str | None = None
    source_name: str = Field(min_length=1, max_length=300)
    source_url: str | None = None
    technology: str = Field(min_length=1, max_length=100)
    role_tags: list[str] = Field(min_length=1)
    document_version: str = Field(min_length=1, max_length=100)
    language: str = "zh-CN"
    content_type: ContentType
    license_status: LicenseStatus
    target_corpus_version: str = Field(min_length=1, max_length=120)
    retrieved_at: date | None = None
    references: list[SourceReference] = Field(default_factory=list)
    authority_priority: int = Field(default=100, ge=0, le=1000)
    enabled: bool = True
    manifest_dir: Path = Field(default=Path("."), exclude=True, repr=False)

    @field_validator("role_tags")
    @classmethod
    def normalize_roles(cls, value: list[str]) -> list[str]:
        roles = list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
        if not roles:
            raise ValueError("role_tags must not be empty")
        return roles

    @model_validator(mode="after")
    def validate_location(self) -> "SourceEntry":
        if not self.path and not self.source_url:
            raise ValueError("source requires path or source_url")
        if self.content_type != "webpage" and not self.path:
            raise ValueError("file source requires path")
        return self

    @computed_field
    @property
    def publishable(self) -> bool:
        return self.license_status == "approved"

    @property
    def resolved_path(self) -> Path | None:
        if not self.path:
            return None
        candidate = Path(self.path)
        return candidate.resolve() if candidate.is_absolute() else (self.manifest_dir / candidate).resolve()


class SourceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: str = Field(min_length=1, max_length=120)
    sources: list[SourceEntry] = Field(min_length=1)


@dataclass(frozen=True)
class ParsedBlock:
    text: str
    kind: str = "paragraph"
    page_start: int | None = None
    page_end: int | None = None
    section_path: list[str] = field(default_factory=list)
    start_index: int = 0
    heading_level: int | None = None
    bbox: list[float] | None = None
    media_path: str = ""
    mineru_node_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedDocument:
    source: SourceEntry
    text: str
    blocks: list[ParsedBlock]
    page_count: int | None = None
    warnings: list[str] = field(default_factory=list)
    rejected_blocks: list[dict[str, Any]] = field(default_factory=list)
    parser_name: str = "local"
    parser_schema: str = "text"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParentUnit:
    parent_id: str
    document_id: str
    document_version: str
    parent_index: int
    parent_type: str
    title: str
    text: str
    section_path: list[str]
    page_start: int | None
    page_end: int | None
    start_index: int
    document_hash: str
    content_hash: str
    structure_confidence: float
    heading_level: int | None = None
    bbox: list[float] | None = None
    media_path: str = ""
    mineru_node_path: str = ""
    structure_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChildChunk:
    chunk_id: str
    document_id: str
    document_version: str
    corpus_version: str
    parent_id: str
    parent_type: str
    child_index: int
    start_index: int
    evidence_text: str
    embedding_text: str
    document_hash: str
    parent_hash: str
    content_hash: str
    technology: str
    role_tags: list[str]
    knowledge_type: str
    section_path: list[str]
    source_name: str
    source_url: str
    reference_urls: list[str]
    page_start: int | None
    page_end: int | None
    language: str
    license_status: str
    authority_priority: int
    review_status: str = "pending"
    status: str = "unpublished"
    published_at: str | None = None
    structure_confidence: float = 0.0
    duplicate_of: str | None = None
    heading_level: int | None = None
    bbox: list[float] | None = None
    media_path: str = ""
    mineru_node_path: str = ""
    structure_metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        value = asdict(self)
        value["text"] = value.pop("evidence_text")
        return value


@dataclass
class DocumentProcessResult:
    document_id: str
    status: str
    page_count: int | None = None
    text_length: int = 0
    parent_count: int = 0
    chunk_count: int = 0
    duplicate_count: int = 0
    parsed_block_count: int = 0
    assigned_block_count: int = 0
    rejected_blocks: list[dict[str, Any]] = field(default_factory=list)
    completed_stages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    quality_issues: list[str] = field(default_factory=list)
    failure_reason: str | None = None


@dataclass
class BatchResult:
    batch_id: str
    corpus_version: str
    mode: str
    documents: list[DocumentProcessResult]
    report_path: Path
    stage_path: Path | None = None

    @property
    def chunk_count(self) -> int:
        return sum(item.chunk_count for item in self.documents if item.status != "failed")


@dataclass(frozen=True)
class PublicationResult:
    corpus_version: str
    published_count: int
    previous_version: str | None
    report_path: Path
