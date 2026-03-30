import httpx
from app.config import settings


async def send_resend_email(to: str, subject: str, body: str) -> bool:
    """
    Send an email via Resend API.
    Returns True if successful, False otherwise.
    """
    if not settings.RESEND_API_KEY:
        return False
    
    url = "https://api.resend.com/emails"
    
    headers = {
        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "from": "Travel Scout <onboarding@resend.dev>",
        "to": to,
        "subject": subject,
        "html": f"<p>{body}</p>"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, headers=headers, timeout=10.0)
            return response.status_code in [200, 202]
        except Exception:
            return False


async def send_email_alert(
    to: str,
    origin: str,
    destination: str,
    price: float,
    currency: str,
    depart_date: str,
    airline: str = ""
) -> bool:
    """Send a flight deal alert via email."""
    
    subject = f"✈️ Flight Deal: {origin} → {destination} from {currency} {price:.2f}"
    
    body = f"""
    <h2>Flight Deal Found!</h2>
    <p><strong>From:</strong> {origin}</p>
    <p><strong>To:</strong> {destination}</p>
    {"<p><strong>Airline:</strong> " + airline + "</p>" if airline else ""}
    <p><strong>Price:</strong> {currency} {price:.2f}</p>
    <p><strong>Departure:</strong> {depart_date}</p>
    <p><a href='https://travel-scout.app'>View Details →</a></p>
    """
    
    return await send_resend_email(to, subject, body)