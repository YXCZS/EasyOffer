from typing import Literal

from pydantic import Field, field_validator

from app.models.common import StrictModel

DocumentStatus = Literal["processing", "ready", "failed"]


class KnowledgeDocument(StrictModel):
    document_id: str
    original_name: str
    mime_type: str
    file_size: int
    status: DocumentStatus
    error_message: str | None = None
    chunk_count: int = 0
    embedding_model: str | None = None
    created_at: str
    updated_at: str


class KnowledgeDocumentPage(StrictModel):
    items: list[KnowledgeDocument]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=50)


class KnowledgeDocumentRenameRequest(StrictModel):
    original_name: str = Field(min_length=1, max_length=255)

    @field_validator("original_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("文档名称不能为空")
        return value
