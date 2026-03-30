from fastapi import APIRouter

from app.services.ai_recommendations import ai_service

router = APIRouter(prefix="/ai", tags=["AI Recommendations"])


@router.post("/parse-interest")
async def parse_interest(text: str):
    """Parse natural language interest input into structured data."""
    return await ai_service.parse_interest_natural_language(text)


@router.post("/score-deals")
async def score_deals(user_id: str, deals: list):
    """Score deals with AI-powered ranking."""
    return await ai_service.score_deals(user_id, deals)


@router.get("/predict-window/{destination}")
async def predict_window(destination: str):
    """Predict best booking window for a destination."""
    return await ai_service.predict_booking_window(destination)


@router.get("/itinerary/{interest_id}")
async def get_itinerary(interest_id: str):
    """Generate personalized itinerary suggestions."""
    return await ai_service.generate_itinerary_suggestions(interest_id)