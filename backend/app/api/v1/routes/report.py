from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.dependencies import get_db, get_report_service
from app.core.auth import get_optional_user
from app.models.common import ApiResponse
from app.models.report import Report, ReportGenerateRequest
from app.repositories.user_repository import save_report
from app.services.report_service import ReportService

router = APIRouter(prefix="/report", tags=["report"])


@router.post("/generate", response_model=ApiResponse[Report])
async def generate_report(
    request: ReportGenerateRequest,
    service: ReportService = Depends(get_report_service),
    user: dict | None = Depends(get_optional_user),
    connection: Any = Depends(get_db),
) -> ApiResponse[Report]:
    report = await service.generate(request, user_id=user["user_id"] if user else None)
    if user is not None:
        if connection is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="数据库暂不可用")
        await save_report(connection, user["user_id"], request, report)
    return ApiResponse(data=report)
