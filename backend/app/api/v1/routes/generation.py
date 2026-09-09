from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.api.v1.dependencies import get_db, get_incremental_quiz_service
from app.core.auth import get_optional_user
from app.core.config import get_settings
from app.core.guest import hash_guest_token
from app.models.common import ApiResponse
from app.models.generation import (
    QuizGenerationTaskCreateRequest,
    QuizGenerationTaskProgressRequest,
    QuizGenerationTaskSnapshot,
)
from app.services.incremental_quiz_service import IncrementalQuizService
from app.repositories import generation_repository
from app.services.content_security_service import check_text_safety

router = APIRouter(prefix="/quiz/generation-tasks", tags=["quiz-generation"])


def require_connection(connection: Any) -> Any:
    if connection is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="数据库暂不可用")
    return connection


def _user_id(user: dict | None) -> int | None:
    return user["user_id"] if user else None


def _guest_hash(user: dict | None, guest_token: str | None) -> str | None:
    return None if user else hash_guest_token(guest_token)


def _task_handles(app: Any) -> dict[str, asyncio.Task]:
    handles = getattr(app.state, "generation_task_handles", None)
    if handles is None:
        handles = {}
        app.state.generation_task_handles = handles
    return handles


def _schedule(app: Any, service: IncrementalQuizService, task_id: str, user_id: int | None, guest_token_hash: str | None = None) -> None:
    handles = _task_handles(app)
    existing = handles.get(task_id)
    if existing and not existing.done():
        return
    pool = getattr(app.state, "db_pool", None)
    task = asyncio.create_task(service.run_task(pool, task_id, user_id, guest_token_hash))
    handles[task_id] = task

    def cleanup(done: asyncio.Task) -> None:
        if handles.get(task_id) is done:
            handles.pop(task_id, None)

    task.add_done_callback(cleanup)


@router.post("", response_model=ApiResponse[QuizGenerationTaskSnapshot])
async def create_generation_task(
    payload: QuizGenerationTaskCreateRequest,
    http_request: Request,
    service: IncrementalQuizService = Depends(get_incremental_quiz_service),
    user: dict | None = Depends(get_optional_user),
    guest_token: str | None = Header(default=None, alias="X-Guest-Token"),
    connection: Any = Depends(get_db),
) -> ApiResponse[QuizGenerationTaskSnapshot]:
    settings = get_settings()
    if user is None and payload.use_personal_knowledge:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="personal knowledge requires login")
    if user is None and not settings.guest_generation_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="请登录后生成题目")
    if user is None and payload.document_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请登录后使用个人知识库")
    await check_text_safety(payload.user_input, user.get("openid") if user else None)
    guest_hash = _guest_hash(user, guest_token)
    connection = require_connection(connection)
    if user is None and guest_hash:
        reserved = await generation_repository.reserve_guest_task(
            connection, guest_hash, settings.guest_max_active_tasks, settings.guest_daily_task_limit
        )
        if not reserved:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="游客额度已用完，请稍后再试或登录后继续")
    try:
        snapshot = await service.create(payload, _user_id(user), connection, guest_hash)
    except Exception:
        if user is None and guest_hash:
            await generation_repository.release_guest_task(connection, guest_hash)
        raise
    _schedule(http_request.app, service, snapshot.task_id, _user_id(user), guest_hash)
    return ApiResponse(data=snapshot)


@router.get("/{task_id}", response_model=ApiResponse[QuizGenerationTaskSnapshot])
async def get_generation_task(
    task_id: str,
    user: dict | None = Depends(get_optional_user),
    guest_token: str | None = Header(default=None, alias="X-Guest-Token"),
    connection: Any = Depends(get_db),
    service: IncrementalQuizService = Depends(get_incremental_quiz_service),
) -> ApiResponse[QuizGenerationTaskSnapshot]:
    snapshot = await service.snapshot(require_connection(connection), task_id, _user_id(user), _guest_hash(user, guest_token))
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="生成任务不存在")
    return ApiResponse(data=snapshot)


@router.put("/{task_id}/progress", response_model=ApiResponse[QuizGenerationTaskSnapshot])
async def save_generation_progress(
    task_id: str,
    payload: QuizGenerationTaskProgressRequest,
    user: dict | None = Depends(get_optional_user),
    guest_token: str | None = Header(default=None, alias="X-Guest-Token"),
    connection: Any = Depends(get_db),
    service: IncrementalQuizService = Depends(get_incremental_quiz_service),
) -> ApiResponse[QuizGenerationTaskSnapshot]:
    snapshot = await service.save_progress(require_connection(connection), task_id, _user_id(user), payload, _guest_hash(user, guest_token))
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="生成任务版本已变化，请刷新后重试")
    return ApiResponse(data=snapshot)


@router.post("/{task_id}/retry", response_model=ApiResponse[QuizGenerationTaskSnapshot])
async def retry_generation_task(
    task_id: str,
    http_request: Request,
    user: dict | None = Depends(get_optional_user),
    guest_token: str | None = Header(default=None, alias="X-Guest-Token"),
    connection: Any = Depends(get_db),
    service: IncrementalQuizService = Depends(get_incremental_quiz_service),
) -> ApiResponse[QuizGenerationTaskSnapshot]:
    user_id = _user_id(user)
    guest_hash = _guest_hash(user, guest_token)
    snapshot = await service.retry(require_connection(connection), task_id, user_id, guest_hash)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在或不可重试")
    _schedule(http_request.app, service, task_id, user_id, guest_hash)
    return ApiResponse(data=snapshot)


@router.post("/{task_id}/cancel", response_model=ApiResponse[QuizGenerationTaskSnapshot])
async def cancel_generation_task(
    task_id: str,
    http_request: Request,
    user: dict | None = Depends(get_optional_user),
    guest_token: str | None = Header(default=None, alias="X-Guest-Token"),
    connection: Any = Depends(get_db),
    service: IncrementalQuizService = Depends(get_incremental_quiz_service),
) -> ApiResponse[QuizGenerationTaskSnapshot]:
    user_id = _user_id(user)
    guest_hash = _guest_hash(user, guest_token)
    # Read first so repeated taps are idempotent and guest quota is released
    # only when this request actually transitions an active task.
    before = await service.snapshot(require_connection(connection), task_id, user_id, guest_hash)
    if before is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="generation task not found")
    if before.status not in ("queued", "generating"):
        return ApiResponse(data=before)
    handle = _task_handles(http_request.app).get(task_id)
    if handle and not handle.done():
        handle.cancel()
    snapshot = await service.cancel(require_connection(connection), task_id, user_id, guest_hash)
    if snapshot is None:
        latest = await service.snapshot(require_connection(connection), task_id, user_id, guest_hash)
        if latest is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="generation task not found")
        return ApiResponse(data=latest)
    if guest_hash:
        await generation_repository.release_guest_task(connection, guest_hash)
    return ApiResponse(data=snapshot)
