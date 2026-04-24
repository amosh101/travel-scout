#!/usr/bin/env python3
"""
Demo script showing rich Telegram notification output.
This displays what the notifications will look like when sent.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.notifications.telegram import (
    build_rich_itinerary_message,
    TripItinerary,
    FlightDetails,
    HotelDetails,
    WeatherInfo,
    format_packing_list,
    generate_packing_checklist,
    create_booking_keyboard,
    get_trip_emoji,
)


def print_header(text):
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)


def print_subheader(text):
    """Print a subheader."""
    print(f"\n{'─' * 70}")
    print(f"  {text}")
    print(f"{'─' * 70}")


def demo_f1_miami_itinerary():
    """Demo F1 Miami Grand Prix itinerary."""
    print_header("🎉 DEMO: F1 Miami Grand Prix Itinerary")
    
    flight = FlightDetails(
        origin="MPM",
        destination="MIA",
        airline="South African Airways",
        price=1250.00,
        currency="USD",
        depart_date="2025-05-02",
        return_date="2025-05-05",
        duration_minutes=1020,
        stops=2,
        airline_rating=3.9,
        booking_url="https://www.skyscanner.com/transport/flights/mpm/mia/"
    )
    
    hotel = HotelDetails(
        name="Hyatt Regency Miami",
        price_per_night=285.00,
        image_url="https://images.unsplash.com/photo-1566073771259-6a8506099945?w=800&q=80",
        distance_km=12.5,
        rating=4.2,
        booking_url="https://www.booking.com/hotel/us/hyatt-regency-miami.html",
        address="400 SE 2nd Ave, Miami, FL 33131"
    )
    
    weather = WeatherInfo(
        temp_high=29,
        temp_low=24,
        condition="Partly cloudy",
        humidity=65,
        rain_chance=20
    )
    
    itinerary = TripItinerary(
        trip_type="f1",
        flight=flight,
        hotel=hotel,
        weather=weather,
        event_name="Formula 1 Miami Grand Prix 2025",
        venue_name="Miami International Autodrome",
        venue_location="Miami Gardens, FL, USA",
        savings_analysis="💰 You could save $180 by booking this weekend vs. next week",
        best_booking_time="📊 Optimal booking window: 3-5 weeks before departure"
    )
    
    # Build message
    message = build_rich_itinerary_message(itinerary)
    
    print_subheader("📱 TELEGRAM MESSAGE (HTML Format)")
    print(message)
    
    # Show booking buttons
    print_subheader("🔗 INLINE KEYBOARD BUTTONS")
    keyboard = create_booking_keyboard(
        flight_url=flight.booking_url,
        hotel_url=hotel.booking_url,
        map_url=f"https://www.google.com/maps/search/?api=1&query=Miami+International+Autodrome"
    )
    print(f"Buttons: {keyboard}")
    
    # Show packing list
    print_subheader("🎒 PACKING CHECKLIST (Follow-up Message)")
    packing_list = generate_packing_checklist("MIA", weather, "f1")
    packing_message = format_packing_list(packing_list)
    print(packing_message)
    
    # Photo info
    print_subheader("📸 PHOTO MESSAGE")
    print(f"Photo URL: {hotel.image_url}")
    print(f"Caption: 🏨 <b>{hotel.name}</b>")
    print(f"        ⭐ {hotel.rating:.1f}/5 • ${hotel.price_per_night:.0f}/night")


def demo_business_london_itinerary():
    """Demo London business trip itinerary."""
    print_header("💼 DEMO: London Business Trip Itinerary")
    
    flight = FlightDetails(
        origin="MPM",
        destination="LHR",
        airline="British Airways",
        price=850.00,
        currency="USD",
        depart_date="2025-06-15",
        return_date="2025-06-20",
        duration_minutes=600,
        stops=0,
        airline_rating=4.2,
        booking_url="https://www.britishairways.com/travel/home"
    )
    
    hotel = HotelDetails(
        name="The Savoy",
        price_per_night=450.00,
        image_url="https://images.unsplash.com/photo-1551882547-ff40c63fe5fa?w=800&q=80",
        distance_km=2.1,
        rating=4.8,
        booking_url="https://www.fairmont.com/savoy-london/",
        address="Strand, London WC2R 0EZ, UK"
    )
    
    weather = WeatherInfo(
        temp_high=18,
        temp_low=12,
        condition="Light rain",
        humidity=72,
        rain_chance=60
    )
    
    itinerary = TripItinerary(
        trip_type="business",
        flight=flight,
        hotel=hotel,
        weather=weather,
        venue_name="London Business District",
        venue_location="City of London, UK",
        savings_analysis="📈 Corporate rate saves 12% on standard pricing",
        best_booking_time="📊 Book 4-6 weeks ahead for best business fares"
    )
    
    message = build_rich_itinerary_message(itinerary)
    
    print_subheader("📱 TELEGRAM MESSAGE (HTML Format)")
    print(message)
    
    print_subheader("🎒 BUSINESS PACKING CHECKLIST")
    packing_list = generate_packing_checklist("LHR", weather, "business")
    packing_message = format_packing_list(packing_list)
    print(packing_message)


def demo_leisure_dubai_itinerary():
    """Demo Dubai leisure trip."""
    print_header("🏖️ DEMO: Dubai Luxury Vacation Itinerary")
    
    flight = FlightDetails(
        origin="MPM",
        destination="DXB",
        airline="Emirates",
        price=1180.00,
        currency="USD",
        depart_date="2025-07-10",
        return_date="2025-07-17",
        duration_minutes=480,
        stops=1,
        airline_rating=4.8,
        booking_url="https://www.emirates.com/booking"
    )
    
    hotel = HotelDetails(
        name="Burj Al Arab",
        price_per_night=1250.00,
        image_url="https://images.unsplash.com/photo-1512453979798-5ea904ac6605?w=800&q=80",
        distance_km=28.0,
        rating=4.9,
        booking_url="https://www.jumeirah.com/burj-al-arab",
        address="Jumeirah Beach Road, Dubai, UAE"
    )
    
    weather = WeatherInfo(
        temp_high=42,
        temp_low=32,
        condition="Sunny",
        humidity=35,
        rain_chance=0
    )
    
    itinerary = TripItinerary(
        trip_type="leisure",
        flight=flight,
        hotel=hotel,
        weather=weather,
        savings_analysis="🏨 Early bird hotel booking saves 20%",
        best_booking_time="📊 Book flights 6-8 weeks ahead for Dubai"
    )
    
    message = build_rich_itinerary_message(itinerary)
    
    print_subheader("📱 TELEGRAM MESSAGE (HTML Format)")
    print(message)


def show_telegram_api_structure():
    """Show how the Telegram API calls are structured."""
    print_header("📡 TELEGRAM BOT API STRUCTURE")
    
    print_subheader("Message 1: Photo with Caption")
    print("""
