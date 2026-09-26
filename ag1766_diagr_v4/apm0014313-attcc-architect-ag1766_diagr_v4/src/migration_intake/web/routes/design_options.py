"""Isolated, non-destructive application-wide design previews."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/design-options", tags=["design-options"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

SCREEN_GROUPS = (
    (
        "Portfolio",
        (
            ("applications", "Applications"),
            ("application", "Application workspace"),
            ("application-form", "Application form"),
        ),
    ),
    (
        "Intake",
        (
            ("intake", "Intake overview"),
            ("questionnaire", "Questionnaire"),
            ("evidence", "Evidence"),
            ("import", "Import detail"),
            ("review", "Proposal review"),
        ),
    ),
    (
        "Registers",
        (
            ("interfaces", "Interfaces"),
            ("interface-form", "Interface form"),
            ("wave-util", "WaveUtil"),
            ("wave-detail", "WaveUtil detail"),
        ),
    ),
    (
        "Delivery",
        (
            ("readiness", "Readiness"),
            ("snapshot", "Snapshot"),
            ("topology", "Topology"),
            ("topology-run", "Topology run"),
        ),
    ),
    (
        "Administration",
        (
            ("catalog", "Catalog releases"),
            ("catalog-detail", "Catalog detail"),
            ("catalog-upload", "Catalog upload"),
        ),
    ),
)

SCREENS = {key: label for _, screens in SCREEN_GROUPS for key, label in screens}


@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def design_options_root(request: Request) -> HTMLResponse:
    """Render the complete application-wide option comparison."""
    return templates.TemplateResponse(
        request=request,
        name="design_options/index.html",
        context={"screen_groups": SCREEN_GROUPS},
    )


@router.get("/{option}/{screen}", response_class=HTMLResponse)
async def design_option_screen(request: Request, option: str, screen: str) -> HTMLResponse:
    """Render one complete-design preview screen without production writes."""
    if option not in {"a", "b", "c"} or screen not in SCREENS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return templates.TemplateResponse(
        request=request,
        name="design_options/screen.html",
        context={
            "option": option,
            "screen": screen,
            "screen_label": SCREENS[screen],
            "screen_groups": SCREEN_GROUPS,
        },
    )
