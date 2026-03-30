from uuid import UUID
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User, FlightAlert
from app.models.schemas import FlightAlertResponse, AlertDismiss
from app.routers.auth import get_current_user

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("", response_model=List[FlightAlertResponse])
async def list_alerts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50
):
    result = await db.execute(
        select(FlightAlert)
        .where(FlightAlert.user_id == current_user.id)
        .order_by(FlightAlert.found_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.put("/{alert_id}/dismiss", response_model=FlightAlertResponse)
async def dismiss_alert(
    alert_id: UUID,
    dismiss_data: AlertDismiss,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(FlightAlert).where(
            FlightAlert.id == alert_id,
            FlightAlert.user_id == current_user.id
        )
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found"
        )

    # For now, we just mark it as not notified (hidden)
    # In production, you'd add a dismissed flag
    alert.notified = dismiss_data.dismissed
    await db.commit()
    await db.refresh(alert)
    return alert