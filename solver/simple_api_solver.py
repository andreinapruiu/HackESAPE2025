"""
Simple API Solver - Works with minimal API response
Loads initial state from CSV and tracks inventory locally
"""

import requests
import csv
from collections import defaultdict

class SimpleAPISolver:
    
    def __init__(self, api_key, base_url, data_dir='../eval-platform/src/main/resources/liquibase/data'):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {'API-KEY': api_key}
        self.session_id = None
        
        # Load initial data from CSV
        self.airports = self.load_airports(f'{data_dir}/airports_with_stocks.csv')
        
        # Track inventory locally
        self.inventories = {}
        for code, airport in self.airports.items():
            self.inventories[code] = airport['initial_stock'].copy()
        
        # Aircraft capacities
        self.aircraft_capacities = {
            'OJF294': {'FIRST': 12, 'BUSINESS': 28, 'PREMIUM_ECONOMY': 21, 'ECONOMY': 178},
            'OJF206': {'FIRST': 14, 'BUSINESS': 32, 'PREMIUM_ECONOMY': 18, 'ECONOMY': 210},
            'OJF178': {'FIRST': 0, 'BUSINESS': 24, 'PREMIUM_ECONOMY': 24, 'ECONOMY': 132},
            'OJF156': {'FIRST': 8, 'BUSINESS': 16, 'PREMIUM_ECONOMY': 18, 'ECONOMY': 91}
        }
        
        print("Simple API Solver initialized")
    
    def load_airports(self, filepath):
        """Load airports with initial stocks"""
        import os
        script_dir = os.path.dirname(os.path.abspath(__file__))
        full_path = os.path.join(script_dir, filepath)
        
        airports = {}
        with open(full_path, 'r') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                code = row['code']
                airports[code] = {
                    'code': code,
                    'initial_stock': {
                        'FIRST': int(row['initial_fc_stock']),
                        'BUSINESS': int(row['initial_bc_stock']),
                        'PREMIUM_ECONOMY': int(row['initial_pe_stock']),
                        'ECONOMY': int(row['initial_ec_stock'])
                    }
                }
        
        print(f"Loaded {len(airports)} airports")
        return airports
    
    def start_session(self):
        """Start new game session"""
        # Try to end any existing session first
        try:
            requests.post(
                f'{self.base_url}/session/end',
                headers=self.headers
            )
            print("Ended previous session")
        except:
            pass
        
        response = requests.post(
            f'{self.base_url}/session/start',
            headers=self.headers
        )
        self.session_id = response.text.strip('"')
        print(f"Session started: {self.session_id}")
    
    def calculate_safe_load(self, flight):
        """Calculate safe loading based on local inventory"""
        origin = flight['originAirport']
        passengers = flight['passengers']
        aircraft_type = flight.get('aircraftType', 'OJF294')
        capacity = self.aircraft_capacities.get(aircraft_type, {})
        
        kits_to_load = {}
        
        for kt_api, kt_internal in [('first', 'FIRST'), ('business', 'BUSINESS'),
                                     ('premiumEconomy', 'PREMIUM_ECONOMY'), ('economy', 'ECONOMY')]:
            passenger_count = passengers.get(kt_internal, 0)
            aircraft_cap = capacity.get(kt_internal, passenger_count)
            available = self.inventories.get(origin, {}).get(kt_internal, 0)
            
            # Load exactly passengers, but don't exceed capacity or inventory
            desired = min(passenger_count, aircraft_cap, available)
            kits_to_load[kt_api] = max(0, desired)
        
        return kits_to_load
    
    def update_inventory_after_loading(self, flight_loads):
        """Update local inventory after loading kits"""
        for load in flight_loads:
            # We need to track which flight this is - simplified: just deduct
            pass  # Simplified: inventory tracked during load calculation
    
    def play_round(self, day, hour, flight_updates):
        """Play one round"""
        
        # Build flight loads
        flight_loads = []
        for flight in flight_updates:
            if flight['eventType'] in ['SCHEDULED', 'CHECKED_IN']:
                kits_to_load = self.calculate_safe_load(flight)
                
                # Update local inventory
                origin = flight['originAirport']
                for kt_api, kt_internal in [('first', 'FIRST'), ('business', 'BUSINESS'),
                                             ('premiumEconomy', 'PREMIUM_ECONOMY'), ('economy', 'ECONOMY')]:
                    loaded = kits_to_load[kt_api]
                    self.inventories[origin][kt_internal] -= loaded
                
                flight_loads.append({
                    'flightId': flight['flightId'],
                    'kitsLoaded': kits_to_load
                })
        
        # Simplified purchasing: buy 1000 of each type at HUB1 daily
        kit_orders = []
        if hour == 0 and day < 25:
            for kit_type in ['FIRST', 'BUSINESS', 'PREMIUM_ECONOMY', 'ECONOMY']:
                kit_orders.append({
                    'kitType': kit_type,
                    'quantity': 1000
                })
            
            # Add to HUB1 inventory (immediate for simplicity)
            for order in kit_orders:
                self.inventories['HUB1'][order['kitType']] += order['quantity']
        
        # Submit action
        headers = {**self.headers, 'SESSION-ID': self.session_id}
        
        action = {
            'day': day,
            'hour': hour,
            'flightLoads': flight_loads,
            'kitPurchasingOrders': kit_orders
        }
        
        response = requests.post(
            f'{self.base_url}/play/round',
            headers=headers,
            json=action
        )
        
        return response.json()
    
    def run(self):
        """Run full 30-day simulation"""
        print("\n" + "="*80)
        print("STARTING SIMPLE API SOLVER")
        print("="*80)
        
        # Start session
        self.start_session()
        
        # Initial round to get first flights
        headers = {**self.headers, 'SESSION-ID': self.session_id}
        action = {
            'day': 0,
            'hour': 0,
            'flightLoads': [],
            'kitPurchasingOrders': []
        }
        
        response = requests.post(
            f'{self.base_url}/play/round',
            headers=headers,
            json=action
        )
        
        api_response = response.json()
        
        # Start from day 0, hour 1 (already played hour 0)
        for round_num in range(1, 720):
            day = round_num // 24
            hour = round_num % 24
            
            flight_updates = api_response.get('flightUpdates', [])
            api_response = self.play_round(day, hour, flight_updates)
            
            total_cost = api_response.get('totalCost', 0)
            penalties = api_response.get('penalties', [])
            
            # Progress update every day
            if hour == 23:
                print(f"Day {day:2d}/29 | Cost: EUR {total_cost:>18,.2f} | Penalties: {len(penalties):3d}")
        
        # Final results
        print("\n" + "="*80)
        print("SIMULATION COMPLETE")
        print("="*80)
        print(f"Final Cost: EUR {total_cost:,.2f}")
        print(f"Session ID: {self.session_id}")
        print("="*80)
        
        return api_response


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python simple_api_solver.py <API_KEY> <BASE_URL>")
        print("Example: python simple_api_solver.py 43b9ab90-b593-404c-a8d8-aaa074e181e1 http://localhost:8080/api/v1")
        sys.exit(1)
    
    api_key = sys.argv[1]
    base_url = sys.argv[2]
    
    solver = SimpleAPISolver(api_key, base_url)
    result = solver.run()
