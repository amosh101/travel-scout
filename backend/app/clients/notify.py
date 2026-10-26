"""Transactional delivery: email (SMTP) + SMS (Twilio REST).

Hard rule (real-data policy): a missing provider configuration SKIPS
honestly — the channel result says ``skipped_not_configured`` and the
caller logs it. No fake success is ever returned.

Every function returns a status dict so callers (agent payment
confirms, outcome confirms, digests, erasure) can audit per channel.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def _email_configured() -> bool:
    s = get_settings()
    return bool(s.smtp_host and s.smtp_from)


def _sms_configured() -> bool:
    s = get_settings()
    return bool(s.twilio_account_sid and s.twilio_auth_token and s.twilio_from)


def send_email(to: str, subject: str, body: str) -> str:
    """Send a plain-text email. Returns a status string, never raises."""
    if not to or "@" not in to:
        return "skipped_no_address"
    if not _email_configured():
        logger.info("email skipped (not configured): to=%s subject=%r", to, subject)
        return "skipped_not_configured"
    s = get_settings()
    try:
        msg = EmailMessage()
        msg["From"] = s.smtp_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            if s.smtp_use_tls:
                smtp.starttls()
            if s.smtp_user and s.smtp_password:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
        return "sent"
    except Exception as e:  # noqa: BLE001 — delivery must never crash a request
        logger.warning("email send failed to %s: %s", to, e)
        return f"failed:{type(e).__name__}"


def send_sms(to: str, body: str) -> str:
    """Send an SMS via Twilio REST (global). Status string, never raises."""
    if not to or to.strip() in {"", "+0"}:
        return "skipped_no_number"
    if not _sms_configured():
        logger.info("sms skipped (not configured): to=%s body=%r", to[-4:] if to else None, body[:40])
        return "skipped_not_configured"
    s = get_settings()
    try:
        r = httpx.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_account_sid}/Messages.json",
            data={"To": to, "From": s.twilio_from, "Body": body},
            auth=(s.twilio_account_sid, s.twilio_auth_token),
            timeout=15,
        )
        if r.status_code in (200, 201):
            return "sent"
        logger.warning("sms send failed: %s %s", r.status_code, r.text[:120])
        return f"failed:http_{r.status_code}"
    except Exception as e:  # noqa: BLE001
        logger.warning("sms send failed to %s: %s", to[-4:] if to else None, e)
        return f"failed:{type(e).__name__}"


# -----------------------------------------------------------------------------
# Product-level notifications (templates + fan-out)
# -----------------------------------------------------------------------------


def notify_payment_received(
    *, user_email: str, user_phone: str | None, itinerary_title: str,
    amount_cents: int, currency: str, agent_note: str | None,
) -> dict[str, str]:
    """Customer paid the agent (off-platform); the app confirms to the
    customer across channels."""
    amount = f"{amount_cents / 100:.2f} {currency}"
    body = (
        f"Payment received for {itinerary_title}.\n\n"
        f"Amount: {amount}\n"
        + (f"Note from your booking agent: {agent_note}\n" if agent_note else "")
        + "\nYour booking agent is now completing the reservations. "
        "Tickets and vouchers will arrive in your chat and here by email."
    )
    email_status = send_email(user_email, "Travel Scout — payment received", body)
    # Short, carrier-safe SMS
    sms_status = (
        f"Travel Scout: payment received for {itinerary_title} ({amount}). "
        "Your agent is completing your reservations."
    )
    sms_result = send_sms(user_phone or "", sms_status)
    logger.info("payment_received notification: %s -> email=%s sms=%s",
                user_email, email_status, sms_result)
    return {"email": email_status, "sms": sms_result}


def notify_booking_outcome(
    *, user_email: str, user_phone: str | None, itinerary_title: str,
    confirmed: bool, external_id: str | None, summary_body: str | None,
) -> dict[str, str]:
    """Agent completed (or failed) the booking; the customer gets the
    full confirmation (chat already carries the summary card)."""
    if confirmed:
        subject = "Travel Scout — booking confirmed"
        refs = f"Reference: {external_id}\n" if external_id else ""
        body = f"Your booking for {itinerary_title} is CONFIRMED.\n{refs}\n{summary_body or ''}"
    else:
        subject = "Travel Scout — booking update"
        body = f"Your booking for {itinerary_title} was not completed. Reply in chat and we will find alternatives."
    email_status = send_email(user_email, subject, body)
    sms_result = send_sms(
        user_phone or "",
        ("Travel Scout: BOOKING CONFIRMED for " + itinerary_title +
         (f" (ref {external_id})" if external_id else "") + ". Details in your chat.")
        if confirmed
        else "Travel Scout: your booking could not be completed. See chat for alternatives.",
    )
    logger.info("outcome notification: %s confirmed=%s email=%s sms=%s",
                user_email, confirmed, email_status, sms_result)
    return {"email": email_status, "sms": sms_result}


def notify_digest(*, user_email: str, items: list[dict]) -> dict[str, str]:
    """Weekly digest email (in-app copy is the Digest row itself)."""
    lines = ["Your week in trips:\n"]
    for it in items:
        lines.append(
            f"- {it.get('title')}: {it.get('destination')} · "
            f"{it.get('start')} → {it.get('end')} · {it.get('why')}"
        )
    lines.append(
        "\nOpen Travel Scout to save a trip or hand it to your booking agent."
    )
    email_status = send_email(user_email, "Travel Scout — your weekly trips", "\n".join(lines))
    return {"email": email_status}