POST https://api.telegram.org/bot<TOKEN>/sendPhoto
{
    "chat_id": "123456789",
    "photo": "https://images.unsplash.com/photo-1566073771259-...",
    "caption": "🏨 <b>Hyatt Regency Miami</b>\n⭐ 4.2/5 • $285/night",
    "parse_mode": "HTML",
    "reply_markup": {
        "inline_keyboard": [
            [{"text": "✈️ Book Flight", "url": "https://..."}],
            [{"text": "✓ Got it", "callback_data": "dismiss_alert"}]
        ]
    }
}
""")
    
    print_subheader("Message 2: Rich Itinerary Details")
    print("""
POST https://api.telegram.org/bot<TOKEN>/sendMessage
{
    "chat_id": "123456789",
    "text": "🏎️ <b>Your Trip is Ready!</b>\n\n... (rich HTML message)",
    "parse_mode": "HTML",
    "disable_web_page_preview": true
}
""")
    
    print_subheader("Message 3: Packing Checklist")
    print("""
POST https://api.telegram.org/bot<TOKEN>/sendMessage
{
    "chat_id": "123456789",
    "text": "<b>🎒 Packing Checklist</b>\n\n• 📄 Passport/ID\n• ...",
    "parse_mode": "HTML"
}
""")


def show_file_changes():
    """Show what files were modified."""
    print_header("📝 FILES MODIFIED")
    
    files = [
        ("app/notifications/telegram.py", 
         "Complete rewrite with rich formatting, photo sending, hotel images, inline keyboards, packing lists, and weather data"),
        ("app/models/schemas.py",
         "Added RichItinerary, FlightDetails, HotelInfo, WeatherForecast schemas"),
        ("app/routers/notifications.py",
         "Added /test-rich-itinerary endpoint for testing rich notifications"),
        ("app/services/hotel_service.py",
         "New file: Hotel data, weather, and booking intelligence services"),
        ("app/services/notification_integration.py",
         "New file: Integration service combining flights + hotels + notifications"),
        ("app/notifications/__init__.py",
         "Updated exports for new notification functions"),
        ("app/services/__init__.py",
         "Updated exports for hotel and notification services"),
    ]
    
    for filepath, description in files:
        print(f"\n✅ {filepath}")
        print(f"   {description.strip()}")


def main():
    """Run all demos."""
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║                                                                      ║
║   🎉 Travel Scout - Rich Telegram Notifications Demo                ║
║                                                                      ║
║   This demo shows what the enhanced Telegram notifications           ║
║   will look like with rich formatting, photos, and detailed          ║
║   itineraries for flights, hotels, and events.                       ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
""")
    
    # Show F1 Miami demo
    demo_f1_miami_itinerary()
    
    # Show London business demo
    demo_business_london_itinerary()
    
    # Show Dubai leisure demo
    demo_leisure_dubai_itinerary()
    
    # Show API structure
    show_telegram_api_structure()
    
    # Show file changes
    show_file_changes()
    
    print("\n" + "=" * 70)
    print("\n✨ DEMO COMPLETE!")
    print("\nTo send real notifications, run:")
    print("  python test_rich_notification.py")
    print("\nOr test via API:")
    print("  curl -X POST http://localhost:8001/api/notifications/test-rich-itinerary \\")
    print("    -H 'Content-Type: application/json' \\")
    print("    -H 'Authorization: Bearer <your_token>' \\")
    print("    -d @sample_itinerary.json")
    print()


if __name__ == "__main__":
    main()
