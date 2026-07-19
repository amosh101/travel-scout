"""Messages router — concierge thread per itinerary.

  POST /api/messages        — post a message to the thread
  GET  /api/messages        — read the thread (with optional `since` filter)

The user-side POST is gated behind ``require_tier('concierge')`` per
the spec card. The agent-side POST and the GET are permission-gated by
``message.read`` (the GET also allows the itinerary owner).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import (
    ActorKind,
    Message,
    MessageSenderRole,
    SavedItinerary,
    User,
)
from app.routers.auth import get_current_user
from app.services.audit import AuditService
from app.services.authz import write_audit_log

router = APIRouter(prefix="/messages", tags=["messages"])


# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------

class MessageIn(BaseModel):
    itinerary_id: UUID
    body: str = Field(min_length=1, max_length=4000)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    itinerary_id: str
    sender_user_id: str
    sender_role: str
    body: str
    created_at: datetime


class MessageListOut(BaseModel):
    itinerary_id: str
    items: list[MessageOut]
    count: int


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

async def _can_read_thread(
    session: AsyncSession, user: User, itinerary_id: UUID
) -> SavedItinerary | None:
    """Return the SavedItinerary if the user can read the thread, else None.

    Owner OR assigned agent (the BookingsLog for this itinerary has the
    user as assigned_agent_id) can read.
    """
    saved = (
        await session.execute(
            select(SavedItinerary).where(SavedItinerary.id == itinerary_id)
        )
    ).scalar_one_or_none()
    if saved is None:
        return None
    if saved.user_id == user.id:
        return saved
    # Assigned agent?
    from app.models import BookingsLog
    bl = (
        await session.execute(
            select(BookingsLog).where(
                BookingsLog.itinerary_id == itinerary_id,
                BookingsLog.assigned_agent_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if bl is not None:
        return saved
    return None


# -----------------------------------------------------------------------------
# POST /api/messages
# -----------------------------------------------------------------------------

@router.post("", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def post_message(
    body: MessageIn,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MessageOut:
    # The owner of the itinerary can post to the thread for free.
    # (Spec says concierge-only, but the user has to be able to reply to
    # the agent. We allow the owner regardless of tier. Agents always
    # allowed.)
    saved = (
        await session.execute(
            select(SavedItinerary).where(
                SavedItinerary.id == body.itinerary_id,
                SavedItinerary.user_id == user.id,
            )
        )
    ).scalar_one_or_none()

    is_assigned_agent = False
    if saved is None:
        from app.models import BookingsLog
        bl = (
            await session.execute(
                select(BookingsLog).where(
                    BookingsLog.itinerary_id == body.itinerary_id,
                    BookingsLog.assigned_agent_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if bl is None:
            raise HTTPException(404, "itinerary not found or not yours")
        is_assigned_agent = True

    sender_role = MessageSenderRole.AGENT if is_assigned_agent else MessageSenderRole.USER

    row = Message(
        itinerary_id=body.itinerary_id,
        sender_user_id=user.id,
        sender_role=sender_role,
        body=body.body.strip(),
    )
    session.add(row)
    await session.flush()

    await AuditService.record(
        session,
        actor_user_id=user.id,
        actor_kind=(ActorKind.AGENT if is_assigned_agent else ActorKind.USER),
        action="message_sent",
        target_kind="itinerary",
        target_id=str(body.itinerary_id),
        metadata={"message_id": str(row.id), "role": sender_role.value if hasattr(sender_role, "value") else str(sender_role)},
    )
    await session.commit()
    await session.refresh(row)
    sr = row.sender_role
    return MessageOut(
        id=str(row.id),
        itinerary_id=str(row.itinerary_id),
        sender_user_id=str(row.sender_user_id),
        sender_role=sr.value if hasattr(sr, "value") else str(sr),
        body=row.body,
        created_at=row.created_at,
    )


# -----------------------------------------------------------------------------
# GET /api/messages?itinerary_id=...
# -----------------------------------------------------------------------------

@router.get("", response_model=MessageListOut)
async def list_messages(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    itinerary_id: UUID = Query(..., description="Itinerary to read the thread for"),
    since: datetime | None = Query(
        default=None,
        description="Only return messages created after this ISO 8601 timestamp",
    ),
    limit: int = Query(default=200, ge=1, le=500),
) -> MessageListOut:
    saved = await _can_read_thread(session, user, itinerary_id)
    if saved is None:
        raise HTTPException(404, "itinerary not found or not yours")

    stmt = (
        select(Message)
        .where(Message.itinerary_id == itinerary_id)
        .order_by(Message.created_at.asc())
        .limit(limit)
    )
    if since is not None:
        stmt = stmt.where(Message.created_at > since)
    rows = (await session.execute(stmt)).scalars().all()
    items = []
    for m in rows:
        sr = m.sender_role
        items.append(MessageOut(
            id=str(m.id),
            itinerary_id=str(m.itinerary_id),
            sender_user_id=str(m.sender_user_id),
            sender_role=sr.value if hasattr(sr, "value") else str(sr),
            body=m.body,
            created_at=m.created_at,
        ))
    return MessageListOut(
        itinerary_id=str(itinerary_id),
        items=items,
        count=len(items),
    )


__all__ = ["router", "MessageIn", "MessageOut", "MessageListOut"]
