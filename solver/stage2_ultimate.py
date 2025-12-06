"""
Stage 2 ULTIMATE Solver
========================

All optimizations combined:
1. AIRCRAFT TYPES: Load capacities and cost_per_kg_km from CSV
2. PENALTY-AWARE DECISIONS: Exact penalty formulas from eval-platform
3. DISTANCE-AWARE: Uses distance from API
4. DEMAND FORECASTING: Uses flight_plan.csv

NEW OPTIMIZATIONS:
5. B3: CLASS-SPECIFIC CAPACITY MARGINS - PE gets 95% vs 90% for others
6. A4: END-GAME DRAIN - Stop purchasing 72h before end, stop repositioning 24h before end
7. C1: MULTI-HOUR LOOKAHEAD - Pre-position for SCHEDULED flights
8. A1: LOADING COST AWARENESS - Factor loading costs into decisions

See OPTIMIZATION_ANALYSIS.md for detailed analysis.
"""

import csv
import os
import time
import logging
import requests
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from dataclasses import dataclass, field

from simple_solver import ApiClient, setup_logging, logger

# ============================================================================
# PENALTY FACTORS (from eval-platform/PenaltyFactors.java)
# ============================================================================
PENALTY_FACTORS = {
    'FLIGHT_OVERLOAD_FACTOR_PER_DISTANCE': 5.0,
    'UNFULFILLED_KIT_FACTOR_PER_DISTANCE': 0.003,
    'NEGATIVE_INVENTORY': 5342.0,
    'OVER_CAPACITY_STOCK': 777.0,
    'END_OF_GAME_REMAINING_STOCK': 0.0013,
    'END_OF_GAME_PENDING_KIT_PROCESSING': 0.0013,
}

# ============================================================================
# KIT PROPERTIES
# ============================================================================
KIT_TYPES = {
    'first': {'cost': 200.0, 'weight': 5.0, 'lead_time': 48},
    'business': {'cost': 150.0, 'weight': 3.0, 'lead_time': 36},
    'premiumEconomy': {'cost': 100.0, 'weight': 2.5, 'lead_time': 24},
    'economy': {'cost': 50.0, 'weight': 1.5, 'lead_time': 12}
}

CLASS_NAMES = ['first', 'business', 'premiumEconomy', 'economy']
TIME_HORIZON = 720

# Smart repositioning parameters
# E4: Class-specific max reposition distances (lighter kits can go further)
# NOTE: F1a/F1b/G2 tested but REVERTED - more aggressive settings cost +€340K in movement
MAX_REPOSITION_DISTANCE = {
    'economy': 3000,      # Lightest (1.5kg) - optimal distance
    'business': 2000,     # Medium (3.0kg)
    'premiumEconomy': 1500,  # Medium (2.5kg)
    'first': 1000         # Heaviest (5.0kg) - shortest distance
}
# E1: Add premiumEconomy to repositioning (biggest penalty at €52K)
REPOSITION_CLASSES = ['economy', 'business', 'premiumEconomy']
# F2: OPTIMIZED - Dynamic reposition percentage based on game phase
# Best found: 3%/2%/0.5% for economy saves €538K from baseline
REPOSITION_PERCENTAGE = {
    'economy': {'early': 0.03, 'mid': 0.02, 'late': 0.005},  # Optimal
    'business': {'early': 0.01, 'mid': 0.005, 'late': 0.00},  # Near zero
    'premiumEconomy': {'early': 0.005, 'mid': 0.00, 'late': 0.00},  # Near zero
}

# D3: End-game flight filtering - don't reposition for flights arriving in last 6 hours
# (kits won't have time to process and be useful)
END_GAME_ARRIVAL_CUTOFF = 714  # Hour 714 = Day 29, Hour 18 (last 6 hours)

# Proactive purchasing parameters
FORECAST_HOURS = 48
PURCHASE_BUFFER = 1.1

# ============================================================================
# NEW: B3 - Class-specific capacity margins
# ============================================================================
CAPACITY_MARGINS = {
    'hub': {
        'first': 0.70,
        'business': 0.70,
        'premiumEconomy': 0.70,
        'economy': 0.70
    },
    'outstation': {
        'first': 0.90,
        'business': 0.90,
        'premiumEconomy': 0.95,  # Higher margin for PE (was causing capacity-reduced)
        'economy': 0.90
    }
}

# ============================================================================
# NEW: A4 - End-game drain parameters
# ============================================================================
# E3: Increase from 72h to 96h to further reduce remaining stock
END_GAME_PURCHASE_CUTOFF = 96  # Hours before end to stop purchasing
END_GAME_REPOSITION_CUTOFF = 24  # Hours before end to stop repositioning

# ============================================================================
# NEW: C1 - Multi-hour lookahead parameters
# ============================================================================
LOOKAHEAD_HOURS = 6  # Hours ahead to look at SCHEDULED flights


@dataclass
class AircraftType:
    id: str
    type_code: str
    first_class_seats: int
    business_seats: int
    premium_economy_seats: int
    economy_seats: int
    cost_per_kg_per_km: float
    first_class_kits_capacity: int
    business_kits_capacity: int
    premium_economy_kits_capacity: int
    economy_kits_capacity: int
    
    def get_kit_capacity(self, class_name: str) -> int:
        return {
            'first': self.first_class_kits_capacity,
            'business': self.business_kits_capacity,
            'premiumEconomy': self.premium_economy_kits_capacity,
            'economy': self.economy_kits_capacity
        }.get(class_name, 0)


