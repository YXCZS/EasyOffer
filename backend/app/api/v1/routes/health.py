from fastapi import APIRouter
from typing import Any

from app.models.common import ApiResponse
from app.core.config import get_settings
from app.services.milvus_admin import health_check as milvus_health_check

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ApiResponse[dict[str, Any]])
async def health() -> ApiResponse[dict[str, Any]]:
    if not get_settings().milvus_enabled:
        return ApiResponse(data={"status": "ok"})
    milvus = milvus_health_check()
    return ApiResponse(
        data={
            "status": "ok" if milvus.ok else "degraded",
            "milvus": {
                "ok": milvus.ok,
                "version": milvus.version,
                "error": milvus.error,
                "collections": milvus.collections or {},
            },
        }
    )
