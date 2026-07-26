"""Chat-thread API for the booking-agent feature (T8e-booking-agent).

Three surfaces, all under ``/api/messages``:

1. **User-facing**:
   - ``POST /api/messages``           — user posts a message in the thread
                                         for their own itinerary.
   - ``GET  /api/messages``           — user reads their own thread.

2. **Agent-facing** (gated by ``agent.work`` permission):
   - Same ``POST /api/messages`` route — when the caller has ``agent.work``,
     the role is forced to ``agent`` regardless of what the body says.
   - ``POST /api/messages/attachments`` — multipart upload; returns the
     new attachment row (caller then posts a message referencing it).

3. **Attachment download** (gated by ownership/perm):
   - ``GET /api/messages/attachments/{id}`` — streams the file payload.

Tier guards:
- ``POST /api/messages`` requires ``user.tier == 'concierge'``. Free-tier
  users get a 403 with the message "this feature requires a concierge
  subscription; outbound booking link is on the itinerary detail page."
- The agent-side path is the same route, but the auth dependency is
  swapped for ``require_permission('agent.work')`` in a small router
  overlay (see ``agent_messages_router`` below). Both share the same
  handler logic.

Booking summary (2026-07-24):
When the agent confirms a booking via ``POST /api/agent/queue/{id}/outcome``,
they're meant to include enough info that the user can act on it. To
make this easy we generate an ``is_summary=True`` message on confirm
that contains dates, passport/visa checklist, and the agent's notes —
the user sees it as the "what you need to know" card on their itinerary.
The summary is built by ``build_booking_summary()`` and posted via
``post_booking_summary()`` in this module.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session
from app.models import (
    ActorKind,
    AuditLog,
    BookingsLog,
    Message,
    MessageAttachment,
    MessageSenderRole,
    SavedItinerary,
    SubscriptionTier,
    User,
)
from app.routers.auth import get_current_user
from app.schemas.messages import (
    AttachmentOut,
    HandOffBrief,
    MessageList,
    MessageOut,
    PostMessageIn,
)
from app.services.authz import write_audit_log

router = APIRouter(prefix="/messages", tags=["messages"])

# Settings is read fresh on each request (via get_settings()) so the
# env-driven values (media_root, media_max_bytes) reflect the running
# config without module-level caching.
def _settings():
    from app.config import get_settings
    return get_settings()

# -- Attachment allowlist (MIME types) ----------------------------------------
ALLOWED_MIME_TYPES = frozenset({
    "image/png",
    "image/jpeg",
    "image/webp",
    "application/pdf",
    "text/plain",
})

# Filename sanitiser — strips path separators + null bytes. Keep ASCII +
# common international chars; clamp length.
_FILENAME_BAD = re.compile(r"[^\w.\-]+", re.UNICODE)


def _sanitise_filename(name: str) -> str:
    """Strip path traversal + control chars from an upload filename.

    Rules:
      - Keep basename only (no slashes, no '..')
      - Replace whitespace + control with underscore
      - Clamp to 200 chars
      - Fall back to 'attachment' if empty
    """
    base = os.path.basename(name or "").strip()
    base = _FILENAME_BAD.sub("_", base).strip("._")
    base = base[:200] if base else "attachment"
    return base or "attachment"


# -- Tier guard ---------------------------------------------------------------


async def _require_concierge_or_agent(
    session: AsyncSession, user: User
) -> None:
    """Allow if user is concierge tier OR has the ``agent.work`` perm.

    The user-side POST handler uses this so a single endpoint serves both
    flows. Free-tier users without ``agent.work`` get 403.
    """
    if user.tier == SubscriptionTier.CONCIERGE:
        return
    # Agent path: user has the agent.work permission
    from app.services.authz import user_has_permission
    if await user_has_permission(session, user.id, "agent.work"):
        return
    raise HTTPException(
        status_code=403,
        detail=(
            "this feature requires a concierge subscription or agent "
            "permission; the outbound booking link is on the itinerary detail page"
        ),
    )


def _resolve_sender_role(user: User, session: AsyncSession) -> MessageSenderRole:
    """Pick the right sender_role for an outgoing message.

    NB: the real handler uses the async variant ``_resolve_sender_role_async``
    because the perm lookup is async. This sync stub exists only to keep
    the module surface tidy; do not call directly.
    """
    raise NotImplementedError(
        "use _resolve_sender_role_async (perm lookup is async)"
    )


async def _resolve_sender_role_async(
    session: AsyncSession, user: User, body: PostMessageIn
) -> MessageSenderRole:
    """Async resolution: agent perm wins; otherwise user.

    The body may include ``sender_role`` in theory but v1 does NOT honour
    it — the role is computed from the auth context. (A user can't
    impersonate an agent by setting sender_role='agent' in the body.)
    """
    from app.services.authz import user_has_permission
    if await user_has_permission(session, user.id, "agent.work"):
        return MessageSenderRole.AGENT
    return MessageSenderRole.USER


# -- Ownership check ----------------------------------------------------------


async def _ensure_itinerary_visible(
    session: AsyncSession, user: User, itinerary_id: UUID
) -> SavedItinerary:
    """Return the itinerary if user can read its thread.

    Rules:
      - User can read if they own the itinerary.
      - Agent can read if they have agent.work (any itinerary).
    Raises 404 if not found / not visible.
    """
    from app.services.authz import user_has_permission
    is_agent = await user_has_permission(session, user.id, "agent.work")

    stmt = select(SavedItinerary).where(SavedItinerary.id == itinerary_id)
    if not is_agent:
        stmt = stmt.where(SavedItinerary.user_id == user.id)
    saved = (await session.execute(stmt)).scalar_one_or_none()
    if saved is None:
        raise HTTPException(status_code=404, detail="itinerary not found")
    return saved


# -- Hand-off brief (agent-only convenience) ----------------------------------


@router.get("/hand-off/{itinerary_id}", response_model=HandOffBrief)
async def get_hand_off_brief(
    itinerary_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Agent-only: short brief to start the booking conversation.

    Returns the user identity + travel-doc fields + itinerary summary
    so the agent has everything they need before they message the user
    off-platform.
    """
    from app.services.authz import require_permission
    # Re-raise 403 if not agent
    await require_permission("agent.work")(  # type: ignore[misc]
        session=session, user=user
    )

    saved = (await session.execute(
        select(SavedItinerary).where(SavedItinerary.id == itinerary_id)
    )).scalar_one_or_none()
    if saved is None:
        raise HTTPException(status_code=404, detail="itinerary not found")

    owner = (await session.execute(
        select(User).where(User.id == saved.user_id)
    )).scalar_one_or_none()

    booking = (await session.execute(
        select(BookingsLog).where(
            BookingsLog.itinerary_id == saved.id,
            BookingsLog.user_id == saved.user_id,
        ).order_by(BookingsLog.created_at.desc()).limit(1)
    )).scalar_one_or_none()

    payload = saved.payload or {}
    return HandOffBrief(
        itinerary_id=saved.id,
        user_email=owner.email if owner else "",
        user_name=owner.name if owner else "",
        user_nationality=owner.nationality if owner else None,
        user_passport_expiry=owner.passport_expiry if owner else None,
        user_dob=owner.date_of_birth if owner else None,
        itinerary_title=saved.title,
        itinerary_starts_at=saved.starts_at,
        itinerary_ends_at=saved.ends_at,
        itinerary_destination=payload.get("destination_name"),
        hand_off_note=(
            (booking.metadata_json or {}).get("summary", {}).get("user_note")
            if booking else None
        ),
        booking_status=booking.status if booking else "pending",
        booking_id=booking.id if booking else None,
    )


