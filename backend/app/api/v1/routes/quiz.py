from fastapi import APIRouter, Depends

from app.api.v1.dependencies import get_quiz_service
from app.models.common import ApiResponse
from app.models.quiz import Quiz, QuizGenerateRequest
from app.services.quiz_service import QuizService

router = APIRouter(prefix="/quiz", tags=["quiz"])


@router.post("/generate", response_model=ApiResponse[Quiz])
async def generate_quiz(
    request: QuizGenerateRequest,
    service: QuizService = Depends(get_quiz_service),
) -> ApiResponse[Quiz]:
    return ApiResponse(data=await service.generate(request))
