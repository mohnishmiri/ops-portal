"""
Report Generation API Endpoints.

Downloadable PDF reports — executive-ready, scheduled or on-demand.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.auth import get_current_user
from app.models.auth import UserContext
from app.models.notification import ReportMetadata, ReportRequest, ReportType
from app.services.report_service import ReportService

router = APIRouter()


def _get_report_service() -> ReportService:
    return ReportService()


@router.post(
    "/generate",
    response_model=ReportMetadata,
    summary="Generate a new PDF report",
)
async def generate_report(
    request: ReportRequest,
    user: UserContext = Depends(get_current_user),
    service: ReportService = Depends(_get_report_service),
) -> ReportMetadata:
    """Generate a downloadable PDF report on demand."""
    return await service.generate_report(
        report_type=request.report_type,
        subscription_ids=request.subscription_ids or user.allowed_subscriptions or None,
        include_recommendations=request.include_recommendations,
        requested_by=user.display_name,
        title=request.title,
    )


@router.get(
    "/download/{report_id}",
    summary="Download a generated report",
)
async def download_report(
    report_id: str,
    user: UserContext = Depends(get_current_user),
    service: ReportService = Depends(_get_report_service),
) -> StreamingResponse:
    """Download a previously generated PDF report."""
    pdf_bytes, filename = await service.get_report_file(report_id)
    return StreamingResponse(
        content=iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/list",
    response_model=list[ReportMetadata],
    summary="List available reports",
)
async def list_reports(
    report_type: ReportType | None = None,
    limit: int = 20,
    user: UserContext = Depends(get_current_user),
    service: ReportService = Depends(_get_report_service),
) -> list[ReportMetadata]:
    """List previously generated reports."""
    return await service.list_reports(report_type=report_type, limit=limit)
