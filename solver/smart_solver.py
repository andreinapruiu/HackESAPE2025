"""
Smart Rule-Based Solver for Kit Management
Explicitly handles all constraints to minimize penalties
"""

import requests
import json
from collections import defaultdict

class SmartSolver:
    """
    Rule-based solver that prioritizes constraint satisfaction:
    1. Never cause negative inventory
    2. Always load at least passenger count (avoid unfulfilled)
    3. Never exceed aircraft capacity (avoid overload)
    4. Purchase proactively based on 3-day demand forecast
    """
    
    def __init__(self, api_key, base_url):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {'API-KEY': api_key}
        self.session_id = None
        
        # Load initial inventory from CSV
        import os
        script_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(script_dir, '..', 'eval-platform', 'src', 'main', 'resources', 'liquibase', 'data')
        data_dir = os.path.abspath(data_dir)
        
        airports = self.load_airports_csv(f'{data_dir}/airports_with_stocks.csv')
        
        # Initialize local inventory tracking
        self.inventories = {}
        self.in_processing = {}
        for code, airport in airports.items():
            self.inventories[code] = airport['initial_stock'].copy()
            self.in_processing[code] = {'FIRST': 0, 'BUSINESS': 0, 'PREMIUM_ECONOMY': 0, 'ECONOMY': 0}
        
        # Aircraft capacities (from data)
        self.aircraft_capacities = {
            'OJF294': {'FIRST': 12, 'BUSINESS': 28, 'PREMIUM_ECONOMY': 21, 'ECONOMY': 178},
            'OJF206': {'FIRST': 14, 'BUSINESS': 32, 'PREMIUM_ECONOMY': 18, 'ECONOMY': 210},
            'OJF178': {'FIRST': 0, 'BUSINESS': 24, 'PREMIUM_ECONOMY': 24, 'ECONOMY': 132},
            'OJF156': {'FIRST': 8, 'BUSINESS': 16, 'PREMIUM_ECONOMY': 18, 'ECONOMY': 91}
        }
        
        print("Smart Solver initialized")
    
    def load_airports_csv(self, filepath):
        """Load airports with initial stocks from CSV"""
        import csv
        airports = {}
        with open(filepath, 'r') as f:
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
        response = requests.post(
            f'{self.base_url}/session/start',
            headers=self.headers
        )
        session_id_str = response.text.strip('"')  # Response is just the UUID string
        self.session_id = session_id_str
        print(f"Session started: {self.session_id}")
        
        # Get initial state by playing round 0
        return self.play_round_initial()
    
    def play_round_initial(self):
        """Get initial game state (day 0, hour 0)"""
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
        
        return response.json()
    
    def forecast_demand(self, flight_updates, days_ahead=3):
        """
        Forecast demand for next N days based on scheduled flights
        Returns: {airport: {kit_type: count}}
        """
        demand = defaultdict(lambda: defaultdict(int))
        
        for flight in flight_updates:
            if flight['eventType'] == 'SCHEDULED':
                origin = flight['originAirport']
                passengers = flight['passengers']
                
                for kit_type in ['FIRST', 'BUSINESS', 'PREMIUM_ECONOMY', 'ECONOMY']:
                    demand[origin][kit_type] += passengers.get(kit_type, 0)
        
        return demand
    
    def calculate_safe_load(self, flight, inventories):
        """
        Calculate safe kit loading for a flight:
        - At least passengers (avoid UNFULFILLED_PASSENGERS)
        - At most aircraft capacity (avoid PLANE_OVERLOAD)
        - At most available inventory (avoid NEGATIVE_INVENTORY)
        """
        origin = flight['originAirport']
        passengers = flight['passengers']
        aircraft_type = flight.get('aircraftType', 'OJF294')
        capacity = self.aircraft_capacities.get(aircraft_type, {})
        
        kits_to_load = {}
        
        for kt_api, kt_internal in [('first', 'FIRST'), ('business', 'BUSINESS'),
                                     ('premiumEconomy', 'PREMIUM_ECONOMY'), ('economy', 'ECONOMY')]:
            passenger_count = passengers.get(kt_internal, 0)
            aircraft_cap = capacity.get(kt_internal, passenger_count)
            available = inventories.get(origin, {}).get(kt_internal, 0)
            
            # RULE 1: Load at least passengers (avoid unfulfilled penalty)
            desired = passenger_count
            
            # RULE 2: Don't exceed aircraft capacity
            desired = min(desired, aircraft_cap)
            
            # RULE 3: Don't exceed available inventory
            desired = min(desired, available)
            
            # RULE 4: If insufficient inventory, load what we have (minimize penalty)
            # Better to partially fulfill than completely ignore
            kits_to_load[kt_api] = max(0, desired)
            
            # Update local inventory
            if origin in inventories:
                inventories[origin][kt_internal] -= kits_to_load[kt_api]
        
        return kits_to_load
    
    def calculate_purchase_needs(self, inventories, demand_forecast, day, in_processing):
        """
        Calculate kit purchase needs based on:
        - Current inventory levels
        - 3-day demand forecast
        - In-processing kits (arriving soon)
        - Lead time (24h until kits available)
        """
        kit_orders = []
        
        if day > 25:
            # Don't purchase late-game (avoid END_OF_GAME_REMAINING_STOCK penalty)
            return kit_orders
        
        # Aggregate global demand and inventory
        total_demand = defaultdict(int)
        total_inventory = defaultdict(int)
        total_in_processing = defaultdict(int)
        
        for airport in demand_forecast:
            for kit_type in ['FIRST', 'BUSINESS', 'PREMIUM_ECONOMY', 'ECONOMY']:
                total_demand[kit_type] += demand_forecast[airport][kit_type]
        
        for airport in inventories:
            for kit_type in ['FIRST', 'BUSINESS', 'PREMIUM_ECONOMY', 'ECONOMY']:
                total_inventory[kit_type] += inventories[airport].get(kit_type, 0)
        
        for airport in in_processing:
            for kit_type in ['FIRST', 'BUSINESS', 'PREMIUM_ECONOMY', 'ECONOMY']:
                total_in_processing[kit_type] += in_processing[airport].get(kit_type, 0)
        
        # Purchase strategy: maintain 3-day buffer
        for kit_type in ['FIRST', 'BUSINESS', 'PREMIUM_ECONOMY', 'ECONOMY']:
            forecast = total_demand[kit_type]
            current = total_inventory[kit_type]
            incoming = total_in_processing[kit_type]
            
            # Calculate shortage
            available = current + incoming
            shortage = forecast - available
            
            # Add safety buffer (20%)
            purchase_qty = int(shortage * 1.2)
            
            # Purchase in reasonable batches
            if purchase_qty > 100:
                kit_orders.append({
                    'kitType': kit_type,
                    'quantity': purchase_qty
                })
        
        return kit_orders
    
    def play_round(self, day, hour, flight_updates):
        """
        Play one round (1 hour) with smart rule-based decisions
        """
        # Forecast demand
        demand_forecast = self.forecast_demand(flight_updates, days_ahead=3)
        
        # Build flight loads (constraint-aware)
        flight_loads = []
        for flight in flight_updates:
            if flight['eventType'] in ['SCHEDULED', 'CHECKED_IN']:
                kits_to_load = self.calculate_safe_load(flight, self.inventories)
                
                flight_loads.append({
                    'flightId': flight['flightId'],
                    'kitsLoaded': kits_to_load
                })
        
        # Build kit orders (proactive purchasing)
        kit_orders = []
        if hour == 0:  # Purchase once per day
            kit_orders = self.calculate_purchase_needs(self.inventories, demand_forecast, day, self.in_processing)
            
            # Update local inventory (purchase delivered to HUB1 immediately for simplicity)
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
        print("STARTING SMART SOLVER")
        print("="*80)
        
        # Start session and get initial state
        api_response = self.start_session()
        
        print(f"Initial response: flights={len(api_response.get('flightUpdates', []))}, " +
              f"penalties={len(api_response.get('penalties', []))}, cost={api_response.get('totalCost', 0)}")
        
        # Play 720 rounds (30 days × 24 hours)
        for round_num in range(1, 720):
            day = round_num // 24
            hour = round_num % 24
            
            flight_updates = api_response.get('flightUpdates', [])
            
            # Debug: print flight info occasionally
            if hour == 0 and day % 5 == 0:
                print(f"\n[DEBUG] Day {day}, Hour {hour}: {len(flight_updates)} flights")
                if len(flight_updates) > 0:
                    print(f"  First flight: {flight_updates[0].get('flightId', 'N/A')}, " +
                          f"origin: {flight_updates[0].get('originAirport', 'N/A')}, " +
                          f"eventType: {flight_updates[0].get('eventType', 'N/A')}")
            
            api_response = self.play_round(day, hour, flight_updates)
            
            total_cost = api_response.get('totalCost', 0)
            penalties = api_response.get('penalties', [])
            
            # Debug: show penalties if any
            if len(penalties) > 0 and hour == 23:
                print(f"  [WARNING] {len(penalties)} penalties on day {day}")
            
            # Progress update every day
            if hour == 23:
                print(f"Day {day:2d}/29 | Cost: EUR {total_cost:>18,.2f} | Penalties: {len(penalties):3d}")
        
        # Final results
        total_cost = api_response.get('totalCost', 0)
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
        print("Usage: python smart_solver.py <API_KEY> <BASE_URL>")
        print("Example: python smart_solver.py 43b9ab90-b593-404c-a8d8-aaa074e181e1 http://localhost:8080/api/v1")
        sys.exit(1)
    
    api_key = sys.argv[1]
    base_url = sys.argv[2]
    
    solver = SmartSolver(api_key, base_url)
    result = solver.run()