@dataclass
class Airport:
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
    initial_fc: int = 0
    initial_bc: int = 0
    initial_pe: int = 0
    initial_ec: int = 0
    processing_time_fc: int = 6
    processing_time_bc: int = 4
    processing_time_pe: int = 2
    processing_time_ec: int = 1
    
    def get_capacity(self, class_name: str) -> int:
        return {'first': self.capacity_fc, 'business': self.capacity_bc,
                'premiumEconomy': self.capacity_pe, 'economy': self.capacity_ec}.get(class_name, 0)
    
    def get_processing_time(self, class_name: str) -> int:
        return {'first': self.processing_time_fc, 'business': self.processing_time_bc,
                'premiumEconomy': self.processing_time_pe, 'economy': self.processing_time_ec}.get(class_name, 1)
    
    def get_loading_cost(self, class_name: str) -> float:
        return {'first': self.first_loading_cost, 'business': self.business_loading_cost,
                'premiumEconomy': self.premium_economy_loading_cost, 
                'economy': self.economy_loading_cost}.get(class_name, 0)


@dataclass
class FlightPattern:
    origin: str
    destination: str
    departure_hour: int
    arrival_hour: int
    arrival_next_day: bool
    distance_km: float
    days_of_week: List[int]


class DataLoader:
    def __init__(self, resources_dir: str = "resources"):
        self.resources_dir = Path(resources_dir)
        if not self.resources_dir.exists():
            self.resources_dir = Path(__file__).parent / resources_dir
    
    def load_aircraft_types(self) -> Dict[str, AircraftType]:
        aircraft_types = {}
        csv_path = self.resources_dir / "aircraft_types.csv"
        if not csv_path.exists():
            return aircraft_types
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                aircraft = AircraftType(
                    id=row['id'],
                    type_code=row['type_code'],
                    first_class_seats=int(row['first_class_seats']),
                    business_seats=int(row['business_seats']),
                    premium_economy_seats=int(row['premium_economy_seats']),
                    economy_seats=int(row['economy_seats']),
                    cost_per_kg_per_km=float(row['cost_per_kg_per_km']),
                    first_class_kits_capacity=int(row['first_class_kits_capacity']),
                    business_kits_capacity=int(row['business_kits_capacity']),
                    premium_economy_kits_capacity=int(row['premium_economy_kits_capacity']),
                    economy_kits_capacity=int(row['economy_kits_capacity']),
                )
                aircraft_types[aircraft.type_code] = aircraft
        
        logger.info(f"Loaded {len(aircraft_types)} aircraft types")
        return aircraft_types
    
    def load_airports(self) -> Dict[str, Airport]:
        airports = {}
        csv_path = self.resources_dir / "airports_with_stocks.csv"
        if not csv_path.exists():
            return airports
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                airport = Airport(
                    id=row['id'], code=row['code'], name=row['name'],
                    first_loading_cost=float(row['first_loading_cost']),
                    business_loading_cost=float(row['business_loading_cost']),
                    premium_economy_loading_cost=float(row['premium_economy_loading_cost']),
                    economy_loading_cost=float(row['economy_loading_cost']),
                    capacity_fc=int(row['capacity_fc']),
                    capacity_bc=int(row['capacity_bc']),
                    capacity_pe=int(row['capacity_pe']),
                    capacity_ec=int(row['capacity_ec']),
                    initial_fc=int(row.get('initial_fc_stock', 0)),
                    initial_bc=int(row.get('initial_bc_stock', 0)),
                    initial_pe=int(row.get('initial_pe_stock', 0)),
                    initial_ec=int(row.get('initial_ec_stock', 0)),
                    processing_time_fc=int(row.get('first_processing_time', 6)),
                    processing_time_bc=int(row.get('business_processing_time', 4)),
                    processing_time_pe=int(row.get('premium_economy_processing_time', 2)),
                    processing_time_ec=int(row.get('economy_processing_time', 1)),
                )
                airports[airport.code] = airport
        
        logger.info(f"Loaded {len(airports)} airports")
        return airports
    
    def load_flight_patterns(self) -> List[FlightPattern]:
        patterns = []
        csv_path = self.resources_dir / "flight_plan.csv"
        if not csv_path.exists():
            return patterns
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                days = []
                for i, day in enumerate(['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']):
                    if row.get(day, '0') == '1':
                        days.append(i)
                
                pattern = FlightPattern(
                    origin=row['depart_code'],
                    destination=row['arrival_code'],
                    departure_hour=int(row['scheduled_hour']),
                    arrival_hour=int(row['scheduled_arrival_hour']),
                    arrival_next_day=row.get('arrival_next_day', '0') == '1',
                    distance_km=float(row['distance_km']),
                    days_of_week=days
                )
                patterns.append(pattern)
        
        logger.info(f"Loaded {len(patterns)} flight patterns")
        return patterns


class KitMovement:
    def __init__(self, hour: int, airport: str, class_name: str, quantity: int):
        self.hour = hour
        self.airport = airport
        self.class_name = class_name
        self.quantity = quantity


