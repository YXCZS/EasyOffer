import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.dependencies import get_db
from app.core.auth import get_current_user
from app.models.common import ApiResponse
from app.models.progress import IncompleteQuizList, ProgressSaveRequest, QuizProgressDetail
from app.repositories import progress_repository
from app.services.progress_service import ProgressConflictError, ProgressNotFoundError, save_progress, to_detail

router = APIRouter(prefix="/user/quizzes", tags=["quiz-progress"])
logger = logging.getLogger(__name__)


def require_connection(connection: Any) -> Any:
    if connection is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="数据库暂不可用")
    return connection


@router.get("/incomplete", response_model=ApiResponse[IncompleteQuizList])
async def incomplete_quizzes(
    user: dict = Depends(get_current_user),
    connection: Any = Depends(get_db),
) -> ApiResponse[IncompleteQuizList]:
    rows = await progress_repository.list_incomplete(require_connection(connection), user["user_id"])
    return ApiResponse(data={"items": rows})


@router.get("/{quiz_id}/progress", response_model=ApiResponse[QuizProgressDetail])
async def get_quiz_progress(
    quiz_id: str,
    user: dict = Depends(get_current_user),
    connection: Any = Depends(get_db),
) -> ApiResponse[QuizProgressDetail]:
    row = await progress_repository.get_progress(require_connection(connection), user["user_id"], quiz_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="练习进度不存在")
    return ApiResponse(data=to_detail(row))


@router.put("/{quiz_id}/progress", response_model=ApiResponse[QuizProgressDetail])
async def save_quiz_progress(
    quiz_id: str,
    request: ProgressSaveRequest,
    user: dict = Depends(get_current_user),
    connection: Any = Depends(get_db),
) -> ApiResponse[QuizProgressDetail]:
    connection = require_connection(connection)
    try:
        row = await save_progress(connection, user["user_id"], quiz_id, request)
    except ProgressNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="练习进度不存在") from exc
    except ProgressConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return ApiResponse(data=to_detail(row))


@router.delete("/{quiz_id}/progress", response_model=ApiResponse[dict[str, bool]])
async def abandon_quiz_progress(
    quiz_id: str,
    user: dict = Depends(get_current_user),
    connection: Any = Depends(get_db),
) -> ApiResponse[dict[str, bool]]:
    try:
        changed = await progress_repository.abandon_progress(require_connection(connection), user["user_id"], quiz_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("quiz_progress_abandon_failed quiz_id=%s user_id=%s", quiz_id, user["user_id"])
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="练习暂时无法删除，请稍后重试") from exc
    # Abandon is intentionally idempotent. A stale item can remain on the
    # client after the quiz was completed, cleaned up, or removed elsewhere;
    # treating that state as success keeps the delete action predictable.
    return ApiResponse(data={"abandoned": bool(changed)})
