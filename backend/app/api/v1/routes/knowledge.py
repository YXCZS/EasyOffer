from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status

from app.api.v1.dependencies import get_db
from app.core.auth import get_current_user
from app.models.common import ApiResponse
from app.models.knowledge import KnowledgeDocument, KnowledgeDocumentPage, KnowledgeDocumentRenameRequest
from app.repositories import knowledge_repository
from app.services.knowledge_service import KnowledgeValidationError, SecureDocumentStorage, document_hash, process_document, validate_upload

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def require_connection(connection: Any) -> Any:
    if connection is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="数据库暂不可用")
    return connection


def to_model(row: dict[str, Any]) -> KnowledgeDocument:
    return KnowledgeDocument.model_validate({key: row.get(key) for key in KnowledgeDocument.model_fields})


@router.get("/documents", response_model=ApiResponse[KnowledgeDocumentPage])
async def list_knowledge_documents(
    page: int = Query(1, ge=1, le=10000),
    page_size: int = Query(10, ge=1, le=50),
    user: dict = Depends(get_current_user),
    connection: Any = Depends(get_db),
) -> ApiResponse[KnowledgeDocumentPage]:
    data = await knowledge_repository.list_documents(require_connection(connection), user["user_id"], page, page_size)
    data["items"] = [to_model(item) for item in data["items"]]
    return ApiResponse(data=KnowledgeDocumentPage.model_validate(data))


@router.get("/documents/{document_id}", response_model=ApiResponse[KnowledgeDocument])
async def get_knowledge_document(document_id: str, user: dict = Depends(get_current_user), connection: Any = Depends(get_db)) -> ApiResponse[KnowledgeDocument]:
    row = await knowledge_repository.get_document(require_connection(connection), user["user_id"], document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return ApiResponse(data=to_model(row))


@router.post("/documents", response_model=ApiResponse[KnowledgeDocument])
async def upload_knowledge_document(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
    user: dict = Depends(get_current_user),
    connection: Any = Depends(get_db),
) -> ApiResponse[KnowledgeDocument]:
    connection = require_connection(connection)
    content = await file.read()
    try:
        name, mime = validate_upload(file.filename, file.content_type, content)
    except KnowledgeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    user_id = user["user_id"]
    from app.core.config import get_settings
    if await knowledge_repository.count_user_documents(connection, user_id) >= get_settings().knowledge_max_documents:
        raise HTTPException(status_code=413, detail="个人知识库文档数量已达上限")
    content_hash = document_hash(content)
    existing = await knowledge_repository.find_by_hash(connection, user_id, content_hash)
    if existing:
        return ApiResponse(data=to_model(existing))
    storage = SecureDocumentStorage()
    path = storage.save(user_id, name, content)
    document_id = f"doc_{uuid4().hex}"
    try:
        row = await knowledge_repository.create_document(connection, {"document_id": document_id, "user_id": user_id, "original_name": name, "storage_path": path, "content_hash": content_hash, "mime_type": mime, "file_size": len(content)})
        # The processor is isolated behind a task boundary; inline execution keeps local MVP deployments deterministic.
        await process_document(connection, user_id, document_id, storage)
        row = await knowledge_repository.get_document(connection, user_id, document_id)
    except Exception:
        storage.remove(path)
        raise
    return ApiResponse(data=to_model(row))


@router.post("/documents/{document_id}/retry", response_model=ApiResponse[KnowledgeDocument])
async def retry_knowledge_document(document_id: str, user: dict = Depends(get_current_user), connection: Any = Depends(get_db)) -> ApiResponse[KnowledgeDocument]:
    connection = require_connection(connection)
    row = await knowledge_repository.get_document(connection, user["user_id"], document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    if row["status"] != "failed":
        raise HTTPException(status_code=409, detail="只有处理失败的文档可以重试")
    await knowledge_repository.reset_processing(connection, user["user_id"], document_id)
    await process_document(connection, user["user_id"], document_id)
    row = await knowledge_repository.get_document(connection, user["user_id"], document_id)
    return ApiResponse(data=to_model(row))


@router.patch("/documents/{document_id}", response_model=ApiResponse[KnowledgeDocument])
@router.put("/documents/{document_id}", response_model=ApiResponse[KnowledgeDocument])
async def rename_knowledge_document(
    document_id: str,
    request: KnowledgeDocumentRenameRequest,
    user: dict = Depends(get_current_user),
    connection: Any = Depends(get_db),
) -> ApiResponse[KnowledgeDocument]:
    connection = require_connection(connection)
    row = await knowledge_repository.get_document(connection, user["user_id"], document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    updated = await knowledge_repository.rename_document(
        connection, user["user_id"], document_id, request.original_name
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return ApiResponse(data=to_model(updated))


@router.delete("/documents/{document_id}", response_model=ApiResponse[dict[str, bool]])
async def delete_knowledge_document(document_id: str, user: dict = Depends(get_current_user), connection: Any = Depends(get_db)) -> ApiResponse[dict[str, bool]]:
    connection = require_connection(connection)
    row = await knowledge_repository.delete_document(connection, user["user_id"], document_id)
    if row is None:
        return ApiResponse(data={"deleted": True})
    try:
        from app.services.knowledge_service import get_vector_store
        get_vector_store(user["user_id"]).delete_document(document_id)
    except Exception:
        pass
    SecureDocumentStorage().remove(row["storage_path"])
    return ApiResponse(data={"deleted": True})
