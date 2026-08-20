from fastapi import APIRouter, Depends

from app.api.v1.dependencies import get_report_service
from app.models.common import ApiResponse
from app.models.report import Report, ReportGenerateRequest
from app.services.report_service import ReportService

router = APIRouter(prefix="/report", tags=["report"])


@router.post("/generate", response_model=ApiResponse[Report])
async def generate_report(
    request: ReportGenerateRequest,
    service: ReportService = Depends(get_report_service),
) -> ApiResponse[Report]:
    return ApiResponse(data=await service.generate(request))