class UltimateSolver:
    """
    Ultimate solver with all optimizations.
    """
    
    def __init__(self, api_client: ApiClient, data_loader: DataLoader):
        self.api_client = api_client
        self.airports = data_loader.load_airports()
        self.aircraft_types = data_loader.load_aircraft_types()
        self.flight_patterns = data_loader.load_flight_patterns()
        
        # Build lookups
        self.route_distances: Dict[Tuple[str, str], float] = {}
        for pattern in self.flight_patterns:
            self.route_distances[(pattern.origin, pattern.destination)] = pattern.distance_km
        
        self._build_demand_forecast()
        
        # Identify HUB
        self.hub_code = max(self.airports.keys(), 
                           key=lambda c: sum(self.airports[c].get_capacity(cls) for cls in CLASS_NAMES))
        
        # NEW A1: Build loading cost lookup
        self._build_loading_cost_rankings()
        
        # Initialize inventory
        self.inventory: Dict[str, Dict[str, int]] = {}
        for code, airport in self.airports.items():
            self.inventory[code] = {
                'first': airport.initial_fc,
                'business': airport.initial_bc,
                'premiumEconomy': airport.initial_pe,
                'economy': airport.initial_ec
            }
        
        self.scheduled_movements: List[KitMovement] = []
        self.pending_purchases: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        
        # NEW C1: Track anticipated demand from SCHEDULED flights
        self.anticipated_demand: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        
        # Statistics
        self.stats = {
            'rounds_played': 0, 'flights_loaded': 0,
            'kits_loaded': defaultdict(int), 'kits_purchased': defaultdict(int),
            'kits_repositioned': defaultdict(int),
            'unfulfilled': defaultdict(int), 'capacity_reduced': defaultdict(int),
            'aircraft_capacity_limited': defaultdict(int),
            'start_time': None, 
            'distance_used_from_api': 0, 'distance_used_from_csv': 0,
            'aircraft_type_found': 0, 'aircraft_type_missing': 0,
            'penalty_decisions': defaultdict(int),
            'end_game_purchases_blocked': 0,
            'end_game_reposition_blocked': 0,
            'lookahead_prepositions': 0,
            'loading_cost_savings': 0.0
        }
        
        total = {c: sum(self.inventory[a].get(c, 0) for a in self.inventory) for c in CLASS_NAMES}
        logger.info(f"Initial inventory: F={total['first']}, B={total['business']}, "
                   f"PE={total['premiumEconomy']}, E={total['economy']}")
        logger.info(f"HUB: {self.hub_code}")
        logger.info("ULTIMATE SOLVER: All optimizations enabled")
        logger.info(f"  B3: Class-specific margins (PE outstation: {CAPACITY_MARGINS['outstation']['premiumEconomy']*100}%)")
        logger.info(f"  A4: End-game drain (purchase cutoff: {END_GAME_PURCHASE_CUTOFF}h, reposition: {END_GAME_REPOSITION_CUTOFF}h)")
        logger.info(f"  C1: Lookahead {LOOKAHEAD_HOURS}h for SCHEDULED flights")
        logger.info(f"  A1: Loading cost awareness enabled")
    
    def _build_demand_forecast(self):
        self.departures_by_airport_day: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
        for pattern in self.flight_patterns:
            for day in pattern.days_of_week:
                self.departures_by_airport_day[pattern.origin][day] += 1
    
    def _build_loading_cost_rankings(self):
        """NEW A1: Rank airports by loading cost for each class"""
        self.loading_cost_rank: Dict[str, Dict[str, int]] = {}
        
        for class_name in CLASS_NAMES:
            costs = [(code, airport.get_loading_cost(class_name)) 
                    for code, airport in self.airports.items()]
            costs.sort(key=lambda x: x[1])
            
            self.loading_cost_rank[class_name] = {code: rank for rank, (code, _) in enumerate(costs)}
        
        # Calculate average loading cost for reference
        self.avg_loading_cost = {
            class_name: sum(a.get_loading_cost(class_name) for a in self.airports.values()) / len(self.airports)
            for class_name in CLASS_NAMES
        }
        logger.info(f"Avg loading costs: F=€{self.avg_loading_cost['first']:.2f}, "
                   f"B=€{self.avg_loading_cost['business']:.2f}, "
                   f"PE=€{self.avg_loading_cost['premiumEconomy']:.2f}, "
                   f"E=€{self.avg_loading_cost['economy']:.2f}")
    
    def _get_dynamic_reposition_percentage(self, current_hour: int, class_name: str = 'economy') -> float:
        """F2: Dynamic reposition percentage based on game phase AND class"""
        hours_remaining = TIME_HORIZON - current_hour
        
        class_percentages = REPOSITION_PERCENTAGE.get(class_name, REPOSITION_PERCENTAGE['economy'])
        
        if hours_remaining > 220:  # First ~500 hours (days 0-20)
            return class_percentages['early']
        elif hours_remaining > 50:  # Hours 500-670 (days 20-28)
            return class_percentages['mid']
        else:  # Last ~50 hours (days 28-30)
            return class_percentages['late']
    
    def _has_return_flight_soon(self, origin: str, destination: str, current_hour: int) -> bool:
        """C3: Check if a return flight exists within 24 hours"""
        current_day = current_hour // 24
        current_hour_of_day = current_hour % 24
        day_of_week = current_day % 7
        
        # Check next 24 hours for return flights
        for lookahead in range(24):
            check_hour = (current_hour_of_day + lookahead) % 24
            check_day = (day_of_week + (current_hour_of_day + lookahead) // 24) % 7
            
            for pattern in self.flight_patterns:
                # Return flight: destination -> origin
                if pattern.origin == destination and pattern.destination == origin:
                    if check_day in pattern.days_of_week and pattern.departure_hour == check_hour:
                        return True
        
        return False
    
    def _get_forecasted_departures(self, airport: str, current_hour: int, lookahead_hours: int) -> int:
        total = 0
        for h in range(current_hour, current_hour + lookahead_hours):
            day = (h // 24) % 7
            hour_of_day = h % 24
            for pattern in self.flight_patterns:
                if pattern.origin == airport and day in pattern.days_of_week:
                    if pattern.departure_hour == hour_of_day:
                        total += 1
        return total
    
    def _get_distance(self, origin: str, destination: str, flight: dict) -> float:
        api_distance = flight.get('distance') or flight.get('scheduledDistance')
        if api_distance and api_distance > 0:
            self.stats['distance_used_from_api'] += 1
            return float(api_distance)
        
        csv_distance = self.route_distances.get((origin, destination))
        if csv_distance:
            self.stats['distance_used_from_csv'] += 1
            return csv_distance
        
        return 3000.0
    
    def _get_aircraft_type(self, flight: dict) -> Optional[AircraftType]:
        aircraft_code = flight.get('aircraftType') or flight.get('aircraftTypeCode')
        if aircraft_code and aircraft_code in self.aircraft_types:
            self.stats['aircraft_type_found'] += 1
            return self.aircraft_types[aircraft_code]
        
        if self.aircraft_types:
            self.stats['aircraft_type_missing'] += 1
            return min(self.aircraft_types.values(), key=lambda a: a.economy_kits_capacity)
        return None
    
    def _calculate_unfulfilled_penalty(self, class_name: str, distance: float, count: int) -> float:
        if count <= 0:
            return 0.0
        kit_cost = KIT_TYPES[class_name]['cost']
        return PENALTY_FACTORS['UNFULFILLED_KIT_FACTOR_PER_DISTANCE'] * kit_cost * distance * count
    
    def _calculate_movement_cost(self, class_name: str, distance: float, count: int, 
                                  aircraft: Optional[AircraftType] = None) -> float:
        if count <= 0:
            return 0.0
        weight = KIT_TYPES[class_name]['weight']
        cost_per_kg_km = aircraft.cost_per_kg_per_km if aircraft else 0.10
        return weight * distance * cost_per_kg_km * count
    
    def _get_inventory(self, airport: str, class_name: str) -> int:
        return max(0, self.inventory.get(airport, {}).get(class_name, 0))
    
    def _get_pending_arrivals(self, airport: str, class_name: str) -> int:
        return sum(m.quantity for m in self.scheduled_movements 
                  if m.airport == airport and m.class_name == class_name)
    
    def _get_available_space(self, airport: str, class_name: str, is_hub: bool) -> int:
        """NEW B3: Class-specific capacity margins"""
        capacity = self.airports[airport].get_capacity(class_name)
        current = self._get_inventory(airport, class_name)
        pending = self._get_pending_arrivals(airport, class_name)
        effective = current + pending
        
        # B3: Use class-specific margins
        if is_hub:
            margin = CAPACITY_MARGINS['hub'].get(class_name, 0.70)
        else:
            margin = CAPACITY_MARGINS['outstation'].get(class_name, 0.90)
        
        safe_capacity = int(capacity * margin)
        return max(0, safe_capacity - effective)
    
    def _is_end_game_purchase_blocked(self, current_hour: int) -> bool:
        """NEW A4: Check if we're in end-game purchase blackout"""
        return current_hour >= TIME_HORIZON - END_GAME_PURCHASE_CUTOFF
    
    def _is_end_game_reposition_blocked(self, current_hour: int) -> bool:
        """NEW A4: Check if we're in end-game reposition blackout"""
        return current_hour >= TIME_HORIZON - END_GAME_REPOSITION_CUTOFF
    
    def _process_scheduled_movements(self, current_hour: int):
        due = [m for m in self.scheduled_movements if m.hour == current_hour]
        for movement in due:
            self.inventory[movement.airport][movement.class_name] = \
                self.inventory[movement.airport].get(movement.class_name, 0) + movement.quantity
        self.scheduled_movements = [m for m in self.scheduled_movements if m.hour > current_hour]
    
    def _process_lookahead_flights(self, flights: list, current_hour: int):
        """NEW C1: Process SCHEDULED flights to anticipate demand"""
        self.anticipated_demand.clear()
        
        for flight in flights:
            if flight.get('eventType') != 'SCHEDULED':
                continue
            
            # Get departure time
            departure = flight.get('departure', {})
            if isinstance(departure, dict):
                dep_day = departure.get('day', 0)
                dep_hour = departure.get('hour', 0)
                dep_time = dep_day * 24 + dep_hour
            else:
                continue
            
            # Only look at flights departing within LOOKAHEAD_HOURS
            if dep_time - current_hour > LOOKAHEAD_HOURS:
                continue
            if dep_time <= current_hour:
                continue  # Already passed or current
            
            origin = flight.get('originAirport', '')
            passengers = flight.get('passengers', {})
            
            if origin and origin in self.airports:
                for class_name in CLASS_NAMES:
                    pax = passengers.get(class_name, 0)
                    self.anticipated_demand[origin][class_name] += pax
        
        # Log if we found anticipated demand
        total_anticipated = sum(sum(v.values()) for v in self.anticipated_demand.values())
        if total_anticipated > 0:
            self.stats['lookahead_prepositions'] += 1
    
    def _calculate_smart_repositioning(self, origin: str, destination: str, 
                                       distance: float, available_space: Dict[str, int],
                                       aircraft: Optional[AircraftType],
                                       already_loaded: Dict[str, int],
                                       current_hour: int,
                                       arrival_hour: int = None) -> Dict[str, int]:
        """Smart repositioning with all optimizations"""
        reposition = {'first': 0, 'business': 0, 'premiumEconomy': 0, 'economy': 0}
        
        # A4: Check end-game reposition blackout
        if self._is_end_game_reposition_blocked(current_hour):
            self.stats['end_game_reposition_blocked'] += 1
            return reposition
        
        # D3: Don't reposition for flights arriving after game ends
        if arrival_hour is not None and arrival_hour >= END_GAME_ARRIVAL_CUTOFF:
            self.stats['end_game_flight_filtered'] = self.stats.get('end_game_flight_filtered', 0) + 1
            return reposition
        
        for class_name in REPOSITION_CLASSES:
            # E4: Class-specific max reposition distance
            max_distance = MAX_REPOSITION_DISTANCE.get(class_name, 2500)
            if distance > max_distance:
                continue  # Skip this class, try next
            forecasted_departures = self._get_forecasted_departures(destination, current_hour, FORECAST_HOURS)
            
            # C1: Consider anticipated demand but DON'T add it to stock calculations
            # (just use it as a hint for whether to reposition)
            anticipated = self.anticipated_demand.get(destination, {}).get(class_name, 0)
            
            if forecasted_departures == 0 and anticipated == 0:
                continue
            
            origin_stock = self._get_inventory(origin, class_name) - already_loaded.get(class_name, 0)
            dest_stock = self._get_inventory(destination, class_name)
            
            origin_departures = self._get_forecasted_departures(origin, current_hour, FORECAST_HOURS)
            # DON'T subtract anticipated from origin - that was causing under-loading
            origin_surplus = origin_stock - (origin_departures * 50)
            
            if origin_surplus <= 0:
                continue
            
            # C1: Use anticipated as a boost factor, not additional demand
            # If there's anticipated demand, increase confidence in repositioning
            dest_need = max(0, (forecasted_departures * 50) - dest_stock)
            if anticipated > 0:
                dest_need = int(dest_need * 1.1)  # 10% boost if we see upcoming demand
            
            max_from_aircraft = float('inf')
            if aircraft:
                aircraft_capacity = aircraft.get_kit_capacity(class_name)
                already_on_flight = already_loaded.get(class_name, 0)
                max_from_aircraft = max(0, aircraft_capacity - already_on_flight)
            
            # F2: Use dynamic reposition percentage based on game phase AND class
            dynamic_percentage = self._get_dynamic_reposition_percentage(current_hour, class_name)
            
            reposition_amount = min(
                int(origin_surplus * dynamic_percentage),
                dest_need,
                available_space.get(class_name, 0),
                max_from_aircraft
            )
            
            # C3: DISABLED - Tested combinations but made things worse
            # - C3 alone: +€226K (reduced too much)
            # - C3 + higher base: +€298K (movement cost increase outweighed savings)
            # if reposition_amount > 0 and self._has_return_flight_soon(origin, destination, current_hour):
            #     reposition_amount = int(reposition_amount * 0.5)
            #     self.stats['return_flight_reduced'] = self.stats.get('return_flight_reduced', 0) + 1
            
            if reposition_amount > 0:
                movement_cost = self._calculate_movement_cost(class_name, distance, reposition_amount, aircraft)
                potential_penalty = self._calculate_unfulfilled_penalty(class_name, distance, reposition_amount)
                
                # A1: Factor in loading cost difference
                origin_loading = self.airports[origin].get_loading_cost(class_name)
                dest_loading = self.airports[destination].get_loading_cost(class_name)
                loading_cost_delta = (dest_loading - origin_loading) * reposition_amount
                
                # A3: Aircraft cost awareness - penalize expensive aircraft
                # Cheapest aircraft: 0.08/kg/km, most expensive: 0.11/kg/km
                # If using expensive aircraft, reduce repositioning threshold
                aircraft_cost_factor = 1.0
                if aircraft:
                    # Normalize: 0.08 -> 1.0, 0.11 -> 1.375 (penalize expensive)
                    aircraft_cost_factor = aircraft.cost_per_kg_per_km / 0.08
                
                # Adjust decision based on loading cost AND aircraft cost
                adjusted_movement_cost = (movement_cost * aircraft_cost_factor) + max(0, loading_cost_delta)
                
                # B1: For business class, use same threshold as economy since it's also rotable
                # Business has 3,754 unfulfilled - we need to be more aggressive
                threshold = 0.2  # Same for all classes
                
                # Always allow economy and business repositioning on short flights
                if potential_penalty * threshold > adjusted_movement_cost or class_name in ['economy', 'business']:
                    reposition[class_name] = reposition_amount
                    self.stats['kits_repositioned'][class_name] += reposition_amount
                    self.stats['penalty_decisions']['reposition_approved'] += 1
                    
                    # Track loading cost impact
                    if loading_cost_delta < 0:
                        self.stats['loading_cost_savings'] += abs(loading_cost_delta)
                else:
                    self.stats['penalty_decisions']['reposition_rejected_cost'] += 1
        
        return reposition
    
    def _calculate_flight_loads(self, flights: list, current_hour: int) -> list:
        """Flight loading with all optimizations"""
        self.stats['current_hour'] = current_hour
        
        # C1: Process lookahead for SCHEDULED flights
        self._process_lookahead_flights(flights, current_hour)
        
        flight_loads = []
        
        for flight in flights:
            if flight.get('eventType') != 'CHECKED_IN':
                continue
            
            flight_id = flight.get('flightId', '')
            origin = flight.get('originAirport', '')
            destination = flight.get('destinationAirport', '')
            passengers = flight.get('passengers', {})
            
            if origin not in self.airports or destination not in self.airports:
                flight_loads.append({
                    'flightId': flight_id,
                    'loadedKits': {'first': 0, 'business': 0, 'premiumEconomy': 0, 'economy': 0}
                })
                continue
            
            is_dest_hub = (destination == self.hub_code)
            distance = self._get_distance(origin, destination, flight)
            aircraft = self._get_aircraft_type(flight)
            
            # D3: Get arrival time early for end-game flight filtering
            arrival_info = flight.get('arrival', {})
            if isinstance(arrival_info, dict):
                arr_day = arrival_info.get('day', 0)
                arr_hour = arrival_info.get('hour', 0)
                arrival_time = arr_day * 24 + arr_hour
            else:
                arrival_time = current_hour + 2
            
            loaded_kits = {}
            available_space = {}
            
            for class_name in CLASS_NAMES:
                pax = passengers.get(class_name, 0)
                available_at_origin = self._get_inventory(origin, class_name)
                space_at_dest = self._get_available_space(destination, class_name, is_dest_hub)
                available_space[class_name] = space_at_dest
                
                max_on_aircraft = float('inf')
                if aircraft:
                    max_on_aircraft = aircraft.get_kit_capacity(class_name)
                
                max_loadable = min(available_at_origin, space_at_dest, max_on_aircraft)
                desired = pax
                actual = min(desired, max_loadable)
                loaded_kits[class_name] = actual
                
                if actual < pax:
                    shortfall = pax - actual
                    if available_at_origin < pax:
                        self.stats['unfulfilled'][class_name] += shortfall
                    elif space_at_dest < pax:
                        self.stats['capacity_reduced'][class_name] += shortfall
                    elif max_on_aircraft < pax:
                        self.stats['aircraft_capacity_limited'][class_name] += shortfall
                
                available_space[class_name] = max(0, space_at_dest - actual)
            
            # Smart repositioning (with all optimizations including D3 end-game filtering)
            if not is_dest_hub:
                reposition = self._calculate_smart_repositioning(
                    origin, destination, distance, available_space, aircraft, loaded_kits, 
                    current_hour, arrival_hour=arrival_time
                )
                for class_name in CLASS_NAMES:
                    if reposition[class_name] > 0:
                        current_stock = self._get_inventory(origin, class_name) - loaded_kits[class_name]
                        extra = min(reposition[class_name], current_stock)
                        loaded_kits[class_name] += extra
            
            # Update inventory
            for class_name in CLASS_NAMES:
                self.inventory[origin][class_name] = max(0,
                    self.inventory[origin].get(class_name, 0) - loaded_kits[class_name])
            
            flight_loads.append({'flightId': flight_id, 'loadedKits': loaded_kits})
            
            # Schedule arrival (arrival_time already calculated above for D3)
            dest_airport = self.airports[destination]
            for class_name in CLASS_NAMES:
                qty = loaded_kits[class_name]
                if qty > 0:
                    processing_time = dest_airport.get_processing_time(class_name)
                    ready_time = arrival_time + processing_time
                    self.scheduled_movements.append(
                        KitMovement(ready_time, destination, class_name, qty)
                    )
            
            self.stats['flights_loaded'] += 1
            for c, q in loaded_kits.items():
                self.stats['kits_loaded'][c] += q
        
        return flight_loads
    
    def _calculate_purchases(self, flight_loads: list, current_hour: int) -> Dict[str, int]:
        """Purchasing with end-game drain"""
        purchases = {'first': 0, 'business': 0, 'premiumEconomy': 0, 'economy': 0}
        
        # A4: End-game purchase blackout
        if self._is_end_game_purchase_blocked(current_hour):
            self.stats['end_game_purchases_blocked'] += 1
            return purchases
        
        needed_now = {c: 0 for c in CLASS_NAMES}
        for load in flight_loads:
            for c in CLASS_NAMES:
                needed_now[c] += load['loadedKits'].get(c, 0)
        
        hub = self.hub_code
        forecasted_departures = self._get_forecasted_departures(hub, current_hour, FORECAST_HOURS)
        
        # NOTE: C1 lookahead should NOT affect purchasing (causes over-buying)
        # Only use forecasted departures for purchasing decisions
        
        for class_name in CLASS_NAMES:
            current = self._get_inventory(hub, class_name)
            
            pending = 0
            lead_time = KIT_TYPES[class_name]['lead_time']
            for t in range(current_hour, current_hour + lead_time + 24):
                pending += self.pending_purchases.get(t, {}).get(class_name, 0)
            
            effective = current + pending
            stock_after = effective - needed_now[class_name]
            
            # Use only forecasted departures (NOT anticipated demand - that caused over-buying)
            estimated_future_need = forecasted_departures * 30
            projected_stock = stock_after - estimated_future_need
            
            if projected_stock < 0:
                shortfall = abs(projected_stock)
                purchase_cost = shortfall * KIT_TYPES[class_name]['cost']
                avg_distance = 4000
                unfulfilled_penalty = self._calculate_unfulfilled_penalty(class_name, avg_distance, shortfall)
                
                if unfulfilled_penalty > purchase_cost:
                    buy = int(shortfall * PURCHASE_BUFFER)
                    self.stats['penalty_decisions']['purchase_penalty_driven'] += 1
                else:
                    buy = int(shortfall * 0.8)
                    self.stats['penalty_decisions']['purchase_cost_conscious'] += 1
                
                if buy > 0:
                    purchases[class_name] = buy
                    arrival = current_hour + lead_time
                    self.pending_purchases[arrival][class_name] += buy
                    self.stats['kits_purchased'][class_name] += buy
        
        return purchases
    
    def _process_response(self, response: dict, current_hour: int):
        self._process_scheduled_movements(current_hour)
        
        if current_hour in self.pending_purchases:
            for c, q in self.pending_purchases[current_hour].items():
                self.inventory[self.hub_code][c] = self.inventory[self.hub_code].get(c, 0) + q
            del self.pending_purchases[current_hour]
    
    def _display_round_results(self, response: Dict, day: int, hour: int):
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
                ptype = penalty.get('code', penalty.get('penaltyType', 'UNKNOWN'))
                logger.warning(f"  - {ptype}: €{penalty.get('penalty', 0):,.2f}")
    
    def solve(self):
        logger.info("=" * 60)
        logger.info("ULTIMATE SOLVER (All Optimizations)")
        logger.info("=" * 60)
        logger.info(f"B3: PE margin = {CAPACITY_MARGINS['outstation']['premiumEconomy']*100}%")
        logger.info(f"A4: Purchase cutoff = {END_GAME_PURCHASE_CUTOFF}h, Reposition cutoff = {END_GAME_REPOSITION_CUTOFF}h")
        logger.info(f"C1: Lookahead = {LOOKAHEAD_HOURS}h")
        logger.info(f"A1: Loading cost awareness enabled")
        logger.info("=" * 60)
        
        self.api_client.start_session()
        self.stats['start_time'] = time.time()
        self.stats['api_requests'] = 1
        self.stats['api_successful'] = 1
        self.last_response = None
        completed_all_rounds = False
        
        try:
            previous_response = None
            
            for hour in range(TIME_HORIZON):
                day = hour // 24
                hour_of_day = hour % 24
                
                if hour_of_day == 0:
                    elapsed = time.time() - self.stats['start_time']
                    progress = (hour / 720) * 100
                    logger.info(f"[Day {day}] Progress: {progress:.1f}%, Elapsed: {elapsed:.1f}s")
                
                self._process_scheduled_movements(hour)
                
                if previous_response is None:
                    flight_loads = []
                    purchases = {'first': 0, 'business': 0, 'premiumEconomy': 0, 'economy': 0}
                else:
                    flights = previous_response.get("flightUpdates", [])
                    flight_loads = self._calculate_flight_loads(flights, hour)
                    purchases = self._calculate_purchases(flight_loads, hour)
                
                try:
                    self.stats['api_requests'] += 1
                    previous_response = self.api_client.play_round(
                        day=day, hour=hour_of_day,
                        flight_loads=flight_loads,
                        kit_purchasing_orders=purchases
                    )
                    self.stats['api_successful'] += 1
                    self.stats['rounds_played'] += 1
                    
                    self._process_response(previous_response, hour)
                    self._display_round_results(previous_response, day, hour_of_day)
                    self.last_response = previous_response
                    
                    current_day = previous_response.get('currentDay', previous_response.get('day', day))
                    current_hour_resp = previous_response.get('currentHour', previous_response.get('hour', hour_of_day))
                    if current_day >= 29 and current_hour_resp >= 23:
                        logger.info("Reached end of simulation")
                        completed_all_rounds = True
                        break
                        
                except requests.exceptions.HTTPError as e:
                    self.stats['api_failed'] = self.stats.get('api_failed', 0) + 1
                    logger.error(f"Error in round: {e}")
                    break
            
        except KeyboardInterrupt:
            logger.warning("Interrupted")
        except Exception as e:
            logger.exception(f"Error: {e}")
        finally:
            logger.info("=" * 60)
            logger.info("Ending session...")
            try:
                end_response = self.api_client.end_session()
                if isinstance(end_response, dict) and 'totalCost' in end_response:
                    self.last_response = end_response
            except Exception as e:
                logger.warning(f"Could not end session: {e}")
            
            self._print_summary(self.last_response)
    
    def _print_summary(self, display_result: Optional[Dict]):
        total_duration = time.time() - self.stats['start_time'] if self.stats['start_time'] else 0
        
        print("\n" + "=" * 60)
        print("ULTIMATE SOLVER SUMMARY")
        print("=" * 60)
        
        if display_result:
            total_cost = display_result.get('totalCost', 0)
            print(f"\n🎯 Total Cost: €{total_cost:,.2f}")
            print(f"   Rounds: {self.stats['rounds_played']}")
            
            print(f"\nKit Statistics:")
            print(f"  Loaded:       F={self.stats['kits_loaded']['first']}, "
                  f"B={self.stats['kits_loaded']['business']}, "
                  f"PE={self.stats['kits_loaded']['premiumEconomy']}, "
                  f"E={self.stats['kits_loaded']['economy']}")
            print(f"  Purchased:    F={self.stats['kits_purchased']['first']}, "
                  f"B={self.stats['kits_purchased']['business']}, "
                  f"PE={self.stats['kits_purchased']['premiumEconomy']}, "
                  f"E={self.stats['kits_purchased']['economy']}")
            print(f"  Repositioned: F={self.stats['kits_repositioned']['first']}, "
                  f"B={self.stats['kits_repositioned']['business']}, "
                  f"PE={self.stats['kits_repositioned']['premiumEconomy']}, "
                  f"E={self.stats['kits_repositioned']['economy']}")
            
            print(f"\nData Sources:")
            print(f"  Distance from API: {self.stats['distance_used_from_api']}")
            print(f"  Aircraft type found: {self.stats['aircraft_type_found']}")
            
            print(f"\nDemand Issues:")
            print(f"  Unfulfilled:        {dict(self.stats['unfulfilled'])}")
            print(f"  Capacity-reduced:   {dict(self.stats['capacity_reduced'])}")
            print(f"  Aircraft-limited:   {dict(self.stats['aircraft_capacity_limited'])}")
            
            print(f"\nOptimization Stats:")
            print(f"  B3 (Capacity margins): PE outstation = {CAPACITY_MARGINS['outstation']['premiumEconomy']*100}%")
            print(f"  A4 (End-game): Purchases blocked = {self.stats['end_game_purchases_blocked']}, "
                  f"Repositions blocked = {self.stats['end_game_reposition_blocked']}")
            print(f"  D3 (Late flights): Filtered = {self.stats.get('end_game_flight_filtered', 0)}")
            print(f"  C1 (Lookahead): Pre-positions = {self.stats['lookahead_prepositions']}")
            print(f"  A1 (Loading cost): Savings = €{self.stats['loading_cost_savings']:,.2f}")
            print(f"  A3 (Aircraft cost): Factored into movement cost decisions")
            print(f"  C3 (Return flight): Reduced = {self.stats.get('return_flight_reduced', 0)}")
            
            print(f"\nDecision Stats:")
            for k, v in self.stats['penalty_decisions'].items():
                print(f"  {k}: {v}")
            
            penalties = display_result.get('penalties', [])
            total_penalty = sum(p.get('penalty', 0) for p in penalties)
            print(f"\nPenalties: {len(penalties)} (€{total_penalty:,.2f})")
            
            if penalties:
                penalty_by_type = defaultdict(lambda: {'count': 0, 'cost': 0.0})
                for p in penalties:
                    ptype = p.get('code', p.get('penaltyType', 'UNKNOWN'))
                    pcost = p.get('penalty', 0)
                    penalty_by_type[ptype]['count'] += 1
                    penalty_by_type[ptype]['cost'] += pcost
                
                for ptype, data in sorted(penalty_by_type.items(), key=lambda x: -x[1]['cost']):
                    print(f"  {ptype}: {data['count']} (€{data['cost']:,.2f})")
        
        print(f"\nDuration: {total_duration:.1f}s")
        print("=" * 60)
        
        if display_result:
            total_cost = display_result.get('totalCost', 0)
            if total_cost < 1_000_000_000:
                print("🎉 Under €1 BILLION!")
            print(f"✓ Final: €{total_cost:,.2f}")


def main():
    import argparse
    
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    
    default_api_key = os.getenv("API_KEY", "43b9ab90-b593-404c-a8d8-aaa074e181e1")
    default_base_url = os.getenv("BASE_URL", "http://127.0.0.1:8080/api/v1")
    
    parser = argparse.ArgumentParser(description="Ultimate solver with all optimizations")
    parser.add_argument("--api-key", type=str, default=default_api_key)
    parser.add_argument("--base-url", type=str, default=default_base_url)
    parser.add_argument("--log-level", type=str, default="INFO")
    parser.add_argument("--resources-dir", type=str, default="resources")
    
    args = parser.parse_args()
    setup_logging(log_level=args.log_level)
    
    logger.info("=" * 60)
    logger.info("Rotables Challenge - ULTIMATE Solver")
    logger.info("=" * 60)
    
    data_loader = DataLoader(args.resources_dir)
    api_client = ApiClient(base_url=args.base_url, api_key=args.api_key)
    solver = UltimateSolver(api_client, data_loader)
    solver.solve()


if __name__ == "__main__":
    main()
