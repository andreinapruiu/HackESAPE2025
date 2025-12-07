"""
DQN Live Player - Use trained DQN model with live backend API
"""

import requests
import json
import numpy as np
import torch
from collections import defaultdict
import sys
import os

# Add parent directory to path to import DQN modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dqn_agent import DQNAgent, StateEncoder, ActionSpace

class DQNLivePlayer:
    """
    Plays the game using a trained DQN model against the live backend
    """
    
    def __init__(self, api_key, base_url, model_path):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {'API-KEY': api_key}
        self.session_id = None
        
        # Load airports and flights
        script_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(script_dir, '..', 'eval-platform', 'src', 'main', 'resources', 'liquibase', 'data')
        data_dir = os.path.abspath(data_dir)
        
        self.airports = self.load_airports_csv(f'{data_dir}/airports_with_stocks.csv')
        self.flights = self.load_flights_csv(f'{data_dir}/flights.csv')
        
        # Initialize DQN components
        self.state_encoder = StateEncoder(self.airports)
        self.action_space = ActionSpace()
        
        # Create agent and load trained model
        self.agent = DQNAgent(
            airports=self.airports,
            state_dim=800,  # Must match training
            learning_rate=0.0001
        )
        
        # Note: New fine-tuned model has 135 actions (9x5x3) instead of 54
        print(f"Agent initialized with {len(self.agent.action_space.actions)} actions")
        
        # Load trained model
        print(f"Loading trained model from: {model_path}")
        checkpoint = torch.load(model_path, map_location=self.agent.device, weights_only=False)
        self.agent.q_network.load_state_dict(checkpoint['q_network'])
        self.agent.q_network.eval()
        print(f"Model loaded successfully! Epsilon: {checkpoint.get('epsilon', 'unknown')}")
        
        # Initialize game state tracking
        self.inventories = {}
        self.in_processing = defaultdict(lambda: defaultdict(int))
        
        for code, airport in self.airports.items():
            self.inventories[code] = airport['initial_stock'].copy()
        
        print("DQN Live Player initialized")
    
    def load_airports_csv(self, filepath):
        """Load airports with initial stocks"""
        import csv
        airports = {}
        with open(filepath, 'r') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                code = row['code']
                airports[code] = {
                    'code': code,
                    'id': row['id'],
                    'initial_stock': {
                        'FIRST': int(row['initial_fc_stock']),
                        'BUSINESS': int(row['initial_bc_stock']),
                        'PREMIUM_ECONOMY': int(row['initial_pe_stock']),
                        'ECONOMY': int(row['initial_ec_stock'])
                    },
                    'capacity': {
                        'FIRST': int(row['capacity_fc']),
                        'BUSINESS': int(row['capacity_bc']),
                        'PREMIUM_ECONOMY': int(row['capacity_pe']),
                        'ECONOMY': int(row['capacity_ec'])
                    }
                }
        print(f"Loaded {len(airports)} airports")
        return airports
    
    def load_flights_csv(self, filepath):
        """Load flights data"""
        import csv
        flights = []
        with open(filepath, 'r') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                flights.append({
                    'id': row['id'],
                    'flight_number': row['flight_number'],
                    'origin_airport_id': row['origin_airport_id'],
                    'destination_airport_id': row['destination_airport_id'],
                    'scheduled_depart_day': int(row['scheduled_depart_day']),
                    'scheduled_depart_hour': int(row['scheduled_depart_hour']),
                    'actual_arrival_day': int(row['actual_arival_day']),
                    'actual_arrival_hour': int(row['actual_arrival_hour']),
                    'passengers': {
                        'FIRST': int(row['actual_first_passengers']),
                        'BUSINESS': int(row['actual_business_passengers']),
                        'PREMIUM_ECONOMY': int(row['actual_premium_economy_passengers']),
                        'ECONOMY': int(row['actual_economy_passengers'])
                    }
                })
        print(f"Loaded {len(flights)} flights")
        return flights
    
    def forecast_airport_demand(self, day, lookahead_days=3):
        """Forecast demand for next N days per airport based on flight schedule
        Returns: {airport: {'first': qty, 'business': qty, 'premiumEconomy': qty, 'economy': qty}}
        """
        demand = {}
        
        # Simple heuristic: look at all checked-in flights we've seen
        # In real scenario, we'd have flight schedule data
        # For now, use average demand per airport as proxy
        
        for airport in self.inventories.keys():
            if airport != 'HUB1':  # Focus on spoke airports
                # Estimate 2-3 flights per day from each spoke
                avg_flight_demand = {
                    'first': 50,
                    'business': 150, 
                    'premiumEconomy': 100,
                    'economy': 500
                }
                
                demand[airport] = {
                    'first': avg_flight_demand['first'] * lookahead_days,
                    'business': avg_flight_demand['business'] * lookahead_days,
                    'premiumEconomy': avg_flight_demand['premiumEconomy'] * lookahead_days,
                    'economy': avg_flight_demand['economy'] * lookahead_days
                }
        
        return demand
    
    def start_session(self):
        """Start new game session"""
        # End any existing session first
        try:
            response = requests.post(
                f'{self.base_url}/session/end',
                headers=self.headers,
                timeout=5
            )
            if response.status_code == 200:
                print("Ended previous session")
        except Exception as e:
            # No active session or error - that's fine
            pass
        
        response = requests.post(
            f'{self.base_url}/session/start',
            headers=self.headers
        )
        
        # Check response status
        if response.status_code != 200:
            try:
                error_data = response.json()
                print(f"Session start failed: {error_data}")
                raise Exception(f"Could not start session: {error_data.get('detail', 'Unknown error')}")
            except:
                raise Exception(f"Could not start session: HTTP {response.status_code}")
        
        # Success - response is plain text UUID
        session_id_str = response.text.strip('"')
        self.session_id = session_id_str
        print(f"Session started: {self.session_id}")
        
        # Get initial state by playing round 0
        return self.play_round_initial()
    
    def play_round_initial(self):
        """Get initial game state (day 0, hour 0)"""
        headers = {**self.headers, 'SESSION-ID': self.session_id}
        
        # API expects this exact structure
        action = {
            'day': 0,
            'hour': 0,
            'flightLoads': [],  # Empty array is valid
            'kitPurchasingOrders': {  # Must be object with these keys
                'first': 0,
                'business': 0,
                'premiumEconomy': 0,
                'economy': 0
            }
        }
        
        response = requests.post(
            f'{self.base_url}/play/round',
            headers=headers,
            json=action
        )
        
        api_response = response.json()
        print(f"DEBUG Raw API Response: {api_response}")
        print(f"DEBUG Initial Response: day={api_response.get('day')}, hour={api_response.get('hour')}, "
              f"flights={len(api_response.get('flightUpdates', []))}, "
              f"penalties={len(api_response.get('penalties', []))}, "
              f"cost={api_response.get('totalCost', 0)}")
        if len(api_response.get('flightUpdates', [])) > 0:
            print(f"  First flight: {api_response['flightUpdates'][0]}")
        
        return api_response
    
    def convert_api_response_to_state(self, api_response, day, hour):
        """Convert live API response to format expected by StateEncoder"""
        # Build state dict matching simulator format
        state_dict = {
            'day': day,
            'hour': hour,
            'inventories': self.inventories,
            'inProcessing': self.in_processing,
            'flightUpdates': api_response.get('flightUpdates', [])
        }
        
        # Encode to tensor
        state_vector = self.state_encoder.encode(state_dict)
        return torch.FloatTensor(state_vector).unsqueeze(0).to(self.agent.device)
    
    def calculate_flight_criticality(self, flight, day):
        """Calculate criticality score for dynamic loading decisions
        Higher score = more critical = load more aggressively
        """
        passengers = flight['passengers']
        total_pax = sum(passengers.values())
        distance = flight.get('distance', 3000)
        
        # Factor 1: Total passenger count (normalize to 0-1)
        pax_score = min(total_pax / 400, 1.0)  # 400+ passengers = max score
        
        # Factor 2: Premium passenger ratio (higher value customers)
        premium_pax = passengers.get('first', 0) + passengers.get('business', 0)
        premium_ratio = premium_pax / max(total_pax, 1)
        
        # Factor 3: Long-haul flights are more critical (higher penalty costs)
        distance_score = min(distance / 5000, 1.0)  # 5000km+ = max score
        
        # Factor 4: Late in game = more critical (end-of-game penalties)
        time_pressure = day / 29.0  # Increases towards game end
        
        # Combined criticality score (0.0 to 1.0)
        criticality = (
            0.35 * pax_score +          # 35% weight on passenger count
            0.25 * premium_ratio +      # 25% weight on premium passengers
            0.20 * distance_score +     # 20% weight on distance
            0.20 * time_pressure        # 20% weight on time pressure
        )
        
        return criticality
    
    def apply_action_to_flights(self, action_dict, current_flights):
        """Convert DQN action policy to actual flight loads with conservative 70% loading"""
        loading_policy = action_dict['loading_policy']
        flight_loads = []
        
        # Conservative 70% loading factor to reduce unfulfilled flights
        conservative_factor = 0.70
        
        for flight in current_flights:
            passengers = flight['passengers']
            flight_id = flight['flightId']
            origin = flight.get('originAirport', 'HUB1')
            
            # Calculate desired kits with conservative 70% loading
            desired_kits = {
                'first': int(passengers.get('first', 0) * loading_policy * conservative_factor),
                'business': int(passengers.get('business', 0) * loading_policy * conservative_factor),
                'premiumEconomy': int(passengers.get('premiumEconomy', 0) * loading_policy * conservative_factor),
                'economy': int(passengers.get('economy', 0) * loading_policy * conservative_factor)
            }
            
            # Ensure we don't load more than available inventory
            available_inv = self.inventories.get(origin, {})
            kits_to_load = {
                'first': min(desired_kits['first'], max(0, available_inv.get('FIRST', 0))),
                'business': min(desired_kits['business'], max(0, available_inv.get('BUSINESS', 0))),
                'premiumEconomy': min(desired_kits['premiumEconomy'], max(0, available_inv.get('PREMIUM_ECONOMY', 0))),
                'economy': min(desired_kits['economy'], max(0, available_inv.get('ECONOMY', 0)))
            }
            
            flight_loads.append({
                'flightId': flight_id,
                'loadedKits': kits_to_load
            })
            
            # Update local inventory
            origin = flight.get('originAirport', 'HUB1')
            if origin in self.inventories:
                self.inventories[origin]['FIRST'] -= kits_to_load['first']
                self.inventories[origin]['BUSINESS'] -= kits_to_load['business']
                self.inventories[origin]['PREMIUM_ECONOMY'] -= kits_to_load['premiumEconomy']
                self.inventories[origin]['ECONOMY'] -= kits_to_load['economy']
        
        return flight_loads
    
    def apply_action_to_purchases(self, action_dict, day, hour):
        """Convert DQN action policy to purchase orders with capacity awareness"""
        purchase_qty = action_dict['purchase_qty']
        purchase_frequency = action_dict['purchase_frequency']
        
        # API expects: {"first": 100, "business": 200, "premiumEconomy": 150, "economy": 500}
        kit_orders = {
            'first': 0,
            'business': 0,
            'premiumEconomy': 0,
            'economy': 0
        }
        
        # Check if we should purchase this hour
        should_purchase = False
        if purchase_frequency == 0:
            should_purchase = False
        elif purchase_frequency == 1:
            should_purchase = (hour == 0)  # Once per day
        elif purchase_frequency == 2:
            should_purchase = (hour == 0 or hour == 12)  # Twice per day
        
        if should_purchase and purchase_qty > 0:
            # Use 50% of DQN purchase quantity (balanced between demand and waste)
            reduced_qty = int(purchase_qty * 0.5)
            
            # Respect HUB1 capacity limits (assume ~4500 safe capacity per kit type)
            hub_inv = self.inventories.get('HUB1', {})
            capacity_limit = 4500
            
            # Calculate safe purchase amounts that won't exceed capacity
            kit_orders['first'] = min(reduced_qty, max(0, capacity_limit - hub_inv.get('FIRST', 0)))
            kit_orders['business'] = min(reduced_qty, max(0, capacity_limit - hub_inv.get('BUSINESS', 0)))
            kit_orders['premiumEconomy'] = min(reduced_qty, max(0, capacity_limit - hub_inv.get('PREMIUM_ECONOMY', 0)))
            kit_orders['economy'] = min(reduced_qty, max(0, capacity_limit - hub_inv.get('ECONOMY', 0)))
            
            # Update local inventory (purchases go to HUB1)
            self.inventories['HUB1']['FIRST'] += kit_orders['first']
            self.inventories['HUB1']['BUSINESS'] += kit_orders['business']
            self.inventories['HUB1']['PREMIUM_ECONOMY'] += kit_orders['premiumEconomy']
            self.inventories['HUB1']['ECONOMY'] += kit_orders['economy']
        
        return kit_orders
    
    def play_round_with_dqn(self, day, hour, flight_updates):
        """Play one round using DQN policy"""
        # Get flights from flight_updates (these are CHECKED_IN flights for this hour)
        checked_in_flights = [f for f in flight_updates 
                             if f.get('eventType') == 'CHECKED_IN']
        
        # Build API response format for state encoder
        api_response_for_state = {
            'day': day,
            'hour': hour,
            'inventories': self.inventories,
            'inProcessing': self.in_processing,
            'flightUpdates': flight_updates
        }
        
        # Get state
        state_tensor = self.convert_api_response_to_state(api_response_for_state, day, hour)
        
        # Get DQN action (no exploration, pure exploitation)
        with torch.no_grad():
            q_values = self.agent.q_network(state_tensor)
            action_idx = q_values.max(1)[1].item()
        
        # Get action dict
        action_dict = self.action_space.get_action_by_id(action_idx)
        
        # Convert to API actions
        flight_loads = self.apply_action_to_flights(action_dict, checked_in_flights)
        kit_orders = self.apply_action_to_purchases(action_dict, day, hour)
        
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
        """Run full 30-day simulation with DQN"""
        print("\n" + "="*80)
        print("STARTING DQN LIVE PLAYER")
        print("="*80)
        
        # Start session
        api_response = self.start_session()
        
        print(f"Initial response: flights={len(api_response.get('flightUpdates', []))}, " +
              f"penalties={len(api_response.get('penalties', []))}, cost={api_response.get('totalCost', 0)}")
        
        # Debug: print flight event types
        if len(api_response.get('flightUpdates', [])) > 0:
            event_types = {}
            for f in api_response.get('flightUpdates', []):
                et = f.get('eventType', 'UNKNOWN')
                event_types[et] = event_types.get(et, 0) + 1
            print(f"Flight event types in initial response: {event_types}")
        else:
            print("WARNING: No flights in initial response - backend may not be returning flights!")
        
        # KEY FIX: Initialize flight_updates from initial response for round 1
        # The API returns flights for the NEXT hour
        flight_updates = api_response.get('flightUpdates', [])
        
        # Play 720 rounds (30 days × 24 hours)
        # We already played round 0 (day 0 hour 0) with play_round_initial()
        # Now play rounds 1-719 (day 0 hour 1 through day 29 hour 23)
        for round_num in range(1, 720):
            day = round_num // 24
            hour = round_num % 24
            
            # Track current day for criticality-based loading
            self.current_day = day
            
            # Use flight_updates from PREVIOUS round's response
            # These are the flights happening at the current (day, hour)
            api_response = self.play_round_with_dqn(day, hour, flight_updates)
            
            total_cost = api_response.get('totalCost', 0)
            penalties = api_response.get('penalties', [])
            
            # Get flight updates for NEXT round
            flight_updates = api_response.get('flightUpdates', [])
            
            # Progress update every day
            if hour == 23:
                print(f"Day {day:2d}/29 | Cost: EUR {total_cost:>18,.2f} | Penalties: {len(penalties):3d}")
                
                # Log penalties with details
                if len(penalties) > 0:
                    penalty_types = {}
                    penalty_details = {}
                    
                    for p in penalties:
                        # Backend uses 'code' not 'type', 'penalty' not 'amount', 'reason' not 'description'
                        ptype = p.get('code', 'UNKNOWN')
                        penalty_types[ptype] = penalty_types.get(ptype, 0) + 1
                        
                        # Collect detailed penalty information
                        if ptype not in penalty_details:
                            penalty_details[ptype] = []
                        
                        detail = {
                            'amount': p.get('penalty', 0),
                            'description': p.get('reason', 'N/A'),
                        }
                        
                        # Add context-specific fields
                        if 'flightNumber' in p and p.get('flightNumber'):
                            detail['flight'] = p.get('flightNumber')
                        if 'airport' in p and p.get('airport'):
                            detail['airport'] = p.get('airport')
                        if 'kitType' in p and p.get('kitType'):
                            detail['kitType'] = p.get('kitType')
                            
                        penalty_details[ptype].append(detail)
                    
                    # Print summary
                    print(f"  Penalty breakdown: {penalty_types}")
                    
                    # Print details for first few penalties of each type (to avoid spam)
                    if day % 5 == 0 or day == 29:  # More detailed logging every 5 days and on last day
                        for ptype, details in penalty_details.items():
                            print(f"    {ptype}:")
                            for detail in details[:3]:  # Show first 3 examples
                                desc = detail.get('description', 'N/A')
                                amt = detail.get('amount', 0)
                                extra = []
                                if 'flight' in detail:
                                    extra.append(f"flight={detail['flight']}")
                                if 'airport' in detail:
                                    extra.append(f"airport={detail['airport']}")
                                if 'kitType' in detail:
                                    extra.append(f"kit={detail['kitType']}")
                                
                                extra_str = f" ({', '.join(extra)})" if extra else ""
                                print(f"      - {desc}{extra_str}: EUR {amt:,.2f}")
                            
                            if len(details) > 3:
                                print(f"      ... and {len(details) - 3} more")
        
        # Final results
        total_cost = api_response.get('totalCost', 0)
        final_penalties = api_response.get('penalties', [])
        
        # End session explicitly
        try:
            end_response = requests.post(
                f'{self.base_url}/session/end',
                headers=self.headers,
                timeout=5
            )
            if end_response.status_code == 200:
                print("\nSession ended successfully")
            elif end_response.status_code == 404:
                print("\nSession already ended by backend (game complete)")
            else:
                print(f"\nSession end returned status: {end_response.status_code}")
        except Exception as e:
            print(f"\nError ending session: {e}")
        
        # Print final penalty summary
        if len(final_penalties) > 0:
            print("\n" + "="*80)
            print("FINAL PENALTY ANALYSIS")
            print("="*80)
            
            penalty_types = {}
            penalty_amounts = {}
            
            for p in final_penalties:
                # Backend uses 'code' not 'type', 'penalty' not 'amount'
                ptype = p.get('code', 'UNKNOWN')
                amount = p.get('penalty', 0)
                
                penalty_types[ptype] = penalty_types.get(ptype, 0) + 1
                penalty_amounts[ptype] = penalty_amounts.get(ptype, 0) + amount
            
            print(f"Total penalties: {len(final_penalties)}")
            print("\nBreakdown by type:")
            for ptype in sorted(penalty_types.keys()):
                count = penalty_types[ptype]
                total_amt = penalty_amounts[ptype]
                avg_amt = total_amt / count if count > 0 else 0
                print(f"  {ptype}: {count} occurrences, EUR {total_amt:,.2f} total (avg EUR {avg_amt:,.2f})")
            
            # Show sample penalties
            print("\nSample penalties (first 10):")
            for i, p in enumerate(final_penalties[:10]):
                ptype = p.get('code', 'UNKNOWN')
                desc = p.get('reason', 'N/A')
                amt = p.get('penalty', 0)
                
                extra = []
                if 'flightNumber' in p and p.get('flightNumber'):
                    extra.append(f"flight={p['flightNumber']}")
                if 'airport' in p and p.get('airport'):
                    extra.append(f"airport={p['airport']}")
                if 'kitType' in p and p.get('kitType'):
                    extra.append(f"kit={p['kitType']}")
                
                extra_str = f" ({', '.join(extra)})" if extra else ""
                print(f"  {i+1}. {ptype}: {desc}{extra_str} - EUR {amt:,.2f}")
        
        print("\n" + "="*80)
        print("SIMULATION COMPLETE")
        print("="*80)
        print(f"Final Cost: EUR {total_cost:,.2f}")
        print(f"Session ID: {self.session_id}")
        print("="*80)
        
        return api_response


if __name__ == '__main__':
    if len(sys.argv) < 4:
        print("Usage: python dqn_live_player.py <API_KEY> <BASE_URL> <MODEL_PATH>")
        print("Example: python dqn_live_player.py 43b9ab90-b593-404c-a8d8-aaa074e181e1 http://localhost:8080/api/v1 dqn_best_model.pth")
        sys.exit(1)
    
    api_key = sys.argv[1]
    base_url = sys.argv[2]
    model_path = sys.argv[3]
    
    player = DQNLivePlayer(api_key, base_url, model_path)
    result = player.run()
