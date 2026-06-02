#!/usr/bin/env python3
"""
Example usage of Travel Scout Neural Integration.

This script demonstrates how to use the search router and related components.
"""

import sys
from pathlib import Path
from datetime import date

# Add integration to path
sys.path.insert(0, str(Path(__file__).parent))

from travel_scout import SearchRouter, get_router


def example_1_basic_search():
    """Example 1: Basic unified search."""
    print("\n" + "="*60)
    print("Example 1: Basic Unified Search")
    print("="*60)
    
    # Create router
    router = SearchRouter()
    
    # Perform search
    result = router.unified_search(
        query="flights to London",
        location="Maputo",
        date_range=(date(2026, 6, 1), date(2026, 6, 7)),
        search_type="flights"
    )
    
    # Display results
    print(f"\nQuery: {result.query}")
    print(f"Source: {result.source}")
    print(f"Results: {result.total_results}")
    print(f"Latency: {result.latency_ms}ms")
    print(f"Failover reason: {result.failover_reason or 'N/A'}")
    
    for i, r in enumerate(result.results[:3], 1):
        print(f"\n{i}. {r.title}")
        print(f"   Price: ${r.price}" if r.price else "   Price: N/A")
        print(f"   URL: {r.url}")


def example_2_specialized_search():
    """Example 2: Specialized flight search."""
    print("\n" + "="*60)
    print("Example 2: Specialized Flight Search")
    print("="*60)
    
    router = SearchRouter()
    
    # Search for specific flight route
    result = router.search_flights(
        origin="MPM",
        destination="LHR",
        depart_date=date(2026, 6, 15),
        return_date=date(2026, 6, 22),
        max_price=1000
    )
    
    print(f"\nFlight Search: MPM → LHR")
    print(f"Source: {result.source}")
    print(f"Found {result.total_results} flights")
    
    for r in result.results[:3]:
        print(f"\n  • {r.title}")
        if r.price:
            print(f"    Price: ${r.price} {r.currency or 'USD'}")
        print(f"    URL: {r.url}")


def example_3_hotel_search():
    """Example 3: Hotel search."""
    print("\n" + "="*60)
    print("Example 3: Hotel Search")
    print("="*60)
    
    router = SearchRouter()
    
    result = router.search_hotels(
        location="Paris",
        check_in=date(2026, 7, 1),
        check_out=date(2026, 7, 5),
        max_price=200
    )
    
    print(f"\nHotel Search: Paris")
    print(f"Source: {result.source}")
    print(f"Found {result.total_results} hotels")
    
    for r in result.results[:3]:
        print(f"\n  • {r.title}")
        print(f"    {r.description[:100]}...")


def example_4_search_with_filters():
    """Example 4: Search with filters."""
    print("\n" + "="*60)
    print("Example 4: Search with Filters")
    print("="*60)
    
    router = SearchRouter()
    
    # Search with price filter
    result = router.unified_search(
        query="flights to Europe",
        search_type="flights",
        filters={
            "max_price": 500,
            "source": "flight_scraper"
        }
    )
    
    print(f"\nFiltered Search: flights to Europe (max $500)")
    print(f"Found {result.total_results} results")
    
    for r in result.results[:3]:
        print(f"  • {r.title} - ${r.price}")


def example_5_force_source():
    """Example 5: Force specific data source."""
    print("\n" + "="*60)
    print("Example 5: Force Data Source")
    print("="*60)
    
    router = SearchRouter()
    
    # Force neural-only search
    result_neural = router.unified_search(
        query="flights to London",
        search_type="flights",
        force_source="neural"
    )
    
    print(f"\nNeural-only search:")
    print(f"  Source: {result_neural.source}")
    print(f"  Results: {result_neural.total_results}")
    
    # Force scraper-only search
    result_scraper = router.unified_search(
        query="flights to London",
        search_type="flights",
        force_source="scraper"
    )
    
    print(f"\nScraper-only search:")
    print(f"  Source: {result_scraper.source}")
    print(f"  Results: {result_scraper.total_results}")


def example_6_metrics_and_history():
    """Example 6: View metrics and search history."""
    print("\n" + "="*60)
    print("Example 6: Metrics and History")
    print("="*60)
    
    router = SearchRouter()
    
    # Perform some searches
    router.unified_search("flights to London")
    router.unified_search("hotels in Paris")
    router.unified_search("events in New York")
    
    # Get metrics
    metrics = router.get_metrics()
    
    print("\nSearch Metrics:")
    print(f"  Total searches: {metrics.get('total_searches', 0)}")
    print(f"  Source breakdown: {metrics.get('source_breakdown', {})}")
    print(f"  Avg latency: {metrics.get('average_latency_ms', 0):.2f}ms")
    
    # Get history
    history = router.get_search_history(limit=5)
    
    print("\nRecent Searches:")
    for h in history:
        print(f"  • {h['query']} ({h['source']}, {h['latency_ms']}ms)")


def example_7_sync_data():
    """Example 7: Sync scraper data to neural index."""
    print("\n" + "="*60)
    print("Example 7: Sync Data to Neural Index")
    print("="*60)
    
    router = SearchRouter()
    
    # Sample flight data from scraper
    sample_flights = [
        {
            "origin": "MPM",
            "destination": "JNB",
            "airline": "South African Airways",
            "price": 450,
            "currency": "USD",
            "depart_date": "2026-06-15",
            "duration_minutes": 90,
            "stops": 0,
            "booking_link": "https://example.com/flights/MPM-JNB"
        },
        {
            "origin": "MPM",
            "destination": "LHR",
            "airline": "British Airways",
            "price": 850,
            "currency": "USD",
            "depart_date": "2026-06-20",
            "duration_minutes": 600,
            "stops": 0,
            "booking_link": "https://example.com/flights/MPM-LHR"
        }
    ]
    
    # Sync to neural index
    result = router.sync_to_neural("flights", sample_flights)
    
    print(f"\nSync Result:")
    print(f"  Status: {result.get('status', 'unknown')}")
    print(f"  Indexed: {result.get('documents_indexed', 0)}")
    print(f"  Failed: {result.get('documents_failed', 0)}")


def example_8_quick_search():
    """Example 8: Quick module-level search."""
    print("\n" + "="*60)
    print("Example 8: Quick Module-Level Search")
    print("="*60)
    
    # Use module-level search function
    from travel_scout import search
    
    result = search("flights to London", location="Maputo")
    
    print(f"\nQuick Search Result:")
    print(f"  Query: {result.query}")
    print(f"  Source: {result.source}")
    print(f"  Results: {result.total_results}")


def main():
    """Run all examples."""
    print("\n" + "="*60)
    print("TRAVEL SCOUT NEURAL INTEGRATION EXAMPLES")
    print("="*60)
    
    try:
        example_1_basic_search()
        example_2_specialized_search()
        example_3_hotel_search()
        example_4_search_with_filters()
        example_5_force_source()
        example_6_metrics_and_history()
        example_7_sync_data()
        example_8_quick_search()
        
        print("\n" + "="*60)
        print("All examples completed successfully!")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"\nError running examples: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()