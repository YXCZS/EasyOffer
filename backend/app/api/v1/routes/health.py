from fastapi import APIRouter

from app.models.common import ApiResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ApiResponse[dict[str, str]])
async def health() -> ApiResponse[dict[str, str]]:
    return ApiResponse(data={"status": "ok"})
