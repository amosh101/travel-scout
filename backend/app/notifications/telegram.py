import httpx
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
from app.config import settings


@dataclass
class HotelDetails:
    """Hotel details for rich notifications."""
    name: str
    price_per_night: float
    image_url: Optional[str] = None
    distance_km: Optional[float] = None
    rating: Optional[float] = None
    booking_url: Optional[str] = None
    address: Optional[str] = None


@dataclass
class FlightDetails:
    """Flight details for rich notifications."""
    origin: str
    destination: str
    airline: str
    price: float
    currency: str = "USD"
    depart_date: str = ""
    return_date: Optional[str] = None
    duration_minutes: int = 0
    stops: int = 0
    airline_rating: Optional[float] = None
    booking_url: Optional[str] = None


@dataclass
class WeatherInfo:
    """Weather forecast for destination."""
    temp_high: int
    temp_low: int
    condition: str
    humidity: int
    rain_chance: int


@dataclass
class TripItinerary:
    """Complete trip itinerary with all details."""
    trip_type: str  # "f1", "business", "leisure"
    flight: FlightDetails
    hotel: Optional[HotelDetails] = None
    weather: Optional[WeatherInfo] = None
    packing_checklist: Optional[List[str]] = None
    event_name: Optional[str] = None
    venue_name: Optional[str] = None
    venue_location: Optional[str] = None
    total_cost: Optional[float] = None
    savings_analysis: Optional[str] = None
    best_booking_time: Optional[str] = None


# Airline ratings (simplified - could be expanded)
AIRLINE_RATINGS = {
    "Emirates": 4.8,
    "Qatar Airways": 4.9,
    "Singapore Airlines": 4.9,
    "South African Airways": 3.9,
    "British Airways": 4.2,
    "Air France": 4.1,
    "Lufthansa": 4.3,
    "Turkish Airlines": 4.5,
    "Ethiopian Airlines": 4.0,
    "United Airlines": 4.0,
    "Delta": 4.2,
    "KLM": 4.1,
    "Air Canada": 4.0,
    "Air Austral": 3.8,
    "Kenya Airways": 3.7,
    "LAM Mozambique Airlines": 3.5,
}


def format_duration(minutes: int) -> str:
    """Format duration in minutes to human readable string."""
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0 and mins > 0:
        return f"{hours}h {mins}m"
    elif hours > 0:
        return f"{hours}h"
    else:
        return f"{mins}m"


def get_airline_rating(airline: str) -> float:
    """Get rating for airline, default to 3.5 if unknown."""
    return AIRLINE_RATINGS.get(airline, 3.5)


def get_emoji_stars(rating: float) -> str:
    """Convert rating to star emojis."""
    full_stars = int(rating)
    half_star = rating - full_stars >= 0.5
    stars = "⭐" * full_stars
    if half_star:
        stars += "½"
    return stars


def get_trip_emoji(trip_type: str) -> str:
    """Get appropriate emoji for trip type."""
    emojis = {
        "f1": "🏎️",
        "business": "💼",
        "leisure": "🏖️",
        "adventure": "🎒",
        "romance": "💑",
        "family": "👨‍👩‍👧‍👦",
    }
    return emojis.get(trip_type, "✈️")


def get_weather_emoji(condition: str) -> str:
    """Get weather emoji based on condition."""
    condition = condition.lower()
    if "sun" in condition or "clear" in condition:
        return "☀️"
    elif "cloud" in condition:
        return "☁️"
    elif "rain" in condition:
        return "🌧️"
    elif "storm" in condition:
        return "⛈️"
    elif "snow" in condition:
        return "🌨️"
    elif "fog" in condition:
        return "🌫️"
    else:
        return "🌤️"


