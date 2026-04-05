"""
MiroFish Integration for Travel Scout
Connects to the multi-agent swarm for AI-powered travel intelligence
"""
import os
import asyncio
from typing import List, Dict, Optional
from datetime import date
import aiohttp


class MiroFishTravelClient:
    """
    Client for MiroFish swarm intelligence.
    Uses local Ollama for zero-cost AI processing.
    """
    
    def __init__(self, base_url: str = "http://localhost:5001"):
        self.base_url = base_url
        self.enabled = self._check_health()
    
    def _check_health(self) -> bool:
        """Check if MiroFish is available"""
        import requests
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=2)
            return resp.status_code == 200
        except:
            return False
    
    async def parse_interest_natural_language(self, user_text: str) -> Dict:
        """
        Parse user text like 'flights to europe under $500 in June' 
        into structured interest using MiroFish agents.
        """
        if not self.enabled:
            return self._fallback_parse(user_text)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/nlp/parse",
                    json={"text": user_text, "domain": "travel"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            print(f"MiroFish NLP error: {e}")
        
        return self._fallback_parse(user_text)
    
    def _fallback_parse(self, text: str) -> Dict:
        """Fallback parsing when MiroFish unavailable"""
        text_lower = text.lower()
        
        # Extract budget
        budget = None
        import re
        budget_match = re.search(r'(\d+)', text)
        if budget_match:
            budget = int(budget_match.group(1))
        
        # Extract destination
        destinations = {
            'europe': 'Europe', 'asia': 'Asia', 'america': 'Americas',
            'africa': 'Africa', 'london': 'LHR', 'paris': 'CDG',
            'miami': 'MIA', 'new york': 'NYC', 'tokyo': 'NRT',
            'dubai': 'DXB', 'singapore': 'SIN', 'maputo': 'MPM'
        }
        destination = None
        for key, val in destinations.items():
            if key in text_lower:
                destination = val
                break
        
        # Extract dates
        dates = []
        months = ['january', 'february', 'march', 'april', 'may', 'june',
                  'july', 'august', 'september', 'october', 'november', 'december']
        for i, month in enumerate(months, 1):
            if month in text_lower:
                dates.append(f"2026-{i:02d}")
        
        return {
            "destination": destination or "Unknown",
            "budget": budget,
            "origin": "MPM",
            "dates": dates,
            "parsed": True,
            "source": "fallback"
        }
    
    async def score_deals(
        self,
        deals: List[Dict],
        user_preferences: Optional[Dict] = None
    ) -> List[Dict]:
        """
        Score deals using MiroFish swarm intelligence.
        Factors: price, airline reliability, timing, user preferences.
        """
        if not self.enabled or not deals:
            return self._fallback_score(deals)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/score",
                    json={
                        "items": deals,
                        "context": user_preferences or {},
                        "scoring_factors": ["price", "airline_quality", "timing"]
                    },
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return result.get("scored_items", deals)
        except Exception as e:
            print(f"MiroFish scoring error: {e}")
        
        return self._fallback_score(deals)
    
    def _fallback_score(self, deals: List[Dict]) -> List[Dict]:
        """Fallback scoring when MiroFish unavailable"""
        scored = []
        for deal in deals:
            price = deal.get("price", 1000)
            duration = deal.get("duration_minutes", 600)
            stops = deal.get("stops", 1)
            
            # Simple weighted score: lower is better
            price_score = price / 1000 * 60  # 60% weight
            duration_score = duration / 1000 * 25  # 25% weight
            stops_score = stops * 15  # 15% weight
            
            total_score = price_score + duration_score + stops_score
            
            scored.append({
                **deal,
                "ai_score": 100 - min(total_score, 100),
                "score_factors": {
                    "price_component": price_score,
                    "duration_component": duration_score,
                    "stops_component": stops_score
                },
                "scoring_source": "fallback"
            })
        
        return sorted(scored, key=lambda x: x["ai_score"], reverse=True)
    
    async def predict_price_trend(
        self,
        origin: str,
        destination: str,
        target_date: date
    ) -> Dict:
        """
        Predict whether flight prices will rise or fall.
        Uses historical data + MiroFish simulation.
        """
        if not self.enabled:
            return self._fallback_prediction(origin, destination, target_date)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/predict",
                    json={
                        "route": f"{origin}-{destination}",
                        "target_date": target_date.isoformat(),
                        "prediction_type": "price_trend"
                    },
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            print(f"MiroFish prediction error: {e}")
        
        return self._fallback_prediction(origin, destination, target_date)
    
    def _fallback_prediction(self, origin: str, destination: str, target_date: date) -> Dict:
        """Fallback price prediction based on booking window heuristics"""
        from datetime import datetime
        
        days_until = (target_date - date.today()).days
        
        # Simple heuristic: prices drop 2-3 months out, rise within 2 weeks
        if days_until > 90:
            prediction = "likely_to_drop"
            confidence = 0.6
            advice = "Prices typically drop 2-3 months before departure. Wait if flexible."
        elif days_until > 30:
            prediction = "stable"
            confidence = 0.5
            advice = "Prices are typically stable. Book when you see a good deal."
        elif days_until > 14:
            prediction = "likely_to_rise"
            confidence = 0.7
            advice = "Prices typically rise within 2-4 weeks of departure. Book soon."
        else:
            prediction = "will_rise"
            confidence = 0.8
            advice = "Last-minute prices are high. Book immediately or consider alternatives."
        
        return {
            "route": f"{origin}-{destination}",
            "prediction": prediction,
            "confidence": confidence,
            "advice": advice,
            "days_until_departure": days_until,
            "source": "fallback_heuristic"
        }
    
    async def generate_travel_itinerary(
        self,
        destination: str,
        duration_days: int,
        budget: float,
        interests: List[str]
    ) -> Dict:
        """Generate personalized itinerary using MiroFish agents"""
        if not self.enabled:
            return {
                "destination": destination,
                "days": duration_days,
                "budget": budget,
                "activities": ["Explore local area", "Visit top attractions"],
                "source": "fallback"
            }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/itinerary",
                    json={
                        "destination": destination,
                        "duration_days": duration_days,
                        "budget": budget,
                        "interests": interests
                    },
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            print(f"MiroFish itinerary error: {e}")
        
        return {"error": "MiroFish unavailable", "source": "error"}


# Ollama direct integration for when MiroFish is down
class OllamaDirectClient:
    """
    Direct Ollama integration for zero-cost AI processing.
    Fallback when MiroFish service is unavailable.
    """
    
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self.model = "qwen3:8b"  # Same as MiroFish
    
    async def is_available(self) -> bool:
        """Check if Ollama is running"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/api/tags",
                    timeout=aiohttp.ClientTimeout(total=2)
                ) as resp:
                    return resp.status == 200
        except:
            return False
    
    async def generate(self, prompt: str, system: Optional[str] = None) -> str:
        """Generate text using Ollama"""
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "model": self.model,
                    "prompt": prompt,
                    "system": system or "You are a helpful travel assistant.",
                    "stream": False
                }
                
                async with session.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return result.get("response", "")
        except Exception as e:
            print(f"Ollama error: {e}")
        
        return ""


# Unified AI service
class TravelAIService:
    """
    Unified AI service for Travel Scout.
    Tries MiroFish → Ollama → Fallback heuristics
    """
    
    def __init__(self):
        self.mirofish = MiroFishTravelClient()
        self.ollama = OllamaDirectClient()
    
    async def parse_interest(self, text: str) -> Dict:
        """Parse natural language interest"""
        # Try MiroFish first
        if self.mirofish.enabled:
            return await self.mirofish.parse_interest_natural_language(text)
        
        # Try Ollama direct
        if await self.ollama.is_available():
            prompt = f"""Parse this travel request into structured data:
Text: "{text}"

Extract and return as JSON:
- destination: where they want to go
- origin: where they're leaving from (default MPM for Maputo)
- budget: maximum price in USD
- dates: when they want to travel

Return ONLY valid JSON."""
            
            response = await self.ollama.generate(
                prompt,
                system="You parse travel requests into structured data. Return only JSON."
            )
            
            # Try to extract JSON
            try:
                import json
                # Find JSON in response
                start = response.find('{')
                end = response.rfind('}') + 1
                if start >= 0 and end > start:
                    return json.loads(response[start:end])
            except:
                pass
        
        # Fallback
        return self.mirofish._fallback_parse(text)
    
    async def score_deals(self, deals: List[Dict], user_prefs: Optional[Dict] = None) -> List[Dict]:
        """Score flight deals with AI"""
        return await self.mirofish.score_deals(deals, user_prefs)
    
    async def get_booking_advice(self, route: str, departure_date: date) -> Dict:
        """Get advice on when to book"""
        return await self.mirofish.predict_price_trend(
            route[:3], route[-3:], departure_date
        )


# Export singleton
travel_ai = TravelAIService()
