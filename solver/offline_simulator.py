"""
Offline Simulator for DQN Training
Mimics the API backend for fast training without network calls
"""

import csv
import random
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Any
import copy


class OfflineSimulator:
    """
    Fast offline simulator for DQN training
    Mimics API backend without network calls
    """
    
    def __init__(self, data_dir=None):
        print("Initializing Offline Simulator...")
        
        # Auto-detect data directory
        if data_dir is None:
            import os
            script_dir = os.path.dirname(os.path.abspath(__file__))
            data_dir = os.path.join(script_dir, '..', 'eval-platform', 'src', 'main', 'resources', 'liquibase', 'data')
            data_dir = os.path.abspath(data_dir)
        
        # Load static data
        self.airports = self.load_airports(f'{data_dir}/airports_with_stocks.csv')
        self.aircraft_types = self.load_aircraft_types(f'{data_dir}/aircraft_types.csv')
        self.flight_schedule = self.load_flight_schedule(f'{data_dir}/flight_plan.csv')
        
        # Map airport IDs for easier lookup
        self.airport_codes = list(self.airports.keys())
        
        # Kit types
        self.kit_types = ['FIRST', 'BUSINESS', 'PREMIUM_ECONOMY', 'ECONOMY']
        
        # Penalty factors (from PenaltyFactors.java)
        self.NEGATIVE_INVENTORY_FACTOR = 5000.0
        self.OVER_CAPACITY_FACTOR = 100.0
        self.FLIGHT_OVERLOAD_FACTOR = 10.0
        self.UNFULFILLED_PASSENGERS_FACTOR = 5.0
        self.INCORRECT_FLIGHT_LOAD_FACTOR = 10000.0
        self.END_OF_GAME_REMAINING_STOCK_FACTOR = 1.0
        self.END_OF_GAME_PENDING_KIT_PROCESSING_FACTOR = 0.001
        self.END_OF_GAME_UNFULFILLED_FLIGHT_KITS = 10.0
        self.EARLY_END_OF_GAME = 10.0
        
        # Kit costs and weights
        self.kit_info = {
            'FIRST': {'cost': 150.0, 'weight': 5.0},
            'BUSINESS': {'cost': 100.0, 'weight': 4.0},
            'PREMIUM_ECONOMY': {'cost': 75.0, 'weight': 3.0},
            'ECONOMY': {'cost': 50.0, 'weight': 2.0}
        }
        
        # Lead time for kit purchases (hours)
        self.PURCHASE_LEAD_TIME = 24
        
        print(f"Loaded {len(self.airports)} airports")
        print(f"Loaded {len(self.aircraft_types)} aircraft types")
        print(f"Loaded {len(self.flight_schedule)} scheduled flights")
        
        self.reset()
    
    def load_airports(self, filepath):
        """Load airport data from CSV"""
        airports = {}
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                code = row['code']
                airports[code] = {
                    'code': code,
                    'name': row['name'],
                    'isHub': code == 'HUB1',  # Only HUB1 is the hub
                    'capacity': {
                        'FIRST': int(row['capacity_fc']),
                        'BUSINESS': int(row['capacity_bc']),
                        'PREMIUM_ECONOMY': int(row['capacity_pe']),
                        'ECONOMY': int(row['capacity_ec'])
                    },
                    'loadingCost': {
                        'FIRST': float(row['first_loading_cost']),
                        'BUSINESS': float(row['business_loading_cost']),
                        'PREMIUM_ECONOMY': float(row['premium_economy_loading_cost']),
                        'ECONOMY': float(row['economy_loading_cost'])
                    },
                    'processingCost': {
                        'FIRST': float(row['first_processing_cost']),
                        'BUSINESS': float(row['business_processing_cost']),
                        'PREMIUM_ECONOMY': float(row['premium_economy_processing_cost']),
                        'ECONOMY': float(row['economy_processing_cost'])
                    },
                    'processingTime': {
                        'FIRST': int(row['first_processing_time']),
                        'BUSINESS': int(row['business_processing_time']),
                        'PREMIUM_ECONOMY': int(row['premium_economy_processing_time']),
                        'ECONOMY': int(row['economy_processing_time'])
                    },
                    'initialStock': {
                        'FIRST': int(row['initial_fc_stock']),
                        'BUSINESS': int(row['initial_bc_stock']),
                        'PREMIUM_ECONOMY': int(row['initial_pe_stock']),
                        'ECONOMY': int(row['initial_ec_stock'])
                    }
                }
        return airports
    
    def load_aircraft_types(self, filepath):
        """Load aircraft type data from CSV"""
        aircraft = {}
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                code = row['type_code']
                aircraft[code] = {
                    'code': code,
                    'name': code,
                    'seats': {
                        'FIRST': int(row['first_class_seats']),
                        'BUSINESS': int(row['business_seats']),
                        'PREMIUM_ECONOMY': int(row['premium_economy_seats']),
                        'ECONOMY': int(row['economy_seats'])
                    },
                    'kitCapacity': {
                        'FIRST': int(row['first_class_kits_capacity']),
                        'BUSINESS': int(row['business_kits_capacity']),
                        'PREMIUM_ECONOMY': int(row['premium_economy_kits_capacity']),
                        'ECONOMY': int(row['economy_kits_capacity'])
                    },
                    'fuelCostPerKm': float(row['cost_per_kg_per_km'])
                }
        return aircraft
    
    def load_flight_schedule(self, filepath):
        """Load flight schedule from CSV (routes and timing, no specific flights)"""
        routes = []
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                # Parse which days of week this route operates
                days_of_week = []
                for i, day in enumerate(['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']):
                    if row[day] == '1':
                        days_of_week.append(i)
                
                route = {
                    'origin': row['depart_code'],
                    'destination': row['arrival_code'],
                    'scheduledHour': int(row['scheduled_hour']),
                    'scheduledArrivalHour': int(row['scheduled_arrival_hour']),
                    'arrivalNextDay': int(row['arrival_next_day']),
                    'distance': float(row['distance_km']),
                    'daysOfWeek': days_of_week  # 0=Monday, 6=Sunday
                }
                routes.append(route)
        return routes
    
    def reset(self):
        """Start new simulation episode"""
        self.day = 0
        self.hour = 0
        self.total_cost = 0
        self.round_costs = []
        
        # Initialize inventories with starting stocks
        self.inventories = {}
        for code, airport in self.airports.items():
            self.inventories[code] = copy.deepcopy(airport['initialStock'])
        
        # In-processing kits (will be available after processing time)
        self.in_processing = {}
        for code in self.airports:
            self.in_processing[code] = {kt: 0 for kt in self.kit_types}
        
        # Kit movements queue (delivery time, airport, kit_type, quantity, is_addition)
        self.kit_movements = []
        
        # Generated flights (instances from schedule)
        self.flights = []
        self.flight_id_counter = 0
        self.flight_number_counter = 1000  # Start at AB1000
        
        # Penalties accumulator
        self.penalties = []
        
        print(f"\n{'='*60}")
        print(f"SIMULATION RESET - Day {self.day}, Hour {self.hour}")
        print(f"{'='*60}")
        
        return self.get_api_response()
    
    def generate_flight_number(self):
        """Generate sequential flight number"""
        num = f"AB{self.flight_number_counter}"
        self.flight_number_counter += 1
        return num
    
    def should_route_operate(self, route, day):
        """Check if route operates on given day based on day of week"""
        # Simple: assume routes operate on specified days within first week,
        # then repeat pattern every 7 days
        day_of_week = day % 7
        return day_of_week in route['daysOfWeek']
    
    def generate_flights_for_day(self, day):
        """Generate flight instances from schedule for a specific day"""
        # Get random aircraft type for variety
        aircraft_type_codes = list(self.aircraft_types.keys())
        
        for route in self.flight_schedule:
            # Check if route operates on this day
            if not self.should_route_operate(route, day):
                continue
            
            # Pick random aircraft for this flight
            aircraft_code = random.choice(aircraft_type_codes)
            aircraft = self.aircraft_types[aircraft_code]
            
            # Generate random passenger loads (70-100% of seats)
            passengers = {}
            for kt in self.kit_types:
                max_seats = aircraft['seats'][kt]
                if max_seats > 0:
                    passengers[kt] = random.randint(int(max_seats * 0.7), max_seats)
                else:
                    passengers[kt] = 0
            
            # Add some variability to distance (±5%)
            distance = route['distance'] * random.uniform(0.95, 1.05)
            
            # Calculate arrival day
            arr_day = day + route['arrivalNextDay']
            
            # Create flight instance
            flight = {
                'flightId': f"FLT_{self.flight_id_counter}",
                'flightNumber': self.generate_flight_number(),
                'origin': route['origin'],
                'destination': route['destination'],
                'scheduledDeparture': {'day': day, 'hour': route['scheduledHour']},
                'scheduledArrival': {'day': arr_day, 'hour': route['scheduledArrivalHour']},
                'actualDeparture': None,  # Set at check-in
                'actualArrival': None,  # Set at check-in (with delays)
                'plannedPassengers': passengers,
                'actualPassengers': passengers,  # Same for simplicity
                'distance': distance,
                'aircraftType': aircraft_code,
                'status': 'PENDING',  # PENDING -> SCHEDULED -> CHECKED_IN -> LANDED
                'kitsLoaded': {kt: 0 for kt in self.kit_types}
            }
            
            self.flights.append(flight)
            self.flight_id_counter += 1
    
    def get_api_response(self):
        """
        Generate API response for current round
        Mimics the structure of PlayRoundResponse
        """
        # Generate flights for upcoming days if needed
        if self.hour == 0:
            # Generate flights for current day + 1 (so we see them 24h ahead)
            self.generate_flights_for_day(self.day + 1)
        
        # Update flight statuses
        flight_updates = []
        
        for flight in self.flights:
            if flight['status'] == 'LANDED':
                continue  # Already processed
            
            dep_day = flight['scheduledDeparture']['day']
            dep_hour = flight['scheduledDeparture']['hour']
            arr_day = flight['scheduledArrival']['day']
            arr_hour = flight['scheduledArrival']['hour']
            
            # SCHEDULED: 24h before departure (when day/hour matches scheduled - 24h)
            if flight['status'] == 'PENDING':
                hours_until_departure = (dep_day - self.day) * 24 + (dep_hour - self.hour)
                if hours_until_departure <= 24 and hours_until_departure > 1:
                    flight['status'] = 'SCHEDULED'
                    flight_updates.append({
                        'eventType': 'SCHEDULED',
                        'flightId': flight['flightId'],
                        'flightNumber': flight['flightNumber'],
                        'originAirport': flight['origin'],
                        'destinationAirport': flight['destination'],
                        'departure': flight['scheduledDeparture'],
                        'arrival': flight['scheduledArrival'],
                        'passengers': flight['plannedPassengers'],
                        'aircraftType': flight['aircraftType']
                    })
            
            # CHECKED_IN: 1h before departure
            elif flight['status'] == 'SCHEDULED':
                hours_until_departure = (dep_day - self.day) * 24 + (dep_hour - self.hour)
                if hours_until_departure <= 1:
                    # Add small delays (0-2 hours, 30% chance)
                    delay = random.randint(0, 2) if random.random() < 0.3 else 0
                    actual_dep_hour = dep_hour + delay
                    actual_dep_day = dep_day
                    while actual_dep_hour >= 24:
                        actual_dep_hour -= 24
                        actual_dep_day += 1
                    
                    # Calculate actual arrival
                    flight_duration = (arr_day - dep_day) * 24 + (arr_hour - dep_hour)
                    actual_arr_hour = actual_dep_hour + flight_duration
                    actual_arr_day = actual_dep_day
                    while actual_arr_hour >= 24:
                        actual_arr_hour -= 24
                        actual_arr_day += 1
                    
                    flight['actualDeparture'] = {'day': actual_dep_day, 'hour': actual_dep_hour}
                    flight['actualArrival'] = {'day': actual_arr_day, 'hour': actual_arr_hour}
                    flight['status'] = 'CHECKED_IN'
                    
                    flight_updates.append({
                        'eventType': 'CHECKED_IN',
                        'flightId': flight['flightId'],
                        'flightNumber': flight['flightNumber'],
                        'originAirport': flight['origin'],
                        'destinationAirport': flight['destination'],
                        'departure': flight['actualDeparture'],
                        'arrival': flight['actualArrival'],
                        'passengers': flight['actualPassengers'],
                        'aircraftType': flight['aircraftType']
                    })
            
            # LANDED: at arrival time
            elif flight['status'] == 'CHECKED_IN':
                if flight['actualArrival']:
                    if self.day == flight['actualArrival']['day'] and self.hour == flight['actualArrival']['hour']:
                        flight['status'] = 'LANDED'
                        
                        flight_updates.append({
                            'eventType': 'LANDED',
                            'flightId': flight['flightId'],
                            'flightNumber': flight['flightNumber'],
                            'originAirport': flight['origin'],
                            'destinationAirport': flight['destination'],
                            'departure': flight['actualDeparture'],
                            'arrival': flight['actualArrival'],
                            'distance': flight['distance'],
                            'passengers': flight['actualPassengers'],
                            'aircraftType': flight['aircraftType']
                        })
        
        return {
            'day': self.day,
            'hour': self.hour,
            'flightUpdates': flight_updates,
            'penalties': [],  # Will be populated by step()
            'totalCost': self.total_cost,
            'inventories': copy.deepcopy(self.inventories),
            'inProcessing': copy.deepcopy(self.in_processing)
        }
    
    def step(self, action):
        """
        Execute one hour of simulation
        action: {'flightLoads': [...], 'kitOrders': [...]}
        Returns: (next_state, reward, done, info)
        """
        round_cost = 0
        round_penalties = []
        
        # 1. Apply flight loads
        flight_loads = action.get('flightLoads', [])
        for load in flight_loads:
            cost, penalty = self.apply_flight_load(load)
            round_cost += cost
            if penalty:
                round_penalties.append(penalty)
        
        # 2. Apply kit orders (purchases at HUB)
        kit_orders = action.get('kitOrders', [])
        for order in kit_orders:
            cost = self.apply_kit_order(order)
            round_cost += cost
        
        # 3. Process kit movements (deliveries, arrivals)
        self.process_movements()
        
        # 4. Check inventory boundaries and apply penalties
        boundary_penalties = self.check_inventory_boundaries()
        for penalty in boundary_penalties:
            round_cost += penalty['amount']
            round_penalties.append(penalty)
        
        # 5. Create movements for landing flights
        self.create_landing_movements()
        
        # 6. Accumulate cost
        self.total_cost += round_cost
        self.round_costs.append(round_cost)
        self.penalties.extend(round_penalties)
        
        # 7. Advance time
        self.hour += 1
        if self.hour >= 24:
            self.hour = 0
            self.day += 1
        
        # 8. Check if done
        done = (self.day >= 30)
        
        if done:
            # Apply end-of-game penalties
            eog_penalties = self.calculate_end_of_game_penalties()
            for penalty in eog_penalties:
                self.total_cost += penalty['amount']
                round_penalties.append(penalty)
        
        # 9. Get next state
        next_state = self.get_api_response()
        next_state['penalties'] = round_penalties
        
        # **Enhanced reward function: heavily penalize constraint violations**
        # Base reward = negative cost
        reward = -round_cost
        
        # Apply massive negative rewards for constraint violations
        # This teaches the agent to avoid penalties at all costs
        for penalty in round_penalties:
            code = penalty.get('code', '')
            
            if code == 'NEGATIVE_INVENTORY':
                # Critical: 10K penalty per violation
                reward -= 10000
            elif code == 'UNFULFILLED_PASSENGERS':
                # High priority: 5K penalty
                reward -= 5000
            elif code == 'PLANE_OVERLOAD':
                # High priority: 5K penalty
                reward -= 5000
            elif code == 'END_OF_GAME_UNFULFILLED_FLIGHT_KITS':
                # Catastrophic: 50K penalty
                reward -= 50000
            elif code == 'OVER_CAPACITY':
                # Medium priority: 1K penalty
                reward -= 1000
            elif code == 'INCORRECT_FLIGHT_LOAD':
                # Critical: 10K penalty
                reward -= 10000
        
        # Bonus for maintaining healthy state (no penalties)
        if len(round_penalties) == 0:
            reward += 1000  # +1K bonus for clean hour
        
        # Progressive bonus: better to avoid penalties early
        if len(round_penalties) == 0 and self.day < 20:
            reward += 500  # Extra bonus for early prevention
        
        info = {
            'day': self.day,
            'hour': self.hour,
            'round_cost': round_cost,
            'total_cost': self.total_cost,
            'penalties': round_penalties
        }
        
        return next_state, reward, done, info
    
    def apply_flight_load(self, load):
        """Apply kit loading to a flight"""
        flight_id = load['flightId']
        kits_loaded = load['kitsLoaded']
        
        # Find flight
        flight = None
        for f in self.flights:
            if f['flightId'] == flight_id:
                flight = f
                break
        
        if not flight:
            # Invalid flight penalty
            penalty = {
                'code': 'INCORRECT_FLIGHT_LOAD',
                'amount': self.INCORRECT_FLIGHT_LOAD_FACTOR,
                'reason': f"Invalid flight ID: {flight_id}"
            }
            return 0, penalty
        
        # Check if flight is at correct status
        if flight['status'] not in ['SCHEDULED', 'CHECKED_IN']:
            penalty = {
                'code': 'INCORRECT_FLIGHT_LOAD',
                'amount': self.INCORRECT_FLIGHT_LOAD_FACTOR,
                'reason': f"Flight {flight_id} already departed/landed"
            }
            return 0, penalty
        
        # Calculate loading costs
        origin = flight['origin']
        cost = 0
        
        for kit_type in self.kit_types:
            quantity = kits_loaded.get(self.kit_type_to_api(kit_type), 0)
            if quantity > 0:
                # Loading cost
                cost += quantity * self.airports[origin]['loadingCost'][kit_type]
                
                # Deduct from inventory
                self.inventories[origin][kit_type] -= quantity
                
                # Store loaded kits
                flight['kitsLoaded'][kit_type] = quantity
        
        return cost, None
    
    def apply_kit_order(self, order):
        """Apply kit purchase order at HUB"""
        kit_type = order['kitType']
        quantity = order['quantity']
        
        # Purchase cost
        cost = quantity * self.kit_info[kit_type]['cost']
        
        # Schedule delivery after lead time
        delivery_hour = self.hour + self.PURCHASE_LEAD_TIME
        delivery_day = self.day
        while delivery_hour >= 24:
            delivery_hour -= 24
            delivery_day += 1
        
        self.kit_movements.append({
            'delivery_day': delivery_day,
            'delivery_hour': delivery_hour,
            'airport': 'HUB1',
            'kit_type': kit_type,
            'quantity': quantity,
            'is_addition': True
        })
        
        return cost
    
    def process_movements(self):
        """Process kit movements scheduled for current time"""
        executed = []
        
        for i, movement in enumerate(self.kit_movements):
            if movement['delivery_day'] == self.day and movement['delivery_hour'] == self.hour:
                airport = movement['airport']
                kit_type = movement['kit_type']
                quantity = movement['quantity']
                
                if movement['is_addition']:
                    self.inventories[airport][kit_type] += quantity
                else:
                    # Kits coming out of processing
                    self.in_processing[airport][kit_type] -= quantity
                    self.inventories[airport][kit_type] += quantity
                
                executed.append(i)
        
        # Remove executed movements
        for i in reversed(executed):
            del self.kit_movements[i]
    
    def create_landing_movements(self):
        """Create kit movements for flights landing at current time"""
        for flight in self.flights:
            if flight['status'] == 'LANDED':
                if flight['actualArrival']['day'] == self.day and flight['actualArrival']['hour'] == self.hour:
                    # Process kits at destination
                    dest = flight['destination']
                    
                    for kit_type in self.kit_types:
                        quantity = flight['kitsLoaded'][kit_type]
                        if quantity > 0:
                            # Put in processing
                            self.in_processing[dest][kit_type] += quantity
                            
                            # Schedule availability after processing time
                            processing_time = self.airports[dest]['processingTime'][kit_type]
                            ready_hour = self.hour + processing_time
                            ready_day = self.day
                            while ready_hour >= 24:
                                ready_hour -= 24
                                ready_day += 1
                            
                            self.kit_movements.append({
                                'delivery_day': ready_day,
                                'delivery_hour': ready_hour,
                                'airport': dest,
                                'kit_type': kit_type,
                                'quantity': quantity,
                                'is_addition': False  # Coming out of processing
                            })
    
    def check_inventory_boundaries(self):
        """Check for inventory violations and return penalties"""
        penalties = []
        
        for airport_code, inventory in self.inventories.items():
            airport = self.airports[airport_code]
            
            for kit_type in self.kit_types:
                available = inventory[kit_type]
                capacity = airport['capacity'][kit_type]
                
                # Negative inventory (understock)
                if available < 0:
                    penalty_amount = self.NEGATIVE_INVENTORY_FACTOR * abs(available)
                    penalties.append({
                        'code': 'NEGATIVE_INVENTORY',
                        'amount': penalty_amount,
                        'reason': f"Negative inventory at {airport_code} for {kit_type}: {available}"
                    })
                
                # Over capacity (overstock)
                if available > capacity:
                    excess = available - capacity
                    penalty_amount = self.OVER_CAPACITY_FACTOR * excess
                    penalties.append({
                        'code': 'OVER_CAPACITY',
                        'amount': penalty_amount,
                        'reason': f"Over capacity at {airport_code} for {kit_type}: {available}/{capacity}"
                    })
        
        return penalties
    
    def calculate_end_of_game_penalties(self):
        """Calculate penalties at end of simulation"""
        penalties = []
        
        # 1. Remaining stocks
        for airport_code, inventory in self.inventories.items():
            for kit_type in self.kit_types:
                available = inventory[kit_type]
                if available != 0:
                    if available < 0:
                        penalty_amount = abs(available) * self.NEGATIVE_INVENTORY_FACTOR
                    else:
                        penalty_amount = available * self.END_OF_GAME_REMAINING_STOCK_FACTOR
                    
                    penalties.append({
                        'code': 'END_OF_GAME_REMAINING_STOCK',
                        'amount': penalty_amount,
                        'reason': f"Remaining stock at {airport_code} for {kit_type}: {available}"
                    })
        
        # 2. In-processing kits
        for airport_code, processing in self.in_processing.items():
            for kit_type in self.kit_types:
                quantity = processing[kit_type]
                if quantity > 0:
                    penalty_amount = quantity * self.kit_info[kit_type]['cost'] * self.END_OF_GAME_PENDING_KIT_PROCESSING_FACTOR
                    penalties.append({
                        'code': 'END_OF_GAME_PENDING_KIT_PROCESSING',
                        'amount': penalty_amount,
                        'reason': f"Kits in processing at {airport_code} for {kit_type}: {quantity}"
                    })
        
        # 3. Unfulfilled flights
        for flight in self.flights:
            if flight['status'] in ['SCHEDULED', 'CHECKED_IN']:
                # Flight didn't depart or land
                total_penalty = 0
                for kit_type in self.kit_types:
                    planned = flight['plannedPassengers'][kit_type]
                    kit_cost = self.kit_info[kit_type]['cost']
                    kit_weight = self.kit_info[kit_type]['weight']
                    
                    penalty_amount = self.END_OF_GAME_UNFULFILLED_FLIGHT_KITS * flight['distance'] * planned * kit_cost * kit_weight
                    total_penalty += penalty_amount
                
                penalties.append({
                    'code': 'END_OF_GAME_UNFULFILLED_FLIGHT_KITS',
                    'amount': total_penalty,
                    'reason': f"Unfulfilled flight {flight['flightNumber']}"
                })
        
        return penalties
    
    def kit_type_to_api(self, kit_type):
        """Convert internal kit type to API format"""
        mapping = {
            'FIRST': 'first',
            'BUSINESS': 'business',
            'PREMIUM_ECONOMY': 'premiumEconomy',
            'ECONOMY': 'economy'
        }
        return mapping.get(kit_type, kit_type)
    
    def get_state(self):
        """Get current state for DQN (to be implemented in training script)"""
        return self.get_api_response()


# Test simulator
if __name__ == "__main__":
    print("Testing Offline Simulator...")
    
    sim = OfflineSimulator()
    
    # Test basic flow
    state = sim.reset()
    print(f"\nInitial state: Day {state['day']}, Hour {state['hour']}")
    print(f"Flight updates: {len(state['flightUpdates'])}")
    print(f"HUB1 inventory: {sim.inventories['HUB1']}")
    
    # Run a few steps
    for i in range(48):  # 2 days
        # Dummy action - just load flights with available kits
        action = {'flightLoads': [], 'kitOrders': []}
        
        # Add a purchase order on hour 0
        if sim.hour == 0:
            action['kitOrders'] = [
                {'kitType': 'ECONOMY', 'quantity': 1000},
                {'kitType': 'BUSINESS', 'quantity': 500}
            ]
        
        next_state, reward, done, info = sim.step(action)
        
        if info['round_cost'] > 0:
            print(f"Day {info['day']}, Hour {info['hour']}: Cost={info['round_cost']:,.2f}, Total={info['total_cost']:,.2f}")
        
        if done:
            print("\nSimulation complete!")
            break
    
    print(f"\nFinal total cost: EUR {sim.total_cost:,.2f}")
    print(f"Total penalties: {len(sim.penalties)}")