def format_cost_table(flight: FlightDetails, hotel: Optional[HotelDetails], nights: int = 7) -> str:
    """Format a cost breakdown table."""
    lines = ["<b>💰 Cost Breakdown</b>", ""]
    lines.append(f"• Flight: {flight.currency} {flight.price:,.0f}")
    
    hotel_total = 0.0
    if hotel:
        hotel_total = hotel.price_per_night * nights
        lines.append(f"• Hotel ({nights} nights @ {flight.currency} {hotel.price_per_night:,.0f}/night): {flight.currency} {hotel_total:,.0f}")
    
    estimated_extras = flight.price * 0.15 + (hotel_total * 0.1 if hotel else 0)
    lines.append(f"• Est. meals & transport: {flight.currency} {estimated_extras:,.0f}")
    
    total = flight.price + hotel_total + estimated_extras
    lines.append("")
    lines.append(f"<b>Total Estimated: {flight.currency} {total:,.0f}</b>")
    
    return "\n".join(lines)


async def send_telegram_message(
    chat_id: str, 
    message: str, 
    parse_mode: str = "HTML",
    reply_markup: Optional[Dict] = None,
    disable_web_page_preview: bool = False
) -> bool:
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
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview
    }
    
    if reply_markup:
        payload["reply_markup"] = reply_markup
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, timeout=10.0)
            return response.status_code == 200
        except Exception as e:
            print(f"Error sending Telegram message: {e}")
            return False


