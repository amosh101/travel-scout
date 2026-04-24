"""
Notification Integration Service

Combines flight data with hotel, weather, and intelligence data
to send rich Telegram notifications with full itineraries.
"""

from datetime import date, datetime, timedelta
from typing import Optional
from app.scrapers.flight_scraper import search_flights, FlightOffer, get_best_flight
from app.services.hotel_service import (
    get_hotel_for_destination,
    get_weather_for_destination,
    get_booking_intelligence,
    HotelData
)
from app.notifications.telegram import (
    send_rich_itinerary,
    TripItinerary,
    FlightDetails as TelegramFlightDetails,
    HotelDetails as TelegramHotelDetails,
    WeatherInfo as TelegramWeatherInfo
)


def flight_to_telegram_details(flight: FlightOffer) -> TelegramFlightDetails:
    """Convert FlightOffer to Telegram FlightDetails."""
    from app.notifications.telegram import get_airline_rating
    
    return TelegramFlightDetails(
        origin=flight.origin,
        destination=flight.destination,
        airline=flight.airline,
        price=flight.price,
        currency=flight.currency,
        depart_date=flight.depart_date.isoformat(),
        return_date=flight.return_date.isoformat() if flight.return_date else None,
        duration_minutes=flight.duration_minutes,
        stops=flight.stops,
        airline_rating=get_airline_rating(flight.airline),
        booking_url=flight.booking_link
    )


def hotel_to_telegram_details(hotel: HotelData) -> TelegramHotelDetails:
    """Convert HotelData to Telegram HotelDetails."""
    return TelegramHotelDetails(
        name=hotel.name,
        price_per_night=hotel.price_per_night,
        image_url=hotel.image_url,
        distance_km=hotel.distance_km,
        rating=hotel.rating,
        booking_url=hotel.booking_url,
        address=hotel.address
    )


def dict_to_weather_info(weather: dict) -> TelegramWeatherInfo:
    """Convert weather dict to Telegram WeatherInfo."""
    return TelegramWeatherInfo(
        temp_high=weather["temp_high"],
        temp_low=weather["temp_low"],
        condition=weather["condition"],
        humidity=weather["humidity"],
        rain_chance=weather["rain_chance"]
    )


async def find_and_notify_flight_deal(
    chat_id: str,
    origin: str,
    destination: str,
    depart_date: date,
    return_date: Optional[date] = None,
    max_price: Optional[float] = None,
    event_name: Optional[str] = None,
    venue_name: Optional[str] = None,
    venue_location: Optional[str] = None,
    trip_type: str = "leisure"
) -> bool:
    """
    Find best flight deal and send rich notification with hotel, weather, etc.
    
    Args:
        chat_id: Telegram chat ID
        origin: Origin airport code
        destination: Destination airport code
        depart_date: Departure date
        return_date: Return date (optional)
        max_price: Maximum price filter
        event_name: Name of event (for F1, concerts, etc.)
        venue_name: Venue name
        venue_location: Venue location string
        trip_type: "f1", "business", "leisure", etc.
    
    Returns:
        True if notification sent successfully
    """
    # Find best flight
    best_flight = await get_best_flight(
        origin=origin,
        destination=destination,
        date_from=depart_date,
        date_to=return_date or (depart_date + timedelta(days=3)),
        max_price=max_price
    )
    
    if not best_flight:
        print(f"No flights found for {origin} -> {destination}")
        return False
    
    # Get hotel for destination
    hotel = get_hotel_for_destination(
        destination=destination,
        max_price=best_flight.price * 0.3 if best_flight else None,  # Hotel ~30% of flight cost
        min_rating=3.5
    )
    
    # Get weather
    weather = get_weather_for_destination(destination)
    
    # Get booking intelligence
    days_until = (depart_date - date.today()).days
    intelligence = get_booking_intelligence(origin, destination, days_until)
    
    # Build itinerary
    flight_details = flight_to_telegram_details(best_flight)
    
    itinerary = TripItinerary(
        trip_type=trip_type,
        flight=flight_details,
        hotel=hotel_to_telegram_details(hotel) if hotel else None,
        weather=dict_to_weather_info(weather),
        event_name=event_name,
        venue_name=venue_name,
        venue_location=venue_location,
        savings_analysis=intelligence["savings_analysis"],
        best_booking_time=intelligence["best_booking_time"]
    )
    
    # Send rich notification
    success = await send_rich_itinerary(
        chat_id=chat_id,
        itinerary=itinerary,
        send_packing_list=True
    )
    
    return success


async def process_user_alert(
    chat_id: str,
    origin: str,
    destination: str,
    interest_keywords: Optional[str] = None,
    budget: Optional[float] = None,
    event_date: Optional[date] = None
) -> bool:
    """
    Process a user alert and send notification if deal found.
    
    This is the main entry point for the alert system.
    
    Args:
        chat_id: Telegram chat ID
        origin: Origin airport
        destination: Destination airport
        interest_keywords: Keywords like "F1", "beach", "business"
        budget: Maximum budget
        event_date: Date of event/travel
    
    Returns:
        True if notification was sent
    """
    # Parse trip type from keywords
    trip_type = "leisure"
    event_name = None
    venue_name = None
    
    if interest_keywords:
        keywords_lower = interest_keywords.lower()
        if "f1" in keywords_lower or "formula" in keywords_lower or "grand prix" in keywords_lower:
            trip_type = "f1"
            if "miami" in keywords_lower or destination == "MIA":
                event_name = "Formula 1 Miami Grand Prix"
                venue_name = "Miami International Autodrome"
            elif "monaco" in keywords_lower or destination == "NCE":
                event_name = "Formula 1 Monaco Grand Prix"
                venue_name = "Circuit de Monaco"
        elif "business" in keywords_lower or "conference" in keywords_lower:
            trip_type = "business"
        elif "beach" in keywords_lower or "vacation" in keywords_lower:
            trip_type = "leisure"
    
    # Set default dates if not provided
    if not event_date:
        event_date = date.today() + timedelta(days=30)
    
    return_date = event_date + timedelta(days=3) if trip_type == "f1" else event_date + timedelta(days=7)
    
    # Send rich notification
    success = await find_and_notify_flight_deal(
        chat_id=chat_id,
        origin=origin,
        destination=destination,
        depart_date=event_date,
        return_date=return_date,
        max_price=budget,
        event_name=event_name,
        venue_name=venue_name,
        trip_type=trip_type
    )
    
    return success


__all__ = [
    'find_and_notify_flight_deal',
    'process_user_alert',
    'flight_to_telegram_details',
    'hotel_to_telegram_details',
]