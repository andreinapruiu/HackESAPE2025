"""
Test script to inspect actual API responses
"""

import requests
import json

api_key = '43b9ab90-b593-404c-a8d8-aaa074e181e1'
base_url = 'http://localhost:8080/api/v1'

# End previous session
try:
    requests.post(f'{base_url}/session/end', headers={'API-KEY': api_key})
except:
    pass

# Start session
response = requests.post(f'{base_url}/session/start', headers={'API-KEY': api_key})
session_id = response.text.strip('"')
print(f"Session started: {session_id}\n")

# Play first few rounds and inspect responses
headers = {'API-KEY': api_key, 'SESSION-ID': session_id}

for round_num in range(5):
    day = round_num // 24
    hour = round_num % 24
    
    action = {
        'day': day,
        'hour': hour,
        'flightLoads': [],
        'kitPurchasingOrders': []
    }
    
    response = requests.post(f'{base_url}/play/round', headers=headers, json=action)
    data = response.json()
    
    print(f"\n{'='*80}")
    print(f"Round {round_num} (Day {day}, Hour {hour})")
    print(f"{'='*80}")
    print(f"Total Cost: EUR {data.get('totalCost', 0):,.2f}")
    print(f"Penalties: {len(data.get('penalties', []))}")
    print(f"Flight Updates: {len(data.get('flightUpdates', []))}")
    
    if len(data.get('flightUpdates', [])) > 0:
        print("\nFirst 3 flights:")
        for i, flight in enumerate(data['flightUpdates'][:3]):
            print(f"  {i+1}. FlightId: {flight['flightId']}")
            print(f"     EventType: {flight['eventType']}")
            print(f"     Origin: {flight.get('originAirport', 'N/A')}")
            print(f"     Destination: {flight.get('destinationAirport', 'N/A')}")
            print(f"     Passengers: {flight.get('passengers', {})}")
            
    # Check flight event types
    event_types = {}
    for flight in data.get('flightUpdates', []):
        et = flight['eventType']
        event_types[et] = event_types.get(et, 0) + 1
    
    if event_types:
        print(f"\nEvent Types: {event_types}")

print("\n" + "="*80)
print("Test complete")
