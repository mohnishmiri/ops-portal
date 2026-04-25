"""
Checksum Schedule Management Routes

Endpoints for creating, retrieving, updating, and managing checksum schedules
for both Synapse and AKS environments.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.core.database import get_db_session
from app.models.auth import UserContext
from app.schemas.checksum_schedules import (
    ChecksumScheduleCreateRequest,
    ChecksumScheduleDetail,
    ChecksumScheduleListResponse,
    ChecksumScheduleResponse,
)
from app.services.compliance_service import (
    get_compliance_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["checksum-schedules"])


@router.post(
    "/",
    response_model=ChecksumScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Checksum Schedule",
    description="Create a new checksum schedule for Synapse or AKS environments",
)
async def create_checksum_schedule(
    request: ChecksumScheduleCreateRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """
    Create a new checksum schedule.

    Parameters:
    - **name**: Unique schedule name
    - **module_type**: Either 'synapse' or 'aks'
    - **schedule_type**: Either 'interval' or 'cron'
    - **interval_hours**: Hours between runs (for interval-based)
    - **cron_expression**: Cron expression (for cron-based)
    - **timezone**: Timezone for schedule
    - **is_enabled**: Whether schedule is active

    Returns:
    - Schedule ID and confirmation message
    """
    try:
        compliance_service = get_compliance_service(db)
        payload = request.model_dump()

        result = await compliance_service.create_checksum_schedule(
            payload=payload,
            created_by=user.email or user.display_name,
        )

        logger.info(
            "checksum_schedule_created_via_api: name=%s module_type=%s",
            request.name,
            request.module_type,
        )

        return {
            "success": True,
            "schedule_id": str(result.get("id", "")),
            "name": result.get("name"),
            "message": "Schedule created successfully",
        }

    except ValueError as e:
        logger.warning(f"Validation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Create schedule failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create checksum schedule",
        )


@router.get(
    "/",
    response_model=ChecksumScheduleListResponse,
    summary="List Checksum Schedules",
    description="Retrieve all checksum schedules",
)
async def list_checksum_schedules(
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """
    List all checksum schedules.

    Returns:
    - List of all schedules with details
    """
    try:
        compliance_service = get_compliance_service(db)
        schedules = await compliance_service.list_checksum_schedules()

        return {
            "success": True,
            "count": len(schedules),
            "schedules": schedules,
        }

    except Exception as e:
        logger.error(f"List schedules failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve checksum schedules",
        )


@router.get(
    "/{schedule_id}",
    response_model=ChecksumScheduleDetail,
    summary="Get Checksum Schedule",
    description="Retrieve a specific checksum schedule",
)
async def get_checksum_schedule(
    schedule_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """
    Get a specific checksum schedule.

    Parameters:
    - **schedule_id**: Schedule ID

    Returns:
    - Schedule details including next run time
    """
    try:
        compliance_service = get_compliance_service(db)
        schedule = await compliance_service.get_checksum_schedule(schedule_id)

        if not schedule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Schedule '{schedule_id}' not found",
            )

        return schedule

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get schedule failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve checksum schedule",
        )


@router.patch(
    "/{schedule_id}",
    summary="Update Checksum Schedule",
    description="Update a checksum schedule",
)
async def update_checksum_schedule(
    schedule_id: int,
    request: ChecksumScheduleCreateRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """
    Update a checksum schedule.

    Parameters:
    - **schedule_id**: Schedule ID
    - **request**: Updated schedule details

    Returns:
    - Updated schedule confirmation
    """
    try:
        compliance_service = get_compliance_service(db)

        payload = request.model_dump(exclude_unset=True)
        payload["updated_by"] = user.email or user.display_name

        result = await compliance_service.update_checksum_schedule(
            schedule_id=schedule_id,
            payload=payload,
        )

        logger.info(
            "checksum_schedule_updated_via_api: schedule_id=%s module_type=%s",
            schedule_id,
            request.module_type,
        )

        return {
            "success": True,
            "schedule_id": str(schedule_id),
            "name": result.get("name"),
            "message": "Schedule updated successfully",
        }

    except ValueError as e:
        logger.warning(f"Validation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Update schedule failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update checksum schedule",
        )


@router.delete(
    "/{schedule_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete Checksum Schedule",
    description="Delete a checksum schedule",
)
async def delete_checksum_schedule(
    schedule_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """
    Delete a checksum schedule.

    Parameters:
    - **schedule_id**: Schedule ID

    Returns:
    - Deletion confirmation
    """
    try:
        compliance_service = get_compliance_service(db)

        result = await compliance_service.delete_checksum_schedule(
            schedule_id=schedule_id,
            deleted_by=user.email or user.display_name,
        )

        logger.info(
            "checksum_schedule_deleted_via_api: schedule_id=%s",
            schedule_id,
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete schedule failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete checksum schedule",
        )


@router.patch(
    "/{schedule_id}/toggle",
    status_code=status.HTTP_200_OK,
    summary="Toggle Schedule Enabled/Disabled",
    description="Toggle a checksum schedule's enabled state",
)
async def toggle_checksum_schedule(
    schedule_id: int,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Toggle a schedule between enabled and disabled."""
    try:
        compliance_service = get_compliance_service(db)
        result = await compliance_service.toggle_checksum_schedule(
            schedule_id=schedule_id,
            toggled_by=user.email or user.display_name,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Toggle schedule failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to toggle schedule",
        )


@router.post(
    "/{schedule_id}/test",
    status_code=status.HTTP_200_OK,
    summary="Test Checksum Schedule",
    description="Run a test execution of a checksum schedule",
)
async def test_checksum_schedule(
    schedule_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """
    Run a test execution of a checksum schedule.

    Parameters:
    - **schedule_id**: Schedule ID

    Returns:
    - Test execution result
    """
    try:
        compliance_service = get_compliance_service(db)

        result = await compliance_service.test_checksum_schedule(
            schedule_id=schedule_id,
            executed_by=user.email or user.display_name,
        )

        logger.info(
            "checksum_schedule_tested_via_api: schedule_id=%s",
            schedule_id,
        )

        return result

    except ValueError as e:
        logger.warning(f"Test failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Test schedule failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to test checksum schedule",
        )
