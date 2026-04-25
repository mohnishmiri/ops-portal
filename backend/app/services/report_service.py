"""
Report Service — PDF report generation.

Generates executive-ready PDF reports using Jinja2 templates + WeasyPrint.
"""

import uuid
from datetime import datetime, timedelta

import structlog

from app.models.notification import ReportMetadata, ReportType
from app.services.cost_service import CostService
from app.services.optimization_service import OptimizationService

logger = structlog.get_logger(__name__)

# In production, use a proper template directory
_REPORT_STORE: dict[str, tuple[bytes, ReportMetadata]] = {}


class ReportService:
    """PDF report generation service."""

    def __init__(self) -> None:
        self._cost_service = CostService()
        self._optimization_service = OptimizationService()

    async def generate_report(
        self,
        report_type: ReportType,
        subscription_ids: list[str] | None = None,
        include_recommendations: bool = True,
        requested_by: str = "system",
        title: str | None = None,
    ) -> ReportMetadata:
        """Generate a PDF report and store for download."""
        report_id = str(uuid.uuid4())
        report_title = title or f"Azure Cost Report — {report_type.value}"

        # Gather data
        overview = await self._cost_service.get_multi_subscription_overview(subscription_ids)

        opt_summary = None
        if include_recommendations:
            opt_summary = await self._optimization_service.get_optimization_summary(subscription_ids)

        # Render HTML → PDF
        html_content = self._render_html(report_type, overview, opt_summary, report_title)
        pdf_bytes = self._html_to_pdf(html_content)

        metadata = ReportMetadata(
            id=report_id,
            report_type=report_type,
            title=report_title,
            generated_at=datetime.utcnow(),
            generated_by=requested_by,
            file_size_bytes=len(pdf_bytes),
            download_url=f"/api/v1/reports/download/{report_id}",
            expires_at=datetime.utcnow() + timedelta(days=7),
        )

        # Store in memory (production would use blob storage)
        _REPORT_STORE[report_id] = (pdf_bytes, metadata)

        logger.info(
            "report_generated",
            report_id=report_id,
            report_type=report_type.value,
            size_bytes=len(pdf_bytes),
        )

        return metadata

    async def get_report_file(self, report_id: str) -> tuple[bytes, str]:
        """Retrieve a generated report file."""
        if report_id not in _REPORT_STORE:
            msg = f"Report {report_id} not found"
            raise FileNotFoundError(msg)

        pdf_bytes, metadata = _REPORT_STORE[report_id]
        filename = f"{metadata.report_type.value}_{metadata.generated_at.strftime('%Y%m%d')}.pdf"
        return pdf_bytes, filename

    async def list_reports(
        self,
        report_type: ReportType | None = None,
        limit: int = 20,
    ) -> list[ReportMetadata]:
        """List generated reports."""
        reports = [meta for _, meta in _REPORT_STORE.values()]
        if report_type:
            reports = [r for r in reports if r.report_type == report_type]
        return sorted(reports, key=lambda r: r.generated_at, reverse=True)[:limit]

    def _render_html(
        self,
        report_type: ReportType,
        overview: object,
        opt_summary: object | None,
        title: str,
    ) -> str:
        """Render report HTML using inline template (production would use Jinja2 files)."""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 40px; color: #333; }}
                h1 {{ color: #1976d2; border-bottom: 3px solid #1976d2; padding-bottom: 10px; }}
                h2 {{ color: #424242; margin-top: 30px; }}
                table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                th {{ background: #1976d2; color: white; padding: 12px; text-align: left; }}
                td {{ padding: 10px; border-bottom: 1px solid #e0e0e0; }}
                tr:nth-child(even) {{ background: #f5f5f5; }}
                .kpi-grid {{ display: flex; gap: 20px; flex-wrap: wrap; margin: 20px 0; }}
                .kpi-card {{ background: #f5f5f5; padding: 20px; border-radius: 8px;
                             flex: 1; min-width: 200px; }}
                .kpi-value {{ font-size: 2em; font-weight: bold; color: #1976d2; }}
                .footer {{ margin-top: 40px; color: #999; font-size: 0.9em;
                           border-top: 1px solid #e0e0e0; padding-top: 10px; }}
            </style>
        </head>
        <body>
            <h1>{title}</h1>
            <p>Generated: {datetime.utcnow().strftime("%B %d, %Y %H:%M UTC")}</p>
            <p>Report Type: {report_type.value}</p>

            <h2>Cost Overview</h2>
            <p>Multi-subscription Azure cost data — see dashboard for interactive analysis.</p>

            <h2>Optimization Recommendations</h2>
            <p>{"Included" if opt_summary else "Not included in this report"}</p>

            <div class="footer">
                <p>Azure Cost Intelligence & Optimization Portal — Confidential</p>
                <p>This report was auto-generated. Contact ARISTOS-AO-EUGENE-COMM-INFRA@accenture.com for questions.</p>
            </div>
        </body>
        </html>
        """

    def _html_to_pdf(self, html: str) -> bytes:
        """Convert HTML to PDF using WeasyPrint."""
        try:
            from weasyprint import HTML

            return HTML(string=html).write_pdf()
        except ImportError:
            logger.warning("weasyprint_not_available, returning HTML as bytes")
            return html.encode("utf-8")