# -- POST /api/messages -------------------------------------------------------


@router.post("", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def post_message(
    body: PostMessageIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Post a message in the itinerary thread.

    - User-side: requires concierge tier; sender_role=user.
    - Agent-side: requires ``agent.work`` perm; sender_role=agent; can
      optionally set ``is_summary=True`` with the structured fields to
      render the booking-summary card on the user side.

    The booking summary fields (``is_summary`` + the structured
    ``summary_*`` fields) are advisory for the message body and are
    also stored in the audit log so the agent dashboard can replay them.
    """
    # Concierge-or-agent gate
    await _require_concierge_or_agent(session, user)

    saved = await _ensure_itinerary_visible(session, user, body.itinerary_id)
    sender_role = await _resolve_sender_role_async(session, user, body)

    msg = Message(
        itinerary_id=saved.id,
        sender_user_id=user.id,
        sender_role=sender_role,
        body=body.body,
        is_summary=bool(body.is_summary),
    )
    session.add(msg)
    await session.flush()

    # Audit log — include summary fields if set so the agent dashboard
    # can replay them.
    audit_meta: dict = {"sender_role": sender_role.value}
    if body.is_summary:
        audit_meta["is_summary"] = True
        audit_meta["summary"] = {
            "start_date": (
                body.summary_start_date.isoformat()
                if body.summary_start_date else None
            ),
            "end_date": (
                body.summary_end_date.isoformat()
                if body.summary_end_date else None
            ),
            "destination": body.summary_destination,
            "passport_required": body.summary_passport_required,
            "visa_required": body.summary_visa_required,
            "visa_status": body.summary_visa_status,
            "notes": body.summary_notes,
        }
    await write_audit_log(
        session,
        actor_user_id=user.id,
        action="message.post",
        target_kind="messages",
        target_id=str(msg.id),
        metadata=audit_meta,
        actor_kind=(
            ActorKind.AGENT if sender_role == MessageSenderRole.AGENT
            else ActorKind.USER
        ),
    )
    await session.commit()
    await session.refresh(msg)

    return _msg_to_out(msg, attachments=[])


# -- GET /api/messages -------------------------------------------------------


@router.get("", response_model=MessageList)
async def list_messages(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
    itinerary_id: UUID = Query(...),
    since: Optional[datetime] = Query(
        default=None,
        description="ISO datetime; only return messages with created_at > since",
    ),
    limit: int = Query(default=200, ge=1, le=500),
):
    """Return messages for an itinerary, oldest first.

    User can read their own threads; agent can read any thread.
    """
    await _ensure_itinerary_visible(session, user, itinerary_id)

    stmt = select(Message).where(Message.itinerary_id == itinerary_id)
    if since is not None:
        stmt = stmt.where(Message.created_at > since)
    stmt = stmt.order_by(Message.created_at.asc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()

    # Fetch attachments in one query (avoid N+1)
    if rows:
        ids = [r.id for r in rows]
        att_rows = (await session.execute(
            select(MessageAttachment).where(MessageAttachment.message_id.in_(ids))
        )).scalars().all()
        by_msg: dict[UUID, list[MessageAttachment]] = {}
        for a in att_rows:
            by_msg.setdefault(a.message_id, []).append(a)
    else:
        by_msg = {}

    items = [
        _msg_to_out(r, attachments=by_msg.get(r.id, []))
        for r in rows
    ]
    return MessageList(itinerary_id=itinerary_id, total=len(items), items=items)


# -- Attachment upload (multipart) -------------------------------------------


def _attachment_storage_path(root: Path, message_id: UUID, sha_hex: str, ext: str) -> Path:
    """Build the on-disk path for an attachment payload.

    Layout: ``<root>/<yyyy>/<mm>/<message_id>-<sha8>.<ext>``.
    Sharded by year-month to keep directory listings manageable.
    """
    now = datetime.now(timezone.utc)
    month_dir = root / f"{now.year:04d}" / f"{now.month:02d}"
    month_dir.mkdir(parents=True, exist_ok=True)
    return month_dir / f"{message_id}-{sha_hex[:8]}{ext}"


@router.post(
    "/attachments",
    response_model=AttachmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
    message_id: UUID = Form(...),
    kind: Optional[str] = Form(default=None, max_length=64),
    file: UploadFile = File(...),
):
    """Upload a file attachment for an existing message.

    The message must already exist (you can't attach to a thread before
    posting the introductory message). The route enforces:
      - Concierge-or-agent auth (same as POST /messages)
      - The message belongs to a thread the caller can read
      - MIME type is on the allowlist
      - File size is under ``settings.media_max_bytes``
    The file payload is streamed to disk under ``settings.media_root``;
    only the reference + hash + filename + size live in the DB.
    """
    await _require_concierge_or_agent(session, user)

    # Validate MIME early — before we read the body
    mime = (file.content_type or "").lower()
    if mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"unsupported file type {mime!r}; allowed: "
                f"{', '.join(sorted(ALLOWED_MIME_TYPES))}"
            ),
        )

    # Look up the message + check ownership
    msg = (await session.execute(
        select(Message).where(Message.id == message_id)
    )).scalar_one_or_none()
    if msg is None:
        raise HTTPException(status_code=404, detail="message not found")
    await _ensure_itinerary_visible(session, user, msg.itinerary_id)

    # Stream the upload to disk, enforcing the size cap
    safe_name = _sanitise_filename(file.filename or "attachment")
    ext = os.path.splitext(safe_name)[1].lower()[:16] or _ext_for_mime(mime)
    root = Path(_settings().media_root)
    root.mkdir(parents=True, exist_ok=True)
    placeholder = root / f".tmp-{secrets.token_hex(8)}"
    sha = hashlib.sha256()
    bytes_written = 0
    try:
        with placeholder.open("wb") as out:
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > _settings().media_max_bytes:
                    out.close()
                    placeholder.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"file exceeds max size "
                            f"{_settings().media_max_bytes} bytes"
                        ),
                    )
                sha.update(chunk)
                out.write(chunk)
        sha_hex = sha.hexdigest()
        final_path = _attachment_storage_path(root, msg.id, sha_hex, ext)
        # If a file with the same hash already exists (dedup), reuse it.
        if final_path.exists():
            placeholder.unlink(missing_ok=True)
        else:
            placeholder.rename(final_path)
    except HTTPException:
        raise
    except Exception as e:
        placeholder.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"upload failed: {e!s}") from e
    finally:
        await file.close()

    row = MessageAttachment(
        message_id=msg.id,
        filename=safe_name,
        mime_type=mime,
        size_bytes=bytes_written,
        sha256=sha_hex,
        storage_path=str(final_path),
        kind=kind,
    )
    session.add(row)
    await session.flush()
    await write_audit_log(
        session,
        actor_user_id=user.id,
        action="message.attachment.upload",
        target_kind="message_attachments",
        target_id=str(row.id),
        metadata={
            "message_id": str(msg.id),
            "mime_type": mime,
            "size_bytes": bytes_written,
            "kind": kind,
            "sha256": sha_hex,
        },
        actor_kind=(
            ActorKind.AGENT
            if (await _is_agent(session, user))
            else ActorKind.USER
        ),
    )
    await session.commit()
    await session.refresh(row)
    return _attachment_to_out(row)


def _ext_for_mime(mime: str) -> str:
    """Fallback extension when the upload filename has no extension."""
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
        "text/plain": ".txt",
    }.get(mime, ".bin")


async def _is_agent(session: AsyncSession, user: User) -> bool:
    from app.services.authz import user_has_permission
    return await user_has_permission(session, user.id, "agent.work")


# -- Attachment download ------------------------------------------------------


@router.get("/attachments/{attachment_id}")
async def download_attachment(
    attachment_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Stream the file payload for an attachment.

    Auth: the caller must have read access to the parent message's
    thread (owner or agent).
    """
    att = (await session.execute(
        select(MessageAttachment).where(MessageAttachment.id == attachment_id)
    )).scalar_one_or_none()
    if att is None:
        raise HTTPException(status_code=404, detail="attachment not found")

    msg = (await session.execute(
        select(Message).where(Message.id == att.message_id)
    )).scalar_one_or_none()
    if msg is None:
        raise HTTPException(status_code=404, detail="message not found")
    await _ensure_itinerary_visible(session, user, msg.itinerary_id)

    path = Path(att.storage_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="attachment payload missing")
    return FileResponse(
        path=str(path),
        media_type=att.mime_type,
        filename=att.filename,
    )


# -- Booking-summary builder --------------------------------------------------


def build_booking_summary(
    *,
    booking: BookingsLog,
    saved: SavedItinerary,
    user: User,
    outcome_note: Optional[str],
    amount_cents: Optional[int],
    currency: Optional[str],
    external_id: Optional[str],
) -> tuple[str, dict]:
    """Build the (body, audit_meta) pair for a confirm-outcome summary.

    The body is the human-readable text the user sees in the chat
    thread. The audit_meta carries the structured fields so the agent
    dashboard can replay them. The same body is also written to the
    BookingsLog row's metadata_json for fast agent-side rendering.
    """
    payload = saved.payload or {}
    dest = payload.get("destination_name") or "your destination"
    starts = saved.starts_at
    ends = saved.ends_at

    amount_line = ""
    if amount_cents and amount_cents > 0:
        ccy = (currency or "USD").upper()
        amount_line = (
            f"•  Total: **{amount_cents/100:,.2f} {ccy}**\n"
        )
    ref_line = ""
    if external_id:
        ref_line = f"•  Reference: `{external_id}`\n"

    date_line = ""
    if starts and ends:
        date_line = f"•  Dates: *{starts.strftime('%Y-%m-%d')}* → *{ends.strftime('%Y-%m-%d')}*\n"

    # Visa / passport reminder — pulled from user.tier + their travel-doc
    # fields if present.
    passport_line = ""
    if user.passport_expiry:
        days_left = (user.passport_expiry - datetime.now(timezone.utc).date()).days
        if days_left < 180:
            passport_line = (
                f"⚠️  Your passport expires in {days_left} days — "
                f"many countries require 6 months' validity. Renew before travel.\n"
            )
    visa_line = (
        "🛂  Check visa requirements for your nationality + destination; "
        "MZ visa-free for many African + SADC passports.\n"
    )

    body = (
        f"✅ *Booking confirmed — {dest}*\n\n"
        f"{date_line}"
        f"{amount_line}"
        f"{ref_line}"
        f"\n"
        f"{passport_line}"
        f"{visa_line}"
        f"\n"
        f"*What's next:*\n"
        f"•  Save your passport + visa copies here (use the attachment button).\n"
        f"•  Arrive at the airport 3h before departure for international flights.\n"
        f"•  Local emergency number in MZ: *119* (police) / *117* (ambulance).\n"
        f"\n"
        f"_Agent note:_ {outcome_note or '—'}\n"
    )

    audit_meta = {
        "summary_kind": "booking_confirmed",
        "destination": dest,
        "starts_at": starts.isoformat() if starts else None,
        "ends_at": ends.isoformat() if ends else None,
        "amount_cents": amount_cents,
        "currency": currency,
        "external_id": external_id,
        "passport_expiry": (
            user.passport_expiry.isoformat() if user.passport_expiry else None
        ),
    }
    return body, audit_meta


# -- Serialisers --------------------------------------------------------------


def _msg_to_out(m: Message, *, attachments: list[MessageAttachment]) -> MessageOut:
    return MessageOut(
        id=m.id,
        itinerary_id=m.itinerary_id,
        sender_user_id=m.sender_user_id,
        sender_role=m.sender_role.value if hasattr(m.sender_role, "value") else str(m.sender_role),
        body=m.body,
        is_summary=m.is_summary,
        booking_id=m.booking_id,
        created_at=m.created_at,
        attachments=[_attachment_to_out(a) for a in attachments],
    )


def _attachment_to_out(a: MessageAttachment) -> AttachmentOut:
    return AttachmentOut(
        id=a.id,
        filename=a.filename,
        mime_type=a.mime_type,
        size_bytes=a.size_bytes,
        kind=a.kind,
        download_url=f"/api/messages/attachments/{a.id}",
        created_at=a.created_at,
    )


__all__ = ["router", "build_booking_summary"]