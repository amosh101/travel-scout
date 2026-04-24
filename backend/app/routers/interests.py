from uuid import UUID
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User, Interest
from app.models.schemas import InterestCreate, InterestUpdate, InterestResponse
from app.routers.auth import get_current_user

router = APIRouter(prefix="/api/interests", tags=["interests"])


@router.get("", response_model=List[InterestResponse])
async def list_interests(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Interest).where(Interest.user_id == current_user.id)
    )
    return result.scalars().all()


@router.post("", response_model=InterestResponse, status_code=status.HTTP_201_CREATED)
async def create_interest(
    interest_data: InterestCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    from datetime import date
    
    interest = Interest(
        user_id=current_user.id,
        name=interest_data.name,
        origin_airport=interest_data.origin_airport,
        destination_region=interest_data.destination_region,
        event_keywords=interest_data.event_keywords,
        max_budget=interest_data.max_budget,
        notification_channels=interest_data.notification_channels,
        active=interest_data.active,
        date_flexibility=interest_data.date_flexibility,
        preferred_departure_date=date.fromisoformat(interest_data.preferred_departure_date) if interest_data.preferred_departure_date else None,
        preferred_return_date=date.fromisoformat(interest_data.preferred_return_date) if interest_data.preferred_return_date else None,
    )
    db.add(interest)
    await db.commit()
    await db.refresh(interest)
    return interest


@router.put("/{interest_id}", response_model=InterestResponse)
async def update_interest(
    interest_id: UUID,
    interest_data: InterestUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Interest).where(
            Interest.id == interest_id,
            Interest.user_id == current_user.id
        )
    )
    interest = result.scalar_one_or_none()
    if not interest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Interest not found"
        )

    # Update fields
    update_data = interest_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(interest, field, value)

    await db.commit()
    await db.refresh(interest)
    return interest


@router.delete("/{interest_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_interest(
    interest_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Interest).where(
            Interest.id == interest_id,
            Interest.user_id == current_user.id
        )
    )
    interest = result.scalar_one_or_none()
    if not interest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Interest not found"
        )

    await db.delete(interest)
    await db.commit()