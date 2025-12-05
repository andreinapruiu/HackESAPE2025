"""
Stage 2 Solver for HackITAll 2025 - Rotables Challenge
Implements greedy algorithm with 24h lookahead, target stock levels, and kit repositioning
"""

import csv
import os
import requests
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from dataclasses import dataclass

# Import from simple_solver for API client and logging setup
from simple_solver import ApiClient, setup_logging, logger

# Kit type constants (from KitType.java)
KIT_TYPES = {
    'first': {'cost': 200.0, 'weight': 5.0, 'lead_time': 48},
    'business': {'cost': 150.0, 'weight': 3.0, 'lead_time': 36},
    'premiumEconomy': {'cost': 100.0, 'weight': 2.5, 'lead_time': 24},
    'economy': {'cost': 50.0, 'weight': 1.5, 'lead_time': 12}
}

CLASS_NAMES = ['first', 'business', 'premiumEconomy', 'economy']
CLASS_MAPPING = {
    'first': 'FIRST',
    'business': 'BUSINESS',
    'premiumEconomy': 'PREMIUM_ECONOMY',
    'economy': 'ECONOMY'
}

# Configuration
LOOKAHEAD_HOURS_NORMAL = 24
ENDGAME_WINDOW_HOURS = 48
SAFETY_FACTOR_NORMAL = 1.10
SAFETY_FACTOR_ENDGAME = 1.00  # In end-game, aim exactly for required kits
TIME_HORIZON = 720


@dataclass
class AircraftType:
    """Represents an aircraft type with capacities and costs"""
    id: str
    type_code: str
    cost_per_kg_per_km: float
    first_class_kits_capacity: int
    business_kits_capacity: int
    premium_economy_kits_capacity: int
    economy_kits_capacity: int
    
    def get_capacity(self, class_name: str) -> int:
        """Get kit capacity for a class"""
        mapping = {
            'first': self.first_class_kits_capacity,
            'business': self.business_kits_capacity,
            'premiumEconomy': self.premium_economy_kits_capacity,
            'economy': self.economy_kits_capacity
        }
        return mapping.get(class_name, 0)


@dataclass
class Airport:
    """Represents an airport with costs and capacities"""
    id: str
    code: str
    name: str
    first_loading_cost: float
    business_loading_cost: float
    premium_economy_loading_cost: float
    economy_loading_cost: float
    capacity_fc: int
    capacity_bc: int
    capacity_pe: int
    capacity_ec: int
    
    def get_loading_cost(self, class_name: str) -> float:
        """Get loading cost for a class"""
        mapping = {
            'first': self.first_loading_cost,
            'business': self.business_loading_cost,
            'premiumEconomy': self.premium_economy_loading_cost,
            'economy': self.economy_loading_cost
        }
        return mapping.get(class_name, 0.0)
    
    def get_capacity(self, class_name: str) -> int:
        """Get storage capacity for a class"""
        mapping = {
            'first': self.capacity_fc,
            'business': self.capacity_bc,
            'premiumEconomy': self.capacity_pe,
            'economy': self.capacity_ec
        }
        return mapping.get(class_name, 0)


class DataLoader:
    """Loads and parses CSV data files"""
    
    def __init__(self, resources_dir: str = "resources"):
        self.resources_dir = Path(resources_dir)
        if not self.resources_dir.exists():
            self.resources_dir = Path(__file__).parent / resources_dir
    
    def load_aircraft_types(self) -> Dict[str, AircraftType]:
        """Load aircraft types from CSV"""
        aircraft_types = {}
        csv_path = self.resources_dir / "aircraft_types.csv"
        
        if not csv_path.exists():
            logger.warning(f"Aircraft types CSV not found at {csv_path}")
            return aircraft_types
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                aircraft = AircraftType(
                    id=row['id'],
                    type_code=row['type_code'],
                    cost_per_kg_per_km=float(row['cost_per_kg_per_km']),
                    first_class_kits_capacity=int(row['first_class_kits_capacity']),
                    business_kits_capacity=int(row['business_kits_capacity']),
                    premium_economy_kits_capacity=int(row['premium_economy_kits_capacity']),
                    economy_kits_capacity=int(row['economy_kits_capacity'])
                )
                aircraft_types[aircraft.type_code] = aircraft
        
        logger.info(f"Loaded {len(aircraft_types)} aircraft types")
        return aircraft_types
    
    def load_airports(self) -> Dict[str, Airport]:
        """Load airports from CSV"""
        airports = {}
        csv_path = self.resources_dir / "airports_with_stocks.csv"
        
        if not csv_path.exists():
            logger.warning(f"Airports CSV not found at {csv_path}")
            return airports
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                airport = Airport(
                    id=row['id'],
                    code=row['code'],
                    name=row['name'],
                    first_loading_cost=float(row['first_loading_cost']),
                    business_loading_cost=float(row['business_loading_cost']),
                    premium_economy_loading_cost=float(row['premium_economy_loading_cost']),
                    economy_loading_cost=float(row['economy_loading_cost']),
                    capacity_fc=int(row['capacity_fc']),
                    capacity_bc=int(row['capacity_bc']),
                    capacity_pe=int(row['capacity_pe']),
                    capacity_ec=int(row['capacity_ec'])
                )
                airports[airport.code] = airport
        
        logger.info(f"Loaded {len(airports)} airports")
        return airports


