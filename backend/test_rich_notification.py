#!/usr/bin/env python3
"""
Test script for rich Telegram notifications.
Sends a sample F1 trip itinerary to test the enhanced notification system.
"""

import asyncio
import os
import sys

# Ensure app module can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.notifications.telegram import (
    send_rich_itinerary,
    TripItinerary,
    FlightDetails,
    HotelDetails,
    WeatherInfo
)


async def send_test_f1_itinerary(chat_id: str = None):
    """Send a test F1 Miami Grand Prix itinerary."""
    
    # Use from environment or fallback
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
    
    if not chat_id:
        print("❌ Error: TELEGRAM_CHAT_ID not set")
        print("Set it with: export TELEGRAM_CHAT_ID=your_chat_id_here")
        return False
    
    print(f"📤 Sending test F1 itinerary to chat ID: {chat_id}")
    print("=" * 60)
    
    # Create sample flight details
    flight = FlightDetails(
        origin="MPM",  # Maputo
        destination="MIA",  # Miami
        airline="South African Airways",
        price=1250.00,
        currency="USD",
        depart_date="2025-05-02",
        return_date="2025-05-05",
        duration_minutes=1020,  # 17 hours
        stops=2,
        airline_rating=3.9,
        booking_url="https://www.skyscanner.com/transport/flights/mpm/mia/250502/250505/"
    )
    
    # Create sample hotel details with real Unsplash image
    hotel = HotelDetails(
        name="Hyatt Regency Miami",
        price_per_night=285.00,
        image_url="https://images.unsplash.com/photo-1566073771259-6a8506099945?w=800&q=80",
        distance_km=12.5,
        rating=4.2,
        booking_url="https://www.booking.com/hotel/us/hyatt-regency-miami.html",
        address="400 SE 2nd Ave, Miami, FL 33131"
    )
    
    # Create sample weather
    weather = WeatherInfo(
        temp_high=29,
        temp_low=24,
        condition="Partly cloudy",
        humidity=65,
        rain_chance=20
    )
    
    # Build complete itinerary
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
    
    print("\n📋 Itinerary Details:")
    print(f"   Event: {itinerary.event_name}")
    print(f"   Route: {flight.origin} → {flight.destination}")
    print(f"   Airline: {flight.airline} ({flight.airline_rating}/5)")
    print(f"   Price: ${flight.price}")
    print(f"   Hotel: {hotel.name} ({hotel.rating}⭐) - ${hotel.price_per_night}/night")
    print(f"   Distance from venue: {hotel.distance_km}km")
    print(f"   Weather: {weather.temp_high}°C / {weather.temp_low}°C, {weather.condition}")
    print()
    
    # Send the rich itinerary
    success = await send_rich_itinerary(
        chat_id=chat_id,
        itinerary=itinerary,
        send_packing_list=True
    )
    
    if success:
        print("✅ Rich itinerary sent successfully!")
        print("\n📱 Expected Telegram output:")
        print("   - Photo message with hotel image and caption")
        print("   - Detailed itinerary with flight info, ratings, costs")
        print("   - Booking buttons (Book Flight, Book Hotel, View Map)")
        print("   - Weather forecast section")
        print("   - Cost breakdown table")
        print("   - Packing checklist as follow-up message")
    else:
        print("❌ Failed to send rich itinerary")
        print("\nTroubleshooting:")
        print("   1. Ensure TELEGRAM_BOT_TOKEN is set in .env")
        print("   2. Ensure TELEGRAM_CHAT_ID is set correctly")
        print("   3. Verify bot is started: @BotFather → /mybots → Select bot")
        print("   4. Check you've messaged the bot at least once")
    
    return success


async def send_test_business_itinerary(chat_id: str = None):
    """Send a test business trip itinerary (London)."""
    
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
    
    if not chat_id:
        print("❌ Error: TELEGRAM_CHAT_ID not set")
        return False
    
    print(f"\n📤 Sending test Business itinerary to chat ID: {chat_id}")
    print("=" * 60)
    
    flight = FlightDetails(
        origin="MPM",
        destination="LHR",
        airline="British Airways",
        price=850.00,
        currency="USD",
        depart_date="2025-06-15",
        return_date="2025-06-20",
        duration_minutes=600,  # 10 hours direct
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
    
    print("\n📋 Itinerary Details:")
    print(f"   Route: {flight.origin} → {flight.destination}")
    print(f"   Type: Business trip")
    print(f"   Hotel: {hotel.name} ({hotel.rating}⭐) - Premium business hotel")
    print(f"   Direct flight: {flight.duration_minutes // 60}h")
    print()
    
    success = await send_rich_itinerary(
        chat_id=chat_id,
        itinerary=itinerary,
        send_packing_list=True
    )
    
    if success:
        print("✅ Business itinerary sent successfully!")
    else:
        print("❌ Failed to send business itinerary")
    
    return success


async def main():
    """Run all tests."""
    print("🧪 Travel Scout - Rich Notification Test Suite")
    print("=" * 60)
    
    # Check environment
    from app.config import settings
    
    if not settings.TELEGRAM_BOT_TOKEN:
        print("\n❌ TELEGRAM_BOT_TOKEN not configured!")
        print("   Add to your .env file:")
        print("   TELEGRAM_BOT_TOKEN=your_bot_token_here")
        print("   TELEGRAM_CHAT_ID=your_chat_id_here")
        sys.exit(1)
    
    print(f"✅ Bot token configured: {settings.TELEGRAM_BOT_TOKEN[:10]}...")
    
    # Run tests
    results = []
    
    # Test 1: F1 Event
    results.append(await send_test_f1_itinerary())
    
    # Wait between messages
    await asyncio.sleep(2)
    
    # Test 2: Business Trip
    results.append(await send_test_business_itinerary())
    
    print("\n" + "=" * 60)
    print("📊 Test Summary:")
    print(f"   Passed: {sum(results)}/{len(results)}")
    print(f"   Failed: {len(results) - sum(results)}/{len(results)}")
    
    if all(results):
        print("\n🎉 All tests passed!")
    else:
        print("\n⚠️  Some tests failed. Check logs above.")


if __name__ == "__main__":
    asyncio.run(main())