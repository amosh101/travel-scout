#!/usr/bin/env python3
"""
Search Events CLI - Travel Scout Neural Search

Search for events using the Neural Search System.

Usage:
    python search_events.py "F1 races" --location "Europe" --date-from 2026-06-01 --date-to 2026-08-31
    python search_events.py "hip hop concerts London" --limit 10
    python search_events.py "Formula 1" --type f1 --json
"""

import sys
import json
import argparse
from datetime import date
from pathlib import Path

# Add paths
NEURAL_INTEGRATION_PATH = Path(__file__).parent / "neural-integration"
sys.path.insert(0, str(NEURAL_INTEGRATION_PATH))

try:
    from event_search import EventSearcher, EventResult, search_events
except ImportError as e:
    print(f"Error: {e}")
    print("Make sure the neural-integration modules are available.")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Search for events using Neural Search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "F1 races"
  %(prog)s "hip hop concerts London" --date-from 2026-06-01 --date-to 2026-08-31
  %(prog)s "Formula 1 British GP" --location "Silverstone" --json
  %(prog)s "music festivals" --type festival --location "Europe" --limit 15
        """
    )
    
    parser.add_argument("query", help="Search query (e.g., 'F1 races', 'concerts London')")
    parser.add_argument("--location", "-l", help="Location filter (city, region, or country)")
    parser.add_argument("--date-from", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--date-to", help="End date (YYYY-MM-DD)")
    parser.add_argument("--type", choices=["concert", "f1", "sports", "festival"],
                       help="Event type filter")
    parser.add_argument("--limit", "-n", type=int, default=10,
                       help="Maximum number of results (default: 10)")
    parser.add_argument("--json", "-j", action="store_true",
                       help="Output results as JSON")
    parser.add_argument("--save", "-s", help="Save results to JSON file")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Show detailed output")
    
    args = parser.parse_args()
    
    try:
        # Parse dates
        date_from = None
        date_to = None
        
        if args.date_from:
            try:
                date_from = date.fromisoformat(args.date_from)
            except ValueError:
                print(f"Error: Invalid date-from format. Use YYYY-MM-DD")
                sys.exit(1)
        
        if args.date_to:
            try:
                date_to = date.fromisoformat(args.date_to)
            except ValueError:
                print(f"Error: Invalid date-to format. Use YYYY-MM-DD")
                sys.exit(1)
        
        # Validate date range
        if date_from and date_to and date_from > date_to:
            print("Error: date-from must be before date-to")
            sys.exit(1)
        
        # Perform search
        print(f"🔍 Searching: '{args.query}'")
        if args.location:
            print(f"   Location: {args.location}")
        if date_from:
            print(f"   From: {date_from}")
        if date_to:
            print(f"   To: {date_to}")
        print()
        
        results = search_events(
            query=args.query,
            location=args.location,
            date_from=args.date_from,
            date_to=args.date_to,
            event_type=args.type,
            limit=args.limit
        )
        
        # Output results
        if args.json or args.save:
            output = json.dumps([r.to_dict() for r in results], indent=2)
            if args.save:
                with open(args.save, 'w') as f:
                    f.write(output)
                print(f"✓ Saved {len(results)} results to {args.save}")
            if args.json:
                print(output)
        else:
            # Pretty print
            if not results:
                print("No events found matching your criteria.")
                return
            
            print(f"Found {len(results)} event(s):\n")
            print("=" * 80)
            
            for i, event in enumerate(results, 1):
                print(f"\n{i}. {event.title}")
                print(f"   Type: {event.event_type.upper()}")
                
                if event.venue:
                    print(f"   Venue: {event.venue}")
                
                if event.location:
                    print(f"   Location: {event.location}")
                
                if event.start_date:
                    print(f"   Date: {event.start_date}")
                    if event.end_date and event.end_date != event.start_date:
                        print(f"   End Date: {event.end_date}")
                
                if event.price_range:
                    print(f"   Price: {event.price_range}")
                
                print(f"   Relevance: {event.relevance_score:.3f}")
                
                if event.url:
                    print(f"   URL: {event.url}")
                
                if args.verbose:
                    print(f"\n   Description: {event.description}")
                else:
                    desc = event.description[:200]
                    if len(event.description) > 200:
                        desc += "..."
                    print(f"   {desc}")
            
            print("\n" + "=" * 80)
            print(f"\n✓ Search complete: {len(results)} event(s) found")
    
    except KeyboardInterrupt:
        print("\n\nSearch cancelled.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()