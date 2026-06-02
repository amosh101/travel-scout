#!/usr/bin/env python3
"""
Build Itinerary CLI - Travel Scout

Create complete travel itineraries combining events, flights, and hotels.

Usage:
    python build_itinerary.py --event "F1 British GP" --dates "2026-07-18:2026-07-20"
    python build_itinerary.py --event "hip hop concerts" --dates "2026-06-01:2026-06-05" --interests "concerts, music"
    python build_itinerary.py --event "Formula 1" --dates "2026-06-01:2026-06-30" --type f1 --json
"""

import sys
import json
import argparse
from pathlib import Path

# Add paths
NEURAL_INTEGRATION_PATH = Path(__file__).parent / "neural-integration"
sys.path.insert(0, str(NEURAL_INTEGRATION_PATH))

try:
    from itinerary_builder import (
        ItineraryBuilder,
        create_itinerary,
        ItineraryBuilderError
    )
except ImportError as e:
    print(f"Error: {e}")
    print("Make sure the neural-integration modules are available.")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Build travel itineraries combining events, flights, and hotels",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --event "F1 British GP" --dates "2026-07-18:2026-07-20"
  %(prog)s --event "Formula 1 races" --dates "2026-06-01:2026-09-01" --type f1
  %(prog)s --event "concerts" --dates "2026-06-01:2026-06-05" --interests "rock,indie" --budget mid
  %(prog)s --event "Silverstone" --dates "2026-07-18" --origin "London" --json
        """
    )
    
    parser.add_argument("--event", "-e", required=True,
                       help="Event search query (e.g., 'F1 British GP', 'concerts London')")
    parser.add_argument("--dates", "-d", required=True,
                       help="Date range YYYY-MM-DD:YYYY-MM-DD or single date YYYY-MM-DD")
    parser.add_argument("--origin", "-o", default="Maputo",
                       help="Origin city (default: Maputo)")
    parser.add_argument("--interests", "-i",
                       help="Comma-separated interests (e.g., 'F1,motorsport,concerts')")
    parser.add_argument("--type", "-t", choices=["concert", "f1", "sports", "festival"],
                       help="Event type filter")
    parser.add_argument("--budget", "-b", default="mid", choices=["budget", "mid", "luxury"],
                       help="Accommodation budget level (default: mid)")
    parser.add_argument("--json", "-j", action="store_true",
                       help="Output results as JSON")
    parser.add_argument("--save", "-s", help="Save itinerary to JSON file")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Show detailed output")
    
    args = parser.parse_args()
    
    try:
        print(f"🎯 Building itinerary for: {args.event}")
        print(f"📅 Dates: {args.dates}")
        print(f"🌍 Origin: {args.origin}")
        if args.interests:
            print(f"⭐ Interests: {args.interests}")
        if args.type:
            print(f"🎪 Event Type: {args.type}")
        print(f"💰 Budget Level: {args.budget}")
        print()
        
        # Build itinerary
        result = create_itinerary(
            event_query=args.event,
            dates=args.dates,
            origin=args.origin,
            interests=args.interests,
            event_type=args.type,
            budget_level=args.budget
        )
        
        # Output results
        if args.json or args.save:
            output = json.dumps(result, indent=2, default=str)
            if args.save:
                with open(args.save, 'w') as f:
                    f.write(output)
                print(f"✓ Saved itinerary to {args.save}")
            if args.json:
                print(output)
        else:
            # Pretty print
            print("\n" + "=" * 80)
            print(f"🎯 {result['title']}")
            print("=" * 80)
            
            # Trip overview
            print(f"\n📅 Dates: {result['start_date']} to {result['end_date']} ({result['duration_days']} days)")
            print(f"📍 Destination: {result['destination']}")
            if result['interests']:
                print(f"⭐ Interests: {', '.join(result['interests'])}")
            
            # Flights
            print(f"\n✈️  FLIGHTS:")
            if result['transport']:
                t = result['transport']
                print(f"   {t['origin']} → {t['destination']}")
                print(f"   Airline: {t['airline'] or 'Various'}")
                print(f"   Outbound: {t['outbound_date']}")
                if t['return_date']:
                    print(f"   Return: {t['return_date']}")
                print(f"   Price: ${t['price']:.2f} {t['currency']}")
                if t['duration_minutes']:
                    hours = t['duration_minutes'] // 60
                    mins = t['duration_minutes'] % 60
                    print(f"   Duration: {hours}h {mins}m")
                if t['stops'] is not None:
                    stops_str = "Non-stop" if t['stops'] == 0 else f"{t['stops']} stop(s)"
                    print(f"   Stops: {stops_str}")
                if t['booking_link']:
                    print(f"   Book: {t['booking_link']}")
            else:
                print("   ⚠️  FLIGHT DATA UNAVAILABLE")
                print("   This bot cannot access real-time flight prices.")
                print("   For actual flights, search:")
                print("   • Google Flights: https://flights.google.com")
                print("   • Kayak: https://www.kayak.com")
                print("   • Skyscanner: https://www.skyscanner.net")
            
            # Accommodation
            print(f"\n🏨 ACCOMMODATION:")
            if result['accommodation']:
                a = result['accommodation']
                print(f"   {a['name']}")
                print(f"   Location: {a['location']}")
                if a['check_in']:
                    print(f"   Check-in: {a['check_in']}")
                if a['check_out']:
                    print(f"   Check-out: {a['check_out']}")
                print(f"   Price: ${a['price_per_night']:.2f}/night")
                if a['rating']:
                    stars = "⭐" * int(a['rating'])
                    print(f"   Rating: {a['rating']}/5 {stars}")
                if a['amenities']:
                    print(f"   Amenities: {', '.join(a['amenities'])}")
                if a['booking_url']:
                    print(f"   Book: {a['booking_url']}")
            else:
                print("   ⚠️  HOTEL DATA UNAVAILABLE")
                print("   This bot cannot access real-time hotel prices.")
                print("   For actual hotels, search:")
                print("   • Booking.com: https://www.booking.com")
                print("   • Hotels.com: https://www.hotels.com")
                print("   • Airbnb: https://www.airbnb.com")
                print()
                print("   💡 Note: London hotels typically range $150-400+ per night")
            
            # Events
            print(f"\n🎪 EVENTS ({len(result['events'])} found):")
            if result['events']:
                for i, e in enumerate(result['events'], 1):
                    print(f"\n   {i}. {e['title']}")
                    print(f"      Type: {e['event_type'].upper()}")
                    if e.get('venue'):
                        print(f"      Venue: {e['venue']}")
                    if e.get('location'):
                        print(f"      Location: {e['location']}")
                    if e.get('start_date'):
                        print(f"      Date: {e['start_date']}")
                        if e.get('end_date') and e['end_date'] != e['start_date']:
                            print(f"      End Date: {e['end_date']}")
                    if e.get('price_range'):
                        print(f"      Price: {e['price_range']}")
                    if e.get('url'):
                        print(f"      URL: {e['url']}")
                    
                    if args.verbose:
                        print(f"\n      Description: {e['description']}")
            else:
                print("   No events found for the specified criteria.")
            
            # Daily schedule
            print(f"\n📋 DAILY SCHEDULE:")
            for day in result['days']:
                print(f"\n   {day['date']}:")
                if day['events']:
                    for e in day['events']:
                        print(f"      • {e['title']}")
                        if e.get('venue'):
                            print(f"        at {e['venue']}")
                else:
                    print(f"      • {day['notes']}")
            
            # Cost breakdown
            print(f"\n💰 COST BREAKDOWN:")
            has_unavailable = False
            for category, cost in result['cost_breakdown'].items():
                if cost == 0 and category in ['flights', 'accommodation']:
                    print(f"   {category.replace('_', ' ').title()}: ⚠️  NOT INCLUDED (search manually)")
                    has_unavailable = True
                else:
                    print(f"   {category.replace('_', ' ').title()}: ${cost:.2f}")
            
            print(f"\n   ════════════════════════════════════════")
            if has_unavailable:
                print(f"   SUBTOTAL: ${result['estimated_total_cost']:.2f} {result['currency']}")
                print(f"   (Flights + Hotels not included - search manually)")
            else:
                print(f"   TOTAL ESTIMATED: ${result['estimated_total_cost']:.2f} {result['currency']}")
            print(f"   ════════════════════════════════════════")
            
            # Footer
            print(f"\n📅 Created: {result['created_at']}")
            print(f"🔧 Source: {result['source']}")
            print("\n" + "=" * 80)
            print("\n💡 Note: This bot cannot access real-time booking data.")
            print("   Please verify all prices on actual booking sites.")
    
    except KeyboardInterrupt:
        print("\n\nItinerary building cancelled.")
        sys.exit(1)
    except ItineraryBuilderError as e:
        print(f"\n❌ Itinerary Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()