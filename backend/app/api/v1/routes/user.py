from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from app.api.v1.dependencies import get_db
from app.core.auth import get_current_user
from app.core.config import get_settings
from app.models.common import ApiResponse
from app.models.user import (
    QuizHistoryDetail,
    QuizHistoryPage,
    UserLoginRequest,
    UserLoginResponse,
    UserProfile,
    UserProfileUpdate,
)
from app.repositories import user_repository
from app.services import user_service

router = APIRouter(prefix="/user", tags=["user"])
ALLOWED_AVATAR_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
MAX_AVATAR_BYTES = 5 * 1024 * 1024


def require_connection(connection: Any) -> Any:
    if connection is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="数据库暂不可用")
    return connection


@router.post("/login", response_model=ApiResponse[UserLoginResponse])
async def login(request: UserLoginRequest, connection: Any = Depends(get_db)) -> ApiResponse[UserLoginResponse]:
    try:
        result = await user_service.login(require_connection(connection), request.code)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.get("/profile", response_model=ApiResponse[UserProfile])
async def profile(user: dict = Depends(get_current_user), connection: Any = Depends(get_db)) -> ApiResponse[UserProfile]:
    row = await user_repository.get_user_profile(require_connection(connection), user["user_id"])
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return ApiResponse(data=row)


@router.put("/profile", response_model=ApiResponse[UserProfile])
async def update_profile(
    request: UserProfileUpdate,
    user: dict = Depends(get_current_user),
    connection: Any = Depends(get_db),
) -> ApiResponse[UserProfile]:
    connection = require_connection(connection)
    await user_repository.update_user_profile(
        connection,
        user["user_id"],
        request.nickname,
        str(request.avatar_url) if request.avatar_url else None,
    )
    row = await user_repository.get_user_profile(connection, user["user_id"])
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return ApiResponse(data=row)


@router.post("/avatar", response_model=ApiResponse[UserProfile])
async def upload_avatar(
    image: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    connection: Any = Depends(get_db),
) -> ApiResponse[UserProfile]:
    connection = require_connection(connection)
    extension = ALLOWED_AVATAR_TYPES.get(image.content_type or "")
    if extension is None:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="只支持 JPG、PNG 或 WebP 图片")
    content = await image.read(MAX_AVATAR_BYTES + 1)
    if len(content) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="头像图片不能超过 5MB")
    settings = get_settings()
    avatar_dir = Path(settings.upload_dir).resolve() / "avatars"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    target = avatar_dir / f"user_{user['user_id']}.{extension}"
    target.write_bytes(content)
    avatar_url = f"{settings.public_base_url.rstrip('/')}/uploads/avatars/{target.name}"
    await user_repository.update_user_profile(connection, user["user_id"], None, avatar_url)
    row = await user_repository.get_user_profile(connection, user["user_id"])
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return ApiResponse(data=row)


@router.get("/quizzes", response_model=ApiResponse[QuizHistoryPage])
async def quizzes(
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=10, ge=1, le=50),
    user: dict = Depends(get_current_user),
    connection: Any = Depends(get_db),
) -> ApiResponse[QuizHistoryPage]:
    data = await user_repository.list_quizzes(require_connection(connection), user["user_id"], page, page_size)
    return ApiResponse(data=data)


@router.get("/quizzes/{quiz_id}", response_model=ApiResponse[QuizHistoryDetail])
async def quiz_detail(
    quiz_id: str,
    user: dict = Depends(get_current_user),
    connection: Any = Depends(get_db),
) -> ApiResponse[QuizHistoryDetail]:
    data = await user_repository.get_quiz_detail(require_connection(connection), user["user_id"], quiz_id)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="闯关记录不存在")
    return ApiResponse(data=data)
