# 🎉 Travel Scout - Rich Telegram Notifications

This document describes the enhanced Telegram notification system with rich formatting, photos, and detailed itineraries.

## What's New

The notification system has been completely upgraded from simple text alerts to rich, multi-message notifications featuring:

- ✅ **Hotel photos** from Unsplash
- ✅ **Rich HTML formatting** with emojis, bold text, sections
- ✅ **Flight details** with airline ratings and duration
- ✅ **Cost breakdown tables** with total estimation
- ✅ **Weather forecasts** for destination
- ✅ **Packing checklists** customized by weather and trip type
- ✅ **Booking intelligence** (optimal booking windows, savings analysis)
- ✅ **Inline keyboard buttons** (Book Flight, Book Hotel, View Map)
- ✅ **Google Maps links** for venue navigation

## Architecture

```
User Alert → Flight Search → Hotel Service → Weather Data
                                              ↓
                           Notification Integration Service
                                              ↓
                    Rich Itinerary → Telegram Bot API → Multiple Messages
```

## Message Flow

When a flight deal matches user preferences, the system sends **3 Telegram messages**:

### Message 1: Photo with Caption
- Hotel image
- Hotel name, rating, price
- **Inline buttons**: Book Flight | Book Hotel | View Map

### Message 2: Rich Itinerary Details
- Trip header with emoji (🏎️ F1, 💼 Business, 🏖️ Leisure)
- Event/venue information (if applicable)
- Flight details with airline rating ⭐
- Booking intelligence tips
- Hotel recommendation
- Weather forecast
- Cost breakdown table

### Message 3: Packing Checklist
- Essential documents
- Weather-specific items (sunscreen, jackets, umbrellas)
- Trip-type items (business attire, camera, etc.)

## Files Modified

| File | Changes |
|------|---------|
| `app/notifications/telegram.py` | Complete rewrite with dataclasses, photo sending, hotel images, inline keyboards, packing lists, weather data, cost tables |
| `app/models/schemas.py` | Added `RichItinerary`, `FlightDetails`, `HotelInfo`, `WeatherForecast` schemas |
| `app/routers/notifications.py` | Added `POST /api/notifications/test-rich-itinerary` endpoint |
| `app/notifications/__init__.py` | Updated exports for new notification functions |
| `app/services/__init__.py` | Updated exports for hotel and notification services |
| `app/services/hotel_service.py` | **NEW** - Hotel data, weather patterns, booking intelligence |
| `app/services/notification_integration.py` | **NEW** - Integration service combining flights + hotels + notifications |
| `test_rich_notification.py` | **NEW** - Test script to send real notifications |
| `demo_rich_notifications.py` | **NEW** - Demo script showing expected output |
| `sample_itinerary_f1.json` | **NEW** - Sample F1 Miami GP itinerary payload |
| `sample_itinerary_business.json` | **NEW** - Sample London business trip payload |

## API Usage

### Test Rich Itinerary Endpoint

```bash
POST /api/notifications/test-rich-itinerary
Content-Type: application/json
Authorization: Bearer <your_jwt_token>

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
    "booking_url": "https://..."
  },
  "hotel": {
    "name": "Hyatt Regency Miami",
    "price_per_night": 285,
    "image_url": "https://images.unsplash.com/...",
    "distance_km": 12.5,
    "rating": 4.2,
    "booking_url": "https://...",
    "address": "400 SE 2nd Ave, Miami, FL 33131"
  },
  "weather": {
    "temp_high": 29,
    "temp_low": 24,
    "condition": "Partly cloudy",
    "humidity": 65,
    "rain_chance": 20
  },
  "event_name": "Formula 1 Miami Grand Prix 2025",
  "venue_name": "Miami International Autodrome",
  "venue_location": "Miami Gardens, FL",
  "savings_analysis": "💰 You could save $180 by booking this weekend",
  "best_booking_time": "📊 Optimal booking window: 3-5 weeks before departure",
  "send_packing_list": true
}
```

### Response

```json
{
  "success": true,
  "message": "Rich itinerary notification sent",
  "chat_id": "123456789",
  "includes_photo": true
}
```

## Trip Types

| Type | Emoji | Packing Focus |
|------|-------|---------------|
| `f1` | 🏎️ | Camera, binoculars, walking shoes |
| `business` | 💼 | Laptop, business attire, business cards |
| `leisure` | 🏖️ | Swimwear, camera, casual wear |
| `adventure` | 🎒 | Hiking gear, first aid, power bank |
| `romance` | 💑 | Nice outfits, camera, evening wear |
| `family` | 👨‍👩‍👧‍👦 | Kids essentials, snacks, entertainment |