async def send_telegram_photo(
    chat_id: str,
    photo_url: str,
    caption: str = "",
    parse_mode: str = "HTML",
    reply_markup: Optional[Dict] = None
) -> bool:
    """
    Send a photo via Telegram Bot API.
    Returns True if successful, False otherwise.
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        return False
    
    url = f"{settings.TELEGRAM_API_URL}/bot{settings.TELEGRAM_BOT_TOKEN}/sendPhoto"
    
    payload = {
        "chat_id": chat_id,
        "photo": photo_url,
        "parse_mode": parse_mode,
        "caption": caption[:1000]  # Telegram caption limit
    }
    
    if reply_markup:
        payload["reply_markup"] = reply_markup
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, timeout=15.0)
            if response.status_code != 200:
                print(f"Telegram photo send error: {response.text}")
                return False
            return True
        except Exception as e:
            print(f"Error sending Telegram photo: {e}")
            return False


async def send_telegram_media_group(
    chat_id: str,
    media: List[Dict[str, Any]],
    disable_notification: bool = False
) -> bool:
    """
    Send multiple photos as an album via Telegram Bot API.
    Returns True if successful.
    """
    if not settings.TELEGRAM_BOT_TOKEN or len(media) == 0:
        return False
    
    # Telegram supports max 10 items per media group
    media = media[:10]
    
    url = f"{settings.TELEGRAM_API_URL}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMediaGroup"
    
    payload = {
        "chat_id": chat_id,
        "media": media,
        "disable_notification": disable_notification
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, timeout=20.0)
            return response.status_code == 200
        except Exception as e:
            print(f"Error sending media group: {e}")
            return False


def create_booking_keyboard(
    flight_url: Optional[str] = None,
    hotel_url: Optional[str] = None,
    map_url: Optional[str] = None,
    dismiss_callback: str = "dismiss_alert"
) -> Dict:
    """Create inline keyboard with booking buttons."""
    keyboard = {"inline_keyboard": []}
    row = []
    
    if flight_url:
        row.append({"text": "✈️ Book Flight", "url": flight_url})
    
    if hotel_url:
        row.append({"text": "🏨 Book Hotel", "url": hotel_url})
    
    if map_url:
        row.append({"text": "🗺️ View Map", "url": map_url})
    
    if row:
        keyboard["inline_keyboard"].append(row)
    
    # Add dismiss button
    keyboard["inline_keyboard"].append([
        {"text": "✓ Got it", "callback_data": dismiss_callback}
    ])
    
    return keyboard


def generate_packing_checklist(destination: str, weather: Optional[WeatherInfo], trip_type: str = "leisure") -> List[str]:
    """Generate a packing checklist based on destination and weather."""
    checklist = []
    
    # Essential documents
    checklist.extend([
        "📄 Passport/ID",
        "✈️ Flight tickets/boarding passes",
        "🏨 Hotel booking confirmation",
    ])
    
    # Weather-specific items
    if weather:
        if weather.temp_high > 25:
            checklist.extend(["🧴 Sunscreen", "🕶️ Sunglasses", "🧢 Hat/cap"])
        if weather.temp_low < 15:
            checklist.extend(["🧥 Warm jacket", "🧣 Scarf", "🧤 Light gloves"])
        if weather.rain_chance > 40:
            checklist.append("☔ Umbrella/rain jacket")
    
    # Trip-type specific
    if trip_type == "business":
        checklist.extend(["💼 Business attire", "💻 Laptop & charger", "📱 Business cards"])
    elif trip_type == "f1":
        checklist.extend(["📷 Camera/binoculars", "👟 Comfortable walking shoes", "🔋 Power bank"])
    elif trip_type == "leisure":
        checklist.extend(["👟 Walking shoes", "🏊 Swimwear", "📸 Camera"])
    
    # Electronics & misc
    checklist.extend([
        "📱 Phone charger",
        "💊 Basic medications",
        "💳 Credit cards & cash",
    ])
    
    return checklist


def format_packing_list(checklist: List[str]) -> str:
    """Format packing checklist for Telegram."""
    return "<b>🎒 Packing Checklist</b>\n\n" + "\n".join(checklist)


def build_rich_itinerary_message(itinerary: TripItinerary) -> str:
    """Build a rich formatted itinerary message."""
    trip_emoji = get_trip_emoji(itinerary.trip_type)
    
    # Header
    lines = [
        f"{trip_emoji} <b>Your Trip is Ready!</b>",
        "",
        "─" * 25,
        "",
    ]
    
    # Event info if available
    if itinerary.event_name:
        lines.append(f"🏁 <b>{itinerary.event_name}</b>")
        if itinerary.venue_name:
            lines.append(f"📍 Venue: {itinerary.venue_name}")
        lines.append("")
    
    # Flight Section
    flight = itinerary.flight
    rating = flight.airline_rating or get_airline_rating(flight.airline)
    stars = get_emoji_stars(rating)
    duration = format_duration(flight.duration_minutes)
    
    lines.extend([
        "✈️ <b>FLIGHT DETAILS</b>",
        "",
        f"<b>{flight.origin} → {flight.destination}</b>",
        f"• Airline: {flight.airline} {stars} ({rating:.1f}/5)",
        f"• Duration: {duration}",
        f"• Stops: {flight.stops} {'layover' if flight.stops == 1 else 'layovers'}",
        f"• Price: <b>{flight.currency} {flight.price:,.0f}</b>",
        f"• Departure: {flight.depart_date}",
    ])
    
    if flight.return_date:
        lines.append(f"• Return: {flight.return_date}")
    
    lines.append("")
    
    # Flight optimization analysis
    if itinerary.best_booking_time:
        lines.extend([
            "📊 <b>Booking Intelligence</b>",
            f"{itinerary.best_booking_time}",
            ""
        ])
    
    if itinerary.savings_analysis:
        lines.extend([
            f"💡 {itinerary.savings_analysis}",
            ""
        ])
    
    lines.append("─" * 25)
    lines.append("")
    
    # Hotel Section (if available)
    if itinerary.hotel:
        hotel = itinerary.hotel
        lines.extend([
            "🏨 <b>HOTEL RECOMMENDATION</b>",
            "",
            f"<b>{hotel.name}</b>",
        ])
        
        if hotel.rating:
            hotel_stars = get_emoji_stars(hotel.rating)
            lines.append(f"• Rating: {hotel_stars} ({hotel.rating:.1f}/5)")
        
        lines.append(f"• Price: {flight.currency} {hotel.price_per_night:,.0f}/night")
        
        if hotel.distance_km:
            lines.append(f"• Distance: {hotel.distance_km:.1f}km from {itinerary.venue_name or 'city center'}")
        
        if hotel.address:
            lines.append(f"• Address: {hotel.address}")
        
        lines.append("")
    
    # Weather Section
    if itinerary.weather:
        weather = itinerary.weather
        weather_emoji = get_weather_emoji(weather.condition)
        lines.extend([
            f"{weather_emoji} <b>DESTINATION WEATHER</b>",
            "",
            f"• High: {weather.temp_high}°C | Low: {weather.temp_low}°C",
            f"• Conditions: {weather.condition}",
            f"• Humidity: {weather.humidity}%",
            f"• Rain chance: {weather.rain_chance}%",
            "",
        ])
    
    # Cost Summary
    nights = 7  # Default assumption
    lines.append(format_cost_table(flight, itinerary.hotel, nights))
    lines.append("")
    lines.append("─" * 25)
    
    return "\n".join(lines)


async def send_rich_itinerary(
    chat_id: str,
    itinerary: TripItinerary,
    send_packing_list: bool = True
) -> bool:
    """
    Send a complete rich itinerary with photo and formatted message.
    """
    # Build the message
    message = build_rich_itinerary_message(itinerary)
    
    # Create booking buttons
    map_url = None
    if itinerary.venue_location:
        map_url = f"https://www.google.com/maps/search/?api=1&query={itinerary.venue_location.replace(' ', '+')}"
    elif itinerary.hotel and itinerary.hotel.address:
        map_url = f"https://www.google.com/maps/search/?api=1&query={itinerary.hotel.address.replace(' ', '+')}"
    else:
        map_url = f"https://www.google.com/maps/search/?api=1&query={itinerary.flight.destination}"
    
    keyboard = create_booking_keyboard(
        flight_url=itinerary.flight.booking_url,
        hotel_url=itinerary.hotel.booking_url if itinerary.hotel else None,
        map_url=map_url
    )
    
    success = False
    
    # Try to send hotel photo first if available
    if itinerary.hotel and itinerary.hotel.image_url:
        photo_caption = f"🏨 <b>{itinerary.hotel.name}</b>\n"
        if itinerary.hotel.rating:
            photo_caption += f"⭐ {itinerary.hotel.rating:.1f}/5 • "
        photo_caption += f"{itinerary.flight.currency} {itinerary.hotel.price_per_night:,.0f}/night"
        
        photo_sent = await send_telegram_photo(
            chat_id=chat_id,
            photo_url=itinerary.hotel.image_url,
            caption=photo_caption,
            reply_markup=keyboard
        )
        
        if photo_sent:
            # Send details as follow-up message
            await send_telegram_message(
                chat_id=chat_id,
                message=message,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            success = True
        else:
            # Fallback: send text-only message
            success = await send_telegram_message(
                chat_id=chat_id,
                message=message,
                parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
    else:
        # No hotel photo, send text message with keyboard
        success = await send_telegram_message(
            chat_id=chat_id,
            message=message,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    
    # Send packing list as separate message
    if success and send_packing_list:
        if not itinerary.packing_checklist:
            itinerary.packing_checklist = generate_packing_checklist(
                itinerary.flight.destination,
                itinerary.weather,
                itinerary.trip_type
            )
        
        packing_message = format_packing_list(itinerary.packing_checklist)
        await send_telegram_message(
            chat_id=chat_id,
            message=packing_message,
            parse_mode="HTML"
        )
    
    return success


# Legacy function for backward compatibility
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
    
    # Create a basic itinerary with legacy data
    flight = FlightDetails(
        origin=origin,
        destination=destination,
        airline=airline or "Unknown",
        price=price,
        currency=currency,
        depart_date=depart_date,
        airline_rating=get_airline_rating(airline) if airline else 3.5
    )
    
    itinerary = TripItinerary(
        trip_type="leisure",
        flight=flight
    )
    
    return await send_rich_itinerary(chat_id, itinerary, send_packing_list=False)