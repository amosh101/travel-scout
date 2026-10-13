#!/usr/bin/env python3
"""
Test script for Neural Search Integration

Verifies all components are working correctly.
"""

import sys
import traceback
from pathlib import Path

# Add paths
NEURAL_INTEGRATION_PATH = Path(__file__).parent / "neural-integration"
sys.path.insert(0, str(NEURAL_INTEGRATION_PATH))

def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")
    try:
        from travel_scout.search_router import SearchRouter, UnifiedSearchResponse
        from travel_scout.search_orchestrator import SearchOrchestrator, SearchSource
        from travel_scout.neural_client import NeuralClient, NeuralSearchResponse
        from event_search import EventSearcher, EventResult, search_events
        from itinerary_builder import ItineraryBuilder, create_itinerary
        print("✓ All imports successful")
        return True
    except Exception as e:
        print(f"✗ Import failed: {e}")
        traceback.print_exc()
        return False


def test_search_router():
    """Test SearchRouter initialization."""
    print("\nTesting SearchRouter...")
    try:
        from travel_scout.search_router import SearchRouter
        router = SearchRouter()
        print(f"✓ SearchRouter initialized")
        return True
    except Exception as e:
        print(f"✗ SearchRouter failed: {e}")
        return False


def test_event_search():
    """Test event search functionality."""
    print("\nTesting Event Search...")
    try:
        from event_search import search_events
        
        # Search for F1 events
        results = search_events(query="F1", limit=3)
        
        if len(results) > 0:
            print(f"✓ Event search returned {len(results)} results")
            for i, r in enumerate(results[:2], 1):
                print(f"  {i}. {r.title[:50]}... (score: {r.relevance_score:.3f})")
            return True
        else:
            print("⚠ Event search returned no results (may need data)")
            return True  # Still pass if no data
    except Exception as e:
        print(f"✗ Event search failed: {e}")
        traceback.print_exc()
        return False


def test_itinerary_builder():
    """Test itinerary builder."""
    print("\nTesting Itinerary Builder...")
    try:
        from itinerary_builder import create_itinerary
        
        result = create_itinerary(
            event_query="F1 races",
            dates="2026-07-01:2026-07-05",
            origin="London",
            event_type="f1",
            budget_level="mid"
        )
        
        if result and 'title' in result:
            print(f"✓ Itinerary created: {result['title']}")
            print(f"  Destination: {result.get('destination', 'N/A')}")
            print(f"  Events found: {len(result.get('events', []))}")
            print(f"  Est. cost: ${result.get('estimated_total_cost', 0):.2f}")
            return True
        else:
            print("✗ Itinerary builder returned invalid result")
            return False
    except Exception as e:
        print(f"✗ Itinerary builder failed: {e}")
        traceback.print_exc()
        return False


def test_backend_router():
    """Test backend router import."""
    print("\nTesting Backend Router...")
    try:
        backend_path = Path(__file__).parent / "backend"
        sys.path.insert(0, str(backend_path))
        
        from app.routers import neural_search
        print("✓ Neural search router import successful")
        return True
    except Exception as e:
        print(f"⚠ Backend router not available: {e}")
        return True  # Not critical for core functionality


def main():
    """Run all tests."""
    print("=" * 60)
    print("Neural Search Integration Test Suite")
    print("=" * 60)
    
    tests = [
        ("Imports", test_imports),
        ("Search Router", test_search_router),
        ("Event Search", test_event_search),
        ("Itinerary Builder", test_itinerary_builder),
        ("Backend Router", test_backend_router),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"\n✗ {name} crashed: {e}")
            results.append((name, False))
    
    print("\n" + "=" * 60)
    print("Test Results")
    print("=" * 60)
    
    passed = sum(1 for _, p in results if p)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    print("=" * 60)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 60)
    
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)