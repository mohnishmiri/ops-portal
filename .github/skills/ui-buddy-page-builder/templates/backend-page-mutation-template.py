"""Example backend mutation pattern for UI_Buddy page work.

Use this as a reference when a page introduces a tracked create/update/delete/trigger
operation and the business event needs richer audit detail than request middleware alone.

This is a template asset, not a runtime module.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.auth import UserContext
from app.models.database import AuditLog
from app.schemas.example import ExampleMutationRequest, ExampleMutationResponse
from app.services.example_service import ExampleService

router = APIRouter(prefix="/example-page", tags=["example-page"])


@router.post("/action", response_model=ExampleMutationResponse)
async def run_example_page_action(
    payload: ExampleMutationRequest,
    request: Request,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExampleMutationResponse:
    service = ExampleService(db)

    result = await service.run_action(payload)
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.message,
        )

    audit_entry = AuditLog(
        user_id=current_user.user_id,
        user_email=current_user.email,
        action="example_page_action",
        resource_type="ui_page",
        resource_id=result.resource_id,
        details={
            "page": "ExamplePage",
            "feature": "example-action",
            "payload": payload.model_dump(mode="json"),
            "source": "ui_buddy_page_builder",
        },
        ip_address=request.client.host if request.client else None,
        status="success",
    )
    db.add(audit_entry)
    await db.commit()

    return ExampleMutationResponse.model_validate(result)


"""
Ollama note:

If this page also needs AI summaries or recommendations, keep the LLM call in a backend
service and follow the existing pattern from app.services.leadership_advisor_service.
Do not call the Ollama-compatible endpoint directly from the frontend.
"""