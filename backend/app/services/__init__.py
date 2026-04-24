# Business logic services
from app.services.hotel_service import (
    HotelData,
    get_hotel_for_destination,
    get_weather_for_destination,
    get_booking_intelligence,
)
from app.services.notification_integration import (
    find_and_notify_flight_deal,
    process_user_alert,
)
from app.services.ai_recommendations import ai_service, DealScore, AIRecommendationService

__all__ = [
    'HotelData',
    'get_hotel_for_destination',
    'get_weather_for_destination',
    'get_booking_intelligence',
    'find_and_notify_flight_deal',
    'process_user_alert',
    'ai_service',
    'DealScore',
    'AIRecommendationService',
]