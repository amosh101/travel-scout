import httpx
from app.config import settings


async def send_telegram_message(chat_id: str, message: str) -> bool:
    """
    Send a message via Telegram Bot API.
    Returns True if successful, False otherwise.
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        return False
    
    url = f"{settings.TELEGRAM_API_URL}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, timeout=10.0)
            return response.status_code == 200
        except Exception:
            return False


async def send_telegram_alert(
    chat_id: str,
    origin: str,
    destination: str,
    price: float,
    currency: str,
    depart_date: str,
    airline: str = ""
) -> bool:
    """Send a flight deal alert via Telegram."""
    
    message = f"✈️ <b>Flight Deal Found!</b>\n\n"
    message += f"🏠 <b>From:</b> {origin}\n"
    message += f"🏝️ <b>To:</b> {destination}\n"
    if airline:
        message += f"🛫 <b>Airline:</b> {airline}\n"
    message += f"💰 <b>Price:</b> {currency} {price:.2f}\n"
    message += f"📅 <b>Departure:</b> {depart_date}\n\n"
    message += f"<a href='https://travel-scout.app'>View Details →</a>"
    
    return await send_telegram_message(chat_id, message)