from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.config import settings
from app.database import get_db
from app.models import User
from app.models.schemas import (
    TestNotificationRequest, 
    RichItinerary, 
    FlightDetails, 
    HotelInfo,
    WeatherForecast
)
from app.routers.auth import get_current_user
from app.notifications.telegram import (
    send_telegram_message,
    send_rich_itinerary,
    TripItinerary,
    FlightDetails as TelegramFlightDetails,
    HotelDetails as TelegramHotelDetails,
    WeatherInfo as TelegramWeatherInfo
)
from app.notifications.email import send_resend_email

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.post("/test", status_code=status.HTTP_200_OK)
async def send_test_notification(
    request: TestNotificationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Send a test notification to the specified channel."""
    
    if request.channel == "telegram":
        if not settings.TELEGRAM_BOT_TOKEN:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Telegram bot token not configured"
            )
        
        success = await send_telegram_message(
            chat_id=request.destination,
            message=f"🎉 Travel Scout test message! Your notifications are working."
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to send Telegram message. Check the chat ID."
            )
            
    elif request.channel == "email":
        if not settings.RESEND_API_KEY:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Resend API key not configured"
            )
        
        success = await send_resend_email(
            to=request.destination,
            subject="Travel Scout - Test Notification",
            body="🎉 Your Travel Scout email notifications are working!"
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to send email"
            )
    
    return {"success": True, "message": f"Test {request.channel} notification sent"}


@router.post("/test-rich-itinerary", status_code=status.HTTP_200_OK)
async def send_test_rich_itinerary(
    itinerary: RichItinerary,
    chat_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Send a test rich itinerary notification via Telegram.
    
    Example payload:
    {
        "trip_type": "f1",
        "flight": {
            "origin": "MPM",
            "destination": "MIA",
            "airline": "South African Airways",
            "price": 1250,
            "currency": "USD",
            "depart_date": "2025-05-02",
            "return_date": "2025-05-05",
            "duration_minutes": 1020,
            "stops": 2,
            "airline_rating": 3.9,
            "booking_url": "https://example.com/book"
        },
        "hotel": {
            "name": "Hyatt Regency Miami",
            "price_per_night": 285,
            "image_url": "https://images.unsplash.com/photo-1566073771259-6a8506099945?w=800",
            "distance_km": 12.5,
            "rating": 4.2,
            "booking_url": "https://example.com/hotel",
            "address": "400 SE 2nd Ave, Miami, FL 33131"
        },
        "weather": {
            "temp_high": 29,
            "temp_low": 24,
            "condition": "Partly cloudy",
            "humidity": 65,
            "rain_chance": 20
        },
        "event_name": "Formula 1 Miami Grand Prix",
        "venue_name": "Miami International Autodrome",
        "venue_location": "Miami Gardens, FL",
        "savings_analysis": "Book now - prices typically increase 15% in final 2 weeks",
        "best_booking_time": "Optimal booking window: 3-5 weeks before departure"
    }
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram bot token not configured"
        )
    
    # Use user's telegram_chat_id if no chat_id provided
    target_chat_id = chat_id or current_user.telegram_chat_id
    if not target_chat_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Telegram chat ID provided"
        )
    
    # Convert API schema to Telegram module dataclasses
    flight = TelegramFlightDetails(
        origin=itinerary.flight.origin,
        destination=itinerary.flight.destination,
        airline=itinerary.flight.airline,
        price=itinerary.flight.price,
        currency=itinerary.flight.currency,
        depart_date=itinerary.flight.depart_date,
        return_date=itinerary.flight.return_date,
        duration_minutes=itinerary.flight.duration_minutes,
        stops=itinerary.flight.stops,
        airline_rating=itinerary.flight.airline_rating,
        booking_url=itinerary.flight.booking_url
    )
    
    hotel = None
    if itinerary.hotel:
        hotel = TelegramHotelDetails(
            name=itinerary.hotel.name,
            price_per_night=itinerary.hotel.price_per_night,
            image_url=itinerary.hotel.image_url,
            distance_km=itinerary.hotel.distance_km,
            rating=itinerary.hotel.rating,
            booking_url=itinerary.hotel.booking_url,
            address=itinerary.hotel.address
        )
    
    weather = None
    if itinerary.weather:
        weather = TelegramWeatherInfo(
            temp_high=itinerary.weather.temp_high,
            temp_low=itinerary.weather.temp_low,
            condition=itinerary.weather.condition,
            humidity=itinerary.weather.humidity,
            rain_chance=itinerary.weather.rain_chance
        )
    
    telegram_itinerary = TripItinerary(
        trip_type=itinerary.trip_type,
        flight=flight,
        hotel=hotel,
        weather=weather,
        event_name=itinerary.event_name,
        venue_name=itinerary.venue_name,
        venue_location=itinerary.venue_location,
        total_cost=itinerary.total_cost,
        savings_analysis=itinerary.savings_analysis,
        best_booking_time=itinerary.best_booking_time
    )
    
    success = await send_rich_itinerary(
        chat_id=target_chat_id,
        itinerary=telegram_itinerary,
        send_packing_list=itinerary.send_packing_list
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to send rich itinerary notification"
        )
    
    return {
        "success": True, 
        "message": "Rich itinerary notification sent",
        "chat_id": target_chat_id,
        "includes_photo": itinerary.hotel is not None and itinerary.hotel.image_url is not None
    }