class Stage2Solver:
    """
    Stage 2 solver with 24h lookahead, target stock levels, and kit repositioning
    """
    
    def __init__(self, api_client: ApiClient, data_loader: DataLoader, 
                 lookahead_hours: int = LOOKAHEAD_HOURS_NORMAL, 
                 endgame_window_hours: int = ENDGAME_WINDOW_HOURS,
                 safety_factor_normal: float = SAFETY_FACTOR_NORMAL,
                 safety_factor_endgame: float = SAFETY_FACTOR_ENDGAME):
        self.api_client = api_client
        self.data_loader = data_loader
        self.lookahead_hours = lookahead_hours
        self.endgame_window_hours = endgame_window_hours
        self.safety_factor_normal = safety_factor_normal
        self.safety_factor_endgame = safety_factor_endgame
        
        # Load data
        self.aircraft_types = data_loader.load_aircraft_types()
        self.airports = data_loader.load_airports()
        
        # Track inventory for all airports (defaults to 0)
        self.inventory = defaultdict(lambda: defaultdict(int))
        
        # Initialize HUB1 inventory from initial stocks (from CSV data)
        hub1 = self.airports.get('HUB1')
        if hub1:
            self.inventory['HUB1'] = {
                'first': 1659,  # From airports_with_stocks.csv
                'business': 5184,
                'premiumEconomy': 2668,
                'economy': 23651
            }
        
        # Track flights in transit (flight_id -> {arrival_time: {class: quantity}})
        self.in_transit = {}
        
        # Track scheduled flights for forecasting
        self.scheduled_flights = []
        
        # Track pending purchases (arrival_time -> {class: quantity})
        self.pending_purchases = defaultdict(lambda: defaultdict(int))
        
        # Statistics tracking
        self.stats = {
            'rounds_played': 0,
            'flights_loaded': 0,
            'kits_loaded': defaultdict(int),
            'kits_purchased': defaultdict(int),
            'api_requests': 0,
            'api_successful': 0,
            'api_failed': 0,
            'start_time': None,
            'penalties_by_type': defaultdict(int),
            'penalty_costs_by_type': defaultdict(float)
        }
        
        logger.info("Stage 2.5 solver initialized (Penalty-aware with End-game Planning)")
        logger.info(f"Normal mode: Lookahead={lookahead_hours}h, Safety={safety_factor_normal}")
        logger.info(f"End-game mode: Window={endgame_window_hours}h, Safety={safety_factor_endgame}")
    
    def solve(self):
        """Main solving loop"""
        logger.info("=" * 60)
        logger.info("Starting Stage 2 Solver (24h Lookahead + Repositioning)")
        logger.info("=" * 60)
        
        # Start session
        self.api_client.start_session()
        self.stats['api_requests'] += 1
        self.stats['api_successful'] += 1
        self.stats['start_time'] = time.time()
        
        try:
            previous_response = None
            completed_all_rounds = False
            
            for hour in range(720):  # 30 days * 24 hours
                day = hour // 24
                hour_of_day = hour % 24
                
                # Progress logging
                if hour_of_day == 0:
                    elapsed = time.time() - self.stats['start_time']
                    progress = (hour / 720) * 100
                    logger.info(f"[Day {day}, Hour {hour_of_day}] Progress: {progress:.1f}%, Elapsed: {elapsed:.1f}s")
                
                # End-game strategy: last ENDGAME_WINDOW_HOURS hours
                current_time = day * 24 + hour
                is_end_game = current_time >= TIME_HORIZON - self.endgame_window_hours
                
                # Process arrivals (kits arriving from flights)
                self._process_arrivals(day, hour_of_day)
                
                # Calculate decisions
                if previous_response is None:
                    flight_loads = []
                    kit_purchasing_orders = self._calculate_initial_purchases(day, hour_of_day)
                else:
                    flight_updates = previous_response.get("flightUpdates", [])
                    # Update scheduled flights for forecasting
                    self._update_scheduled_flights(flight_updates, day, hour_of_day)
                    
                    # Calculate flight loads with lookahead
                    flight_loads = self._calculate_flight_loads_with_lookahead(
                        flight_updates, day, hour_of_day
                    )
                    # Calculate purchases (stop buying in end-game)
                    if is_end_game:
                        # End-game: minimize purchases, try to use existing stock
                        kit_purchasing_orders = self._calculate_end_game_purchases(day, hour_of_day)
                    else:
                        kit_purchasing_orders = self._calculate_purchases_with_lookahead(
                            flight_updates, day, hour_of_day
                        )
                
                # Submit round
                try:
                    self.stats['api_requests'] += 1
                    previous_response = self.api_client.play_round(
                        day=day,
                        hour=hour_of_day,
                        flight_loads=flight_loads,
                        kit_purchasing_orders=kit_purchasing_orders
                    )
                    self.stats['api_successful'] += 1
                    self.stats['rounds_played'] += 1
                    
                    # Update statistics
                    self._update_statistics(flight_loads, kit_purchasing_orders)
                    
                    # Update inventory based on LANDED flights
                    self._update_inventory_from_landings(previous_response.get("flightUpdates", []))
                    
                    # Display results
                    self._display_round_results(previous_response, day, hour_of_day)
                    self.last_response = previous_response
                    
                    # Check if we should continue
                    if previous_response.get("day") >= 29 and previous_response.get("hour") >= 23:
                        logger.info("Reached end of simulation (Day 29, Hour 23)")
                        completed_all_rounds = True
                        break
                        
                except requests.exceptions.HTTPError as e:
                    self.stats['api_failed'] += 1
                    logger.error(f"Error in round Day {day}, Hour {hour_of_day}: {e}")
                    if e.response is not None:
                        logger.error(f"Response: {e.response.text}")
                    break
                    
        except KeyboardInterrupt:
            logger.warning("Interrupted by user")
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
        finally:
            # Only call end_session if we didn't complete all rounds
            # (server automatically ends session when all 720 rounds complete)
            if not completed_all_rounds:
                logger.info("=" * 60)
                logger.info("Ending session (didn't complete all rounds)...")
                self.stats['api_requests'] += 1
                final_result = self.api_client.end_session()
                if final_result:
                    self.stats['api_successful'] += 1
                else:
                    self.stats['api_failed'] += 1
                display_result = final_result if final_result is not None else self.last_response
            else:
                logger.info("=" * 60)
                logger.info("Completed all 720 rounds - server will end session automatically")
                display_result = self.last_response
            
            # Update final statistics from response
            if display_result:
                penalties = display_result.get('penalties', [])
                for penalty in penalties:
                    penalty_type = penalty.get('code', 'UNKNOWN')
                    penalty_cost = penalty.get('penalty', 0)
                    self.stats['penalties_by_type'][penalty_type] += 1
                    self.stats['penalty_costs_by_type'][penalty_type] += penalty_cost
            
            # Print comprehensive summary
            self._print_summary(display_result)
    
    def _print_summary(self, display_result: Optional[Dict]):
        """Print comprehensive execution summary"""
        total_duration = time.time() - self.stats['start_time'] if self.stats['start_time'] else 0
        
        print("\n" + "=" * 60)
        print("SOLVER EXECUTION SUMMARY")
        print("=" * 60)
        print()
        
        if display_result:
            print("Final Results:")
            print(f"  Rounds Played:       {self.stats['rounds_played']}")
            print(f"  Final Day:           {display_result.get('day', 0)}")
            print(f"  Final Hour:          {display_result.get('hour', 0)}")
            print(f"  Total Cost:          €{display_result.get('totalCost', 0):,.2f}")
            print()
            
            print("Kit Statistics:")
            print(f"  Flights Loaded:      {self.stats['flights_loaded']}")
            print(f"  Total Kits Loaded:   "
                  f"F={self.stats['kits_loaded']['first']}, "
                  f"B={self.stats['kits_loaded']['business']}, "
                  f"PE={self.stats['kits_loaded']['premiumEconomy']}, "
                  f"E={self.stats['kits_loaded']['economy']}")
            print(f"  Total Kits Purchased:"
                  f"F={self.stats['kits_purchased']['first']}, "
                  f"B={self.stats['kits_purchased']['business']}, "
                  f"PE={self.stats['kits_purchased']['premiumEconomy']}, "
                  f"E={self.stats['kits_purchased']['economy']}")
            print()
            
            penalties = display_result.get('penalties', [])
            if penalties:
                total_penalty = sum(p.get('penalty', 0) for p in penalties)
                operational_cost = display_result.get('totalCost', 0) - total_penalty
                
                print("Penalty Statistics:")
                print(f"  Total Penalties:     {len(penalties)}")
                print(f"  Penalty Cost:        €{total_penalty:,.2f}")
                print(f"  By Type:")
                
                # Group penalties by type
                penalty_by_type = defaultdict(lambda: {'count': 0, 'cost': 0.0})
                for penalty in penalties:
                    ptype = penalty.get('code', 'UNKNOWN')
                    pcost = penalty.get('penalty', 0)
                    penalty_by_type[ptype]['count'] += 1
                    penalty_by_type[ptype]['cost'] += pcost
                
                # Sort by cost (descending)
                sorted_penalties = sorted(penalty_by_type.items(), 
                                        key=lambda x: x[1]['cost'], reverse=True)
                for ptype, data in sorted_penalties[:10]:  # Top 10
                    print(f"    - {ptype}: {data['count']} (€{data['cost']:,.2f})")
                print()
                
                print("Cost Breakdown:")
                print(f"  Operational Cost:    €{operational_cost:,.2f}")
                print(f"  Penalty Cost:        €{total_penalty:,.2f} "
                      f"({(total_penalty/display_result.get('totalCost', 1)*100):.1f}%)")
                print()
        
        print("=" * 60)
        print("API REQUEST SUMMARY")
        print("=" * 60)
        print(f"Total Requests:      {self.stats['api_requests']}")
        print(f"Successful:          {self.stats['api_successful']}")
        print(f"Failed:              {self.stats['api_failed']}")
        if self.stats['api_requests'] > 0:
            success_rate = (self.stats['api_successful'] / self.stats['api_requests']) * 100
            print(f"Success Rate:        {success_rate:.1f}%")
        if total_duration > 0:
            print(f"Total Duration:      {total_duration:.1f}s")
            if self.stats['api_requests'] > 0:
                req_per_sec = self.stats['api_requests'] / total_duration
                print(f"Requests/Second:     {req_per_sec:.2f}")
        print("=" * 60)
        print()
        
        if display_result:
            print("✓ Solver completed successfully!")
            print(f"  Final Cost: €{display_result.get('totalCost', 0):,.2f}")
            log_file = Path("logs").glob("solver_*.log")
            log_files = list(log_file)
            if log_files:
                latest_log = max(log_files, key=lambda p: p.stat().st_mtime)
                print(f"  Log file: {latest_log.name}")
        print()
    
    def _update_scheduled_flights(self, flight_updates: List[Dict], day: int, hour: int):
        """Update list of scheduled flights for forecasting"""
        current_time = day * 24 + hour
        
        for flight in flight_updates:
            if flight.get("eventType") == "SCHEDULED":
                departure = flight.get("departure", {})
                dep_day = departure.get("day", 0)
                dep_hour = departure.get("hour", 0)
                dep_time = dep_day * 24 + dep_hour
                
                # Store flight info for forecasting
                flight_info = {
                    'flightId': flight.get('flightId'),
                    'flightNumber': flight.get('flightNumber'),
                    'origin': flight.get('originAirport'),
                    'destination': flight.get('destinationAirport'),
                    'departure_time': dep_time,
                    'arrival': flight.get('arrival', {}),
                    'aircraftType': flight.get('aircraftType'),
                    'passengers': flight.get('passengers', {})
                }
                
                # Update or add to scheduled flights
                self.scheduled_flights = [f for f in self.scheduled_flights 
                                        if f.get('flightId') != flight_info['flightId']]
                self.scheduled_flights.append(flight_info)
    
    def _forecast_demand_window(self, current_time: int, time_end: int) -> Dict[str, Dict[str, int]]:
        """Compute demand forecast per airport and class for a time window"""
        demand_forecast = defaultdict(lambda: defaultdict(int))
        
        for flight in self.scheduled_flights:
            dep_time = flight.get('departure_time', 999999)
            if current_time <= dep_time < time_end:
                origin = flight.get('origin', '')
                passengers = flight.get('passengers', {})
                
                for class_name in CLASS_NAMES:
                    pax = passengers.get(class_name, 0)
                    if pax > 0:
                        demand_forecast[origin][class_name] += pax
        
        return dict(demand_forecast)
    
    def _compute_24h_forecast(self, current_time: int) -> Dict[str, Dict[str, int]]:
        """Compute 24h demand forecast per airport and class (backward compatibility)"""
        time_end = current_time + self.lookahead_hours
        return self._forecast_demand_window(current_time, time_end)
    
    def _compute_target_stock(self, demand_forecast: Dict[str, Dict[str, int]], 
                             safety_factor: float) -> Dict[str, Dict[str, int]]:
        """Compute target stock levels per airport and class with given safety factor"""
        target_stock = defaultdict(lambda: defaultdict(int))
        
        for airport_code, cls_demands in demand_forecast.items():
            airport = self.airports.get(airport_code)
            if not airport:
                continue
            
            for class_name, demand in cls_demands.items():
                desired = int(demand * safety_factor)
                capacity = airport.get_capacity(class_name)
                target_stock[airport_code][class_name] = min(desired, capacity)
        
        return dict(target_stock)
    
    def _calculate_flight_loads_with_lookahead(self, flight_updates: List[Dict], 
                                               day: int, hour: int) -> List[Dict]:
        """
        Calculate flight loads with 24h lookahead and repositioning
        """
        current_time = day * 24 + hour
        flight_loads = []
        
        # Detect mode: NORMAL or ENDGAME
        if current_time < TIME_HORIZON - self.endgame_window_hours:
            mode = "NORMAL"
            time_end = min(current_time + self.lookahead_hours, TIME_HORIZON)
            safety_factor = self.safety_factor_normal
        else:
            mode = "ENDGAME"
            time_end = TIME_HORIZON  # Plan for ALL remaining flights
            safety_factor = self.safety_factor_endgame
            logger.debug(f"End-game mode activated at hour {current_time} (planning until {time_end})")
        
        # Compute forecast and target stock based on mode
        demand_forecast = self._forecast_demand_window(current_time, time_end)
        target_stock = self._compute_target_stock(demand_forecast, safety_factor)
        
        # Process CHECKED_IN flights - CRITICAL: Only load kits for flights that are actually CHECKED_IN
        # The API only accepts loads for flights in CHECKED_IN state, not SCHEDULED
        # We use scheduled_flights for forecasting/planning, but only load when CHECKED_IN
        checked_in_flights = [f for f in flight_updates if f.get("eventType") == "CHECKED_IN"]
        
        all_flights_to_process = checked_in_flights
        
        for flight in all_flights_to_process:
            flight_id = flight.get("flightId")
            origin = flight.get("originAirport")
            destination = flight.get("destinationAirport")
            aircraft_type_code = flight.get("aircraftType")
            passengers = flight.get("passengers", {})
            
            # Skip if we already loaded kits for this flight in this round
            if any(fl.get("flightId") == flight_id for fl in flight_loads):
                continue
            
            # Get aircraft type
            aircraft = self.aircraft_types.get(aircraft_type_code)
            if not aircraft:
                logger.warning(f"Unknown aircraft type: {aircraft_type_code}")
                continue
            
            # Get origin airport
            origin_airport = self.airports.get(origin)
            if not origin_airport:
                continue
            
            # Get destination airport
            dest_airport = self.airports.get(destination)
            if not dest_airport:
                continue
            
            loaded_kits = {}
            
            for class_name in CLASS_NAMES:
                # FIX 1: In ENDGAME mode, use planned demand from schedule, not just runtime passengers
                # This ensures we cover flights even if runtime passengers is 0 but schedule has planned passengers
                if mode == "ENDGAME":
                    # Find this flight in scheduled_flights to get planned passengers
                    scheduled_flight = next((f for f in self.scheduled_flights 
                                           if f.get('flightId') == flight_id), None)
                    if scheduled_flight:
                        planned_passengers = scheduled_flight.get('passengers', {}).get(class_name, 0)
                        pax_demand = max(passengers.get(class_name, 0), planned_passengers)
                    else:
                        pax_demand = passengers.get(class_name, 0)
                else:
                    pax_demand = passengers.get(class_name, 0)
                
                # FIX 2: Don't skip classes in ENDGAME - we need to cover all planned demand
                if pax_demand == 0 and origin != "HUB1" and mode != "ENDGAME":
                    # Only skip repositioning in normal mode if no demand
                    loaded_kits[class_name] = 0
                    continue
                
                # Get current stock (estimated)
                origin_stock = self.inventory[origin].get(class_name, 0)
                dest_stock = self.inventory[destination].get(class_name, 0)
                
                # Get target stock for destination
                target_dest = target_stock.get(destination, {}).get(class_name, 0)
                
                # Get capacities
                aircraft_cap = aircraft.get_capacity(class_name)
                dest_capacity = dest_airport.get_capacity(class_name)
                
                # FIX 3: Respect inventory when loading - don't override to ignore stock
                # First, decide what we WISH to load
                wish_for_pax = min(pax_demand, aircraft_cap)
                
                # Hard cap by real stock (don't go negative)
                max_from_stock = max(0, origin_stock)
                kits_for_pax = min(wish_for_pax, max_from_stock)
                
                # Log if we can't load full demand
                if kits_for_pax < wish_for_pax:
                    if mode == "ENDGAME":
                        logger.warning(f"ENDGAME: Cannot load full demand at {origin} for {class_name}: "
                                     f"wish={wish_for_pax}, stock={origin_stock}, loading={kits_for_pax}")
                    else:
                        logger.debug(f"Low stock at {origin} for {class_name}: "
                                   f"wish={wish_for_pax}, stock={origin_stock}, loading={kits_for_pax}")
                
                # 2. Calculate extra kits for repositioning
                # Stage 2.5: In ENDGAME mode, only reposition from HUB1 (don't drain outstations)
                extra_kits = 0
                
                if mode == "ENDGAME" and origin != "HUB1":
                    # In end-game, don't pull kits from outstations (they need them for their last flights)
                    extra_kits = 0
                elif origin == "HUB1":
                    # Calculate actual deficit (considering what's already in transit)
                    dest_deficit = max(0, target_dest - dest_stock)
                    
                    # Only reposition if:
                    # - There's a significant deficit (at least 30% of target, or absolute minimum)
                    # - We have capacity and inventory
                    # - We won't exceed destination capacity
                    # - Destination doesn't already have enough stock
                    
                    # Account for kits already in transit to this destination
                    incoming_kits = self._get_incoming_kits(destination, class_name, day, hour)
                    effective_dest_stock = dest_stock + incoming_kits
                    
                    # Only reposition if there's a real deficit
                    if dest_deficit > max(target_dest * 0.3, 10):  # At least 30% of target or 10 kits
                        # Check if destination already has enough (with incoming kits)
                        if effective_dest_stock < target_dest * 0.8:  # Still below 80% of target
                            capacity_left = aircraft_cap - kits_for_pax
                            available_for_extra = max(0, origin_stock - kits_for_pax) if origin_stock >= 0 else 0
                            
                            # Be very conservative - only reposition up to 40% of deficit
                            conservative_deficit = int(dest_deficit * 0.4)
                            extra_kits = min(conservative_deficit, capacity_left, available_for_extra)
                            
                            # CRITICAL: Respect destination capacity - check current + incoming
                            forecast_dest_after = effective_dest_stock + kits_for_pax + extra_kits
                            
                            # More aggressive capacity checking - leave 15% buffer to avoid penalties
                            max_allowed_capacity = dest_capacity * 0.85
                            
                            if forecast_dest_after > max_allowed_capacity:
                                # Reduce extra_kits to stay within capacity
                                max_allowed = max(0, max_allowed_capacity - effective_dest_stock - kits_for_pax)
                                extra_kits = min(extra_kits, max_allowed)
                            
                            # Don't reposition if it would cause capacity issues
                            if forecast_dest_after > max_allowed_capacity:
                                extra_kits = 0
                        else:
                            # Destination already has enough stock
                            extra_kits = 0
                
                kits_loaded = kits_for_pax + extra_kits
                
                # Ensure we don't exceed aircraft capacity
                kits_loaded = min(kits_loaded, aircraft_cap)
                
                # FIX 3 (continued): Don't override to ignore inventory - we already respected it above
                # The kits_for_pax already respects inventory, so kits_loaded is correct
                
                loaded_kits[class_name] = kits_loaded
                
                # Update inventory (estimated)
                if kits_loaded > 0:
                    self.inventory[origin][class_name] = self.inventory[origin].get(class_name, 0) - kits_loaded
                    
                    # Track in transit - store destination and arrival time
                    arrival = flight.get("arrival", {})
                    arrival_day = arrival.get("day", day)
                    arrival_hour = arrival.get("hour", hour)
                    arrival_time = arrival_day * 24 + arrival_hour
                    
                    # Store transit info: flight_id -> {destination, arrival_time, {class: quantity}}
                    if flight_id not in self.in_transit:
                        self.in_transit[flight_id] = {
                            'destination': destination,
                            'arrival_time': arrival_time,
                            'kits': defaultdict(int)
                        }
                    self.in_transit[flight_id]['kits'][class_name] += kits_loaded
                    
                    if extra_kits > 0:
                        logger.debug(f"Flight {flight.get('flightNumber')}: Repositioning {extra_kits} {class_name} "
                                   f"kits to {destination} (deficit: {dest_deficit})")
            
            # Only add if we're loading at least one kit
            if any(loaded_kits.values()):
                flight_loads.append({
                    "flightId": flight_id,
                    "loadedKits": loaded_kits
                })
            elif mode == "ENDGAME":
                # In end-game, log if we're not loading anything (might indicate a problem)
                logger.warning(f"ENDGAME: Flight {flight_id} from {origin} has no kits loaded "
                             f"(passengers: {passengers})")
        
        return flight_loads
    
    def _process_arrivals(self, day: int, hour: int):
        """Process kit arrivals from flights and purchases"""
        current_time = day * 24 + hour
        
        # Process purchase arrivals
        for arrival_time, purchases in list(self.pending_purchases.items()):
            if arrival_time <= current_time:
                for class_name, quantity in purchases.items():
                    self.inventory['HUB1'][class_name] += quantity
                    logger.debug(f"Purchase arrived: {quantity} {class_name} kits at HUB1")
                del self.pending_purchases[arrival_time]
        
        # Flight arrivals are handled in _update_inventory_from_landings
    
    def _get_incoming_kits(self, airport: str, class_name: str, current_day: int, current_hour: int) -> int:
        """Get kits that are in transit to this airport (will arrive soon)"""
        current_time = current_day * 24 + current_hour
        incoming = 0
        
        for flight_id, transit_info in self.in_transit.items():
            if transit_info.get('destination') == airport:
                arrival_time = transit_info.get('arrival_time', 999999)
                # Count kits arriving in next 24 hours
                if arrival_time > current_time and arrival_time <= current_time + 24:
                    kits = transit_info.get('kits', {})
                    incoming += kits.get(class_name, 0)
        
        return incoming
    
    def _update_inventory_from_landings(self, flight_updates: List[Dict]):
        """Update inventory when flights land"""
        for flight in flight_updates:
            if flight.get("eventType") == "LANDED":
                destination = flight.get("destinationAirport")
                flight_id = flight.get("flightId")
                
                # Get kits that were loaded on this flight
                if flight_id in self.in_transit:
                    transit_info = self.in_transit[flight_id]
                    kits_by_class = transit_info.get('kits', {})
                    
                    # Add kits to destination inventory
                    for class_name, quantity in kits_by_class.items():
                        self.inventory[destination][class_name] = \
                            self.inventory[destination].get(class_name, 0) + quantity
                    
                    # Remove from in_transit
                    del self.in_transit[flight_id]
    
    def _calculate_purchases_with_lookahead(self, flight_updates: List[Dict], 
                                            day: int, hour: int) -> Dict[str, int]:
        """Calculate purchases based on HUB1 forecast - Stage 2.5: More aggressive in end-game"""
        purchases = {cls: 0 for cls in CLASS_NAMES}
        current_time = day * 24 + hour
        
        # Detect mode
        if current_time < TIME_HORIZON - self.endgame_window_hours:
            mode = "NORMAL"
            time_end = min(current_time + self.lookahead_hours, TIME_HORIZON)
            safety_factor = self.safety_factor_normal
        else:
            mode = "ENDGAME"
            time_end = TIME_HORIZON  # Plan for ALL remaining flights
            safety_factor = self.safety_factor_endgame
        
        # Compute forecast for HUB1 (based on mode)
        demand_forecast = self._forecast_demand_window(current_time, time_end)
        hub1_forecast = demand_forecast.get("HUB1", {})
        
        # Get current HUB1 inventory (estimated)
        hub1_stock = self.inventory.get("HUB1", {})
        
        # Account for pending purchases arriving soon
        pending_arrivals = defaultdict(int)
        for arrival_time, purchases_dict in self.pending_purchases.items():
            if arrival_time <= current_time + 48:  # Next 48 hours
                for cls, qty in purchases_dict.items():
                    pending_arrivals[cls] += qty
        
        # Purchase if forecast shows deficit - more conservative
        for class_name in CLASS_NAMES:
            forecast_demand = hub1_forecast.get(class_name, 0)
            current_stock = hub1_stock.get(class_name, 0)
            pending = pending_arrivals.get(class_name, 0)
            effective_stock = current_stock + pending
            
            # Target is based on forecast with safety factor (mode-dependent)
            target_stock = int(forecast_demand * safety_factor)
            
            # Stage 2.5: More aggressive purchasing in end-game to ensure all flights are covered
            if mode == "ENDGAME":
                # In end-game, buy more aggressively to cover ALL remaining flights
                threshold = 0.8  # Buy if below 80% of target
                buy_percentage = 0.7  # Buy 70% of deficit
            else:
                # Normal mode: more conservative
                threshold = 0.6  # Buy if below 60% of target
                buy_percentage = 0.4  # Buy 40% of deficit
            
            if effective_stock < target_stock * threshold:
                deficit = target_stock - effective_stock
                # Buy based on mode
                purchase_qty = int(deficit * buy_percentage)
                purchase_qty = ((purchase_qty + 9) // 10) * 10  # Round to nearest 10
                
                # Cap at API limits
                max_purchase = 42000
                if class_name == 'premiumEconomy':
                    max_purchase = 1000
                
                purchase_qty = min(purchase_qty, max_purchase)
                
                if purchase_qty > 0:
                    purchases[class_name] = purchase_qty
                    # Track purchase arrival
                    lead_time = KIT_TYPES[class_name]['lead_time']
                    arrival_time = current_time + lead_time
                    self.pending_purchases[arrival_time][class_name] += purchase_qty
                    logger.info(f"Purchasing {purchase_qty} {class_name} kits for HUB1 "
                              f"(arriving hour {arrival_time}, forecast: {forecast_demand}, "
                              f"current: {current_stock}, pending: {pending})")
        
        # Also buy small amounts periodically to maintain stock (like naive solver)
        if hour % 12 == 0:
            for class_name in CLASS_NAMES:
                if purchases[class_name] == 0:
                    min_purchases = {
                        'first': 10,
                        'business': 50,
                        'premiumEconomy': 100,
                        'economy': 500
                    }
                    purchase_qty = min_purchases.get(class_name, 0)
                    if purchase_qty > 0:
                        purchases[class_name] = purchase_qty
                        lead_time = KIT_TYPES[class_name]['lead_time']
                        arrival_time = current_time + lead_time
                        self.pending_purchases[arrival_time][class_name] += purchase_qty
        
        return purchases
    
    def _calculate_initial_purchases(self, day: int, hour: int) -> Dict[str, int]:
        """Calculate initial purchases"""
        return {cls: 0 for cls in CLASS_NAMES}
    
    def _update_statistics(self, flight_loads: List[Dict], purchases: Dict[str, int]):
        """Update statistics from round"""
        # Count flights loaded
        self.stats['flights_loaded'] += len(flight_loads)
        
        # Count kits loaded
        for flight_load in flight_loads:
            loaded_kits = flight_load.get('loadedKits', {})
            for class_name in CLASS_NAMES:
                self.stats['kits_loaded'][class_name] += loaded_kits.get(class_name, 0)
        
        # Count kits purchased
        for class_name in CLASS_NAMES:
            self.stats['kits_purchased'][class_name] += purchases.get(class_name, 0)
    
    def _calculate_end_game_purchases(self, day: int, hour: int) -> Dict[str, int]:
        """End-game strategy: Stage 2.5 - Aggressively purchase to cover ALL remaining flights"""
        # Use the same logic as _calculate_purchases_with_lookahead but with end-game mode
        # This ensures we're using the forecast for ALL remaining flights
        current_time = day * 24 + hour
        time_end = TIME_HORIZON  # Plan for ALL remaining flights
        
        # Compute forecast for ALL remaining flights
        demand_forecast = self._forecast_demand_window(current_time, time_end)
        hub1_forecast = demand_forecast.get("HUB1", {})
        
        purchases = {cls: 0 for cls in CLASS_NAMES}
        hub1_stock = self.inventory.get("HUB1", {})
        
        # Account for pending purchases
        pending_arrivals = defaultdict(int)
        for arrival_time, purchases_dict in self.pending_purchases.items():
            if arrival_time <= current_time + 48:
                for cls, qty in purchases_dict.items():
                    pending_arrivals[cls] += qty
        
        # VERY aggressive purchasing to cover ALL remaining flights
        for class_name in CLASS_NAMES:
            forecast_demand = hub1_forecast.get(class_name, 0)
            current_stock = hub1_stock.get(class_name, 0)
            pending = pending_arrivals.get(class_name, 0)
            effective_stock = current_stock + pending
            
            # Target is exactly remaining demand (safety_factor_endgame = 1.0)
            target_stock = int(forecast_demand * self.safety_factor_endgame)
            
            # Buy VERY aggressively - buy if below 95% of target
            if effective_stock < target_stock * 0.95:
                deficit = target_stock - effective_stock
                purchase_qty = int(deficit * 1.0)  # Buy 100% of deficit
                purchase_qty = ((purchase_qty + 9) // 10) * 10  # Round to nearest 10
                
                # Cap at API limits
                max_purchase = 42000
                if class_name == 'premiumEconomy':
                    max_purchase = 1000
                
                purchase_qty = min(purchase_qty, max_purchase)
                
                if purchase_qty > 0:
                    lead_time = KIT_TYPES[class_name]['lead_time']
                    arrival_time = current_time + lead_time
                    # Only buy if it will arrive before end of game
                    if arrival_time < TIME_HORIZON:
                        purchases[class_name] = purchase_qty
                        self.pending_purchases[arrival_time][class_name] += purchase_qty
                        logger.info(f"ENDGAME: Purchasing {purchase_qty} {class_name} kits "
                                  f"(forecast: {forecast_demand}, current: {current_stock}, "
                                  f"target: {target_stock}, arriving hour {arrival_time})")
        
        return purchases
    
    def _display_round_results(self, response: Dict, day: int, hour: int):
        """Display results from a round"""
        flight_updates = response.get("flightUpdates", [])
        penalties = response.get("penalties", [])
        total_cost = response.get("totalCost", 0)
        
        event_counts = {}
        for flight in flight_updates:
            event_type = flight.get("eventType", "UNKNOWN")
            event_counts[event_type] = event_counts.get(event_type, 0) + 1
        
        logger.info(f"Round results - Updates: {len(flight_updates)} flights "
                   f"({', '.join(f'{k}={v}' for k, v in event_counts.items())}), "
                   f"Penalties: {len(penalties)}, Total cost: €{total_cost:,.2f}")
        
        if penalties:
            total_penalty = sum(p.get('penalty', 0) for p in penalties)
            logger.warning(f"⚠ {len(penalties)} penalties (Total: €{total_penalty:,.2f})")
            for penalty in penalties[:3]:
                logger.warning(f"  - {penalty.get('code')}: €{penalty.get('penalty', 0):,.2f}")


def main():
    """Main entry point"""
    import argparse
    from dotenv import load_dotenv
    
    load_dotenv()
    
    default_api_key = os.getenv("API_KEY", "43b9ab90-b593-404c-a8d8-aaa074e181e1")
    default_base_url = os.getenv("BASE_URL", "http://127.0.0.1:8080/api/v1")
    
    parser = argparse.ArgumentParser(description="Stage 2 solver with 24h lookahead")
    parser.add_argument("--api-key", type=str, default=default_api_key,
                       help="API key for authentication")
    parser.add_argument("--base-url", type=str, default=default_base_url,
                       help="Base URL of the evaluation platform")
    parser.add_argument("--log-level", type=str, default="INFO",
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="Logging level")
    parser.add_argument("--no-log-file", action="store_true",
                       help="Disable logging to file")
    parser.add_argument("--lookahead", type=int, default=24,
                       help="Lookahead hours for forecasting (default: 24)")
    parser.add_argument("--safety-factor", type=float, default=1.10,
                       help="Safety factor for target stock (default: 1.10)")
    parser.add_argument("--resources-dir", type=str, default="resources",
                       help="Directory containing CSV data files")
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(log_to_file=not args.no_log_file, log_level=args.log_level)
    logger.info("=" * 60)
    logger.info("Rotables Challenge - Stage 2.5 Solver (Penalty-aware with End-game Planning)")
    logger.info("=" * 60)
    logger.info(f"API Base URL: {args.base_url}")
    logger.info(f"Normal mode: Lookahead={args.lookahead}h, Safety={args.safety_factor}")
    logger.info(f"End-game mode: Window={ENDGAME_WINDOW_HOURS}h, Safety={SAFETY_FACTOR_ENDGAME}")
    
    # Load data
    data_loader = DataLoader(args.resources_dir)
    
    # Create API client
    api_client = ApiClient(base_url=args.base_url, api_key=args.api_key)
    
    # Create and run solver
    solver = Stage2Solver(api_client, data_loader,
                         lookahead_hours=args.lookahead,
                         endgame_window_hours=ENDGAME_WINDOW_HOURS,
                         safety_factor_normal=args.safety_factor,
                         safety_factor_endgame=SAFETY_FACTOR_ENDGAME)
    solver.solve()


if __name__ == "__main__":
    main()

