from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.v1.dependencies import get_db, get_quiz_service, get_visual_asset_service
from app.core.auth import get_optional_user
from app.models.common import ApiResponse
from app.models.quiz import Quiz, QuizGenerateRequest
from app.repositories.user_repository import save_quiz
from app.repositories.progress_repository import create_progress
from app.services.quiz_service import QuizService
from app.services.visual_asset_service import VisualAssetService
from app.services.content_security_service import check_text_safety

router = APIRouter(prefix="/quiz", tags=["quiz"])


@router.post("/generate", response_model=ApiResponse[Quiz])
async def generate_quiz(
    request: QuizGenerateRequest,
    http_request: Request,
    service: QuizService = Depends(get_quiz_service),
    user: dict | None = Depends(get_optional_user),
    connection: Any = Depends(get_db),
    visual_assets: VisualAssetService = Depends(get_visual_asset_service),
) -> ApiResponse[Quiz]:
    if user is None and request.use_personal_knowledge:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="personal knowledge requires login")
    await check_text_safety(request.user_input, user.get("openid") if user else None)
    quiz = await service.generate(
        request,
        user_id=user["user_id"] if user else None,
        connection=connection,
    )
    if user is not None:
        if connection is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="数据库暂不可用")
        await save_quiz(connection, user["user_id"], request.user_input, quiz)
        await create_progress(connection, user["user_id"], quiz)
    if request.generate_images:
        for question in quiz.questions:
            await visual_assets.schedule(
                getattr(http_request.app.state, "db_pool", None),
                question,
                task_id=None,
                quiz_id=quiz.quiz_id,
                user_id=user["user_id"] if user else None,
            )
    return ApiResponse(data=quiz)
