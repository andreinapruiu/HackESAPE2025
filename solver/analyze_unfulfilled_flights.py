#!/usr/bin/env python3
"""
Analyze END_OF_GAME_UNFULFILLED_FLIGHT_KITS penalties
to understand which flights are being missed
"""
import re
from collections import defaultdict

def analyze_unfulfilled_flights(log_file='solver_session.log'):
    """Extract and analyze unfulfilled flights at end of game"""
    
    pattern = r'END_OF_GAME_UNFULFILLED_FLIGHT_KITS - EUR([\d,\.]+) - End of game penalty for unfulfilled kits on flight (\w+)'
    
    unfulfilled_flights = []
    
    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            match = re.search(pattern, line)
            if match:
                penalty_amount = float(match.group(1).replace(',', ''))
                flight_number = match.group(2)
                unfulfilled_flights.append({
                    'flight': flight_number,
                    'penalty': penalty_amount
                })
    
    # Sort by penalty (highest first)
    unfulfilled_flights.sort(key=lambda x: x['penalty'], reverse=True)
    
    print("=" * 80)
    print("END OF GAME UNFULFILLED FLIGHTS ANALYSIS")
    print("=" * 80)
    print()
    print(f"Total Flights with Zero Kits Loaded: {len(unfulfilled_flights)}")
    print(f"Total Penalty: EUR{sum(f['penalty'] for f in unfulfilled_flights):,.2f}")
    print()
    
    # Top 20 most expensive
    print("Top 20 Most Expensive Unfulfilled Flights:")
    print("-" * 80)
    for i, flight in enumerate(unfulfilled_flights[:20], 1):
        print(f"{i:2d}. {flight['flight']:8s}  EUR{flight['penalty']:>15,.2f}")
    
    print()
    print("=" * 80)
    print("DIAGNOSIS: These flights got ZERO kits loaded")
    print("=" * 80)
    print()
    print("Possible Root Causes:")
    print("1. Flights departing from airports with no stock")
    print("2. Flights scheduled before kits arrive at origin airport")
    print("3. Processing time delays - kits not ready before departure")
    print("4. Lead time issues - purchase orders not placed early enough")
    print("5. Logic bug - not loading ANY kits on these specific flights")
    print()
    print("Next Steps:")
    print("1. Check flight schedule CSV - when do these flights depart?")
    print("2. Check if origin airports have stock at departure time")
    print("3. Verify purchase orders are placed with enough lead time")
    print("4. Add logic to prioritize loading SOME kits even if not full capacity")
    print()
    
    # Flight number patterns
    flight_prefixes = defaultdict(int)
    for flight in unfulfilled_flights:
        prefix = flight['flight'][:4]  # AB10, AB11, etc.
        flight_prefixes[prefix] += 1
    
    print("Flight Number Distribution:")
    print("-" * 40)
    for prefix in sorted(flight_prefixes.keys()):
        count = flight_prefixes[prefix]
        print(f"  {prefix}xx: {count} flights")
    
    print()
    print("=" * 80)

if __name__ == '__main__':
    analyze_unfulfilled_flights()