## Hotel Image Sources

All hotel images are from **Unsplash** - a high-quality, free stock photo service:

- Miami: `images.unsplash.com/photo-1566073771259-...`
- London: `images.unsplash.com/photo-1551882547-...`
- Paris/Nice: `images.unsplash.com/photo-1564501049412-...`
- Dubai: `images.unsplash.com/photo-1512453979798-...`
- Singapore: `images.unsplash.com/photo-1564501049412-...`

Images are cached and reliable for Telegram photo messages.

## Testing

### Option 1: Run Demo (No Telegram Bot Required)

```bash
cd backend
source .venv/bin/activate
python demo_rich_notifications.py
```

This shows what the notifications will look like without sending real messages.

### Option 2: Run Test Script (Requires Bot Token)

```bash
cd backend
source .venv/bin/activate

# Set environment variables
export TELEGRAM_BOT_TOKEN=your_bot_token_here
export TELEGRAM_CHAT_ID=your_chat_id_here

# Send test notifications
python test_rich_notification.py
```

### Option 3: Test via API (Requires Running Server)

```bash
# Start the server
cd backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8001

# Send test request (in another terminal)
curl -X POST http://localhost:8001/api/notifications/test-rich-itinerary \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d @sample_itinerary_f1.json
```

## Sample Output

### Message 1 (Photo)
```
[Photo: Hyatt Regency Miami]
Caption: 🏨 Hyatt Regency Miami
        ⭐ 4.2/5 • $285/night

[Buttons: Book Flight] [Book Hotel] [View Map]
```

### Message 2 (Rich Text)
```
🏎️ Your Trip is Ready!

🏁 Formula 1 Miami Grand Prix 2025
📍 Venue: Miami International Autodrome

✈️ FLIGHT DETAILS

MPM → MIA
• Airline: South African Airways ⭐⭐⭐½ (3.9/5)
• Duration: 17h
• Stops: 2 layovers
• Price: $1,250
• Departure: 2025-05-02

📊 Booking Intelligence
📊 Optimal booking window: 3-5 weeks before departure
💡 You could save $180 by booking this weekend vs. next week

🏨 HOTEL RECOMMENDATION

Hyatt Regency Miami
• Rating: ⭐⭐⭐⭐ (4.2/5)
• Price: $285/night
• Distance: 12.5km from Miami International Autodrome

☁️ DESTINATION WEATHER
• High: 29°C | Low: 24°C
• Conditions: Partly cloudy
• Humidity: 65%
• Rain chance: 20%

💰 Cost Breakdown
• Flight: $1,250
• Hotel (7 nights @ $285/night): $1,995
• Est. meals & transport: $387
• Total Estimated: $3,632
```

### Message 3 (Packing List)
```
🎒 Packing Checklist

📄 Passport/ID
✈️ Flight tickets/boarding passes
🏨 Hotel booking confirmation
🧴 Sunscreen
🕶️ Sunglasses
🧢 Hat/cap
📷 Camera/binoculars
👟 Comfortable walking shoes
🔋 Power bank
📱 Phone charger
💊 Basic medications
💳 Credit cards & cash
```

## Configuration

Add to your `.env` file:

```bash
# Telegram Bot
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Optional: Customize
CACHE_TTL=3600
```

## Next Steps

1. **Set up Telegram bot** via @BotFather
2. **Get chat ID** by messaging the bot and checking webhook logs
3. **Test with demo** to see expected output
4. **Send real notification** with test script
5. **Integrate** into alert matching pipeline

## Fallback Behavior

If hotel photos fail to send:
- The text itinerary is still delivered
- Photo is skipped, no error to user

If weather data unavailable:
- Weather section is omitted
- Rest of itinerary still sent

If packing list too long:
- Split into multiple messages
- Or sent as single condensed list

## Airline Ratings

Built-in ratings for common airlines (expandable):

| Airline | Rating |
|---------|--------|
| Qatar Airways | 4.9 |
| Singapore Airlines | 4.9 |
| Emirates | 4.8 |
| Turkish Airlines | 4.5 |
| British Airways | 4.2 |
| Delta | 4.2 |
| Lufthansa | 4.3 |
| South African Airways | 3.9 |
| Ethiopian Airlines | 4.0 |
| LAM Mozambique Airlines | 3.5 |

---

*Built with ❤️ for Travel Scout*