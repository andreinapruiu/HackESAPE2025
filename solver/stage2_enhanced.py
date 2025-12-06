"""
Stage 2 ENHANCED Solver
========================

Built on colleague-style strategy with additional optimizations:

1. DISTANCE-AWARE: Uses distance from API for smarter loading decisions
2. DEMAND FORECASTING: Uses flight_plan.csv to predict upcoming demand
3. SMART REPOSITIONING: Economy-only, short-flights-only repositioning
4. PROACTIVE PURCHASING: Buy ahead based on forecasted demand

Key strategies preserved from colleague:
- Exact passenger loading (primary)
- Capacity-aware with different margins (HUB: 70%, Outstations: 90%)
- Track ALL airport inventories
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

KIT_TYPES = {
    'first': {'cost': 200.0, 'weight': 5.0, 'lead_time': 48},
    'business': {'cost': 150.0, 'weight': 3.0, 'lead_time': 36},
    'premiumEconomy': {'cost': 100.0, 'weight': 2.5, 'lead_time': 24},
    'economy': {'cost': 50.0, 'weight': 1.5, 'lead_time': 12}
}

CLASS_NAMES = ['first', 'business', 'premiumEconomy', 'economy']
TIME_HORIZON = 720

# Smart repositioning parameters
MAX_REPOSITION_DISTANCE = 2500  # Only reposition on flights under this distance (km)
REPOSITION_CLASSES = ['economy']  # Only reposition these light classes
REPOSITION_PERCENTAGE = 0.15  # Only fill 15% of extra capacity with repositioned kits

# Proactive purchasing parameters
FORECAST_HOURS = 48  # Look ahead this many hours for demand
PURCHASE_BUFFER = 1.1  # Buy 10% more than minimum needed


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


@dataclass
class FlightPattern:
    """Flight pattern from flight_plan.csv"""
    origin: str
    destination: str
    departure_hour: int
    arrival_hour: int
    arrival_next_day: bool
    distance_km: float
    days_of_week: List[int]  # 0=Mon, 1=Tue, ..., 6=Sun


class DataLoader:
    def __init__(self, resources_dir: str = "resources"):
        self.resources_dir = Path(resources_dir)
        if not self.resources_dir.exists():
            self.resources_dir = Path(__file__).parent / resources_dir
    
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
        """Load flight patterns from flight_plan.csv for demand forecasting"""
        patterns = []
        csv_path = self.resources_dir / "flight_plan.csv"
        if not csv_path.exists():
            logger.warning(f"flight_plan.csv not found at {csv_path}")
            return patterns
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                # Parse days of week
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
        
        logger.info(f"Loaded {len(patterns)} flight patterns from flight_plan.csv")
        return patterns


class KitMovement:
    """Scheduled kit movement (arrival after processing)"""
    def __init__(self, hour: int, airport: str, class_name: str, quantity: int):
        self.hour = hour
        self.airport = airport
        self.class_name = class_name
        self.quantity = quantity


class EnhancedSolver:
    """
    Enhanced solver with:
    - Distance-aware loading (from API)
    - Demand forecasting (from flight_plan.csv)
    - Smart repositioning (economy only, short flights)
    - Proactive purchasing
    """
    
    def __init__(self, api_client: ApiClient, data_loader: DataLoader):
        self.api_client = api_client
        self.airports = data_loader.load_airports()
        self.flight_patterns = data_loader.load_flight_patterns()
        
        # Build route distance lookup from flight_plan.csv
        self.route_distances: Dict[Tuple[str, str], float] = {}
        for pattern in self.flight_patterns:
            self.route_distances[(pattern.origin, pattern.destination)] = pattern.distance_km
        logger.info(f"Built route distance lookup with {len(self.route_distances)} routes")
        
        # Build demand forecast by airport and day-of-week
        self._build_demand_forecast()
        
        # Identify HUB (highest capacity)
        self.hub_code = max(self.airports.keys(), 
                           key=lambda c: sum(self.airports[c].get_capacity(cls) for cls in CLASS_NAMES))
        
        # Initialize inventory for ALL airports from CSV
        self.inventory: Dict[str, Dict[str, int]] = {}
        for code, airport in self.airports.items():
            self.inventory[code] = {
                'first': airport.initial_fc,
                'business': airport.initial_bc,
                'premiumEconomy': airport.initial_pe,
                'economy': airport.initial_ec
            }
        
        # Track scheduled movements (kits in transit + processing)
        self.scheduled_movements: List[KitMovement] = []
        
        # Pending purchases
        self.pending_purchases: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        
        # Statistics
        self.stats = {
            'rounds_played': 0, 'flights_loaded': 0,
            'kits_loaded': defaultdict(int), 'kits_purchased': defaultdict(int),
            'kits_repositioned': defaultdict(int),
            'unfulfilled': defaultdict(int), 'capacity_reduced': defaultdict(int),
            'start_time': None, 'penalties': defaultdict(int), 'penalty_cost': defaultdict(float),
            'distance_used_from_api': 0, 'distance_used_from_csv': 0
        }
        
        total = {c: sum(self.inventory[a].get(c, 0) for a in self.inventory) for c in CLASS_NAMES}
        logger.info(f"Initial inventory: F={total['first']}, B={total['business']}, "
                   f"PE={total['premiumEconomy']}, E={total['economy']}")
        logger.info(f"HUB identified: {self.hub_code}")
        logger.info(f"ENHANCED SOLVER: Distance-aware, demand forecasting, smart repositioning")
    
    def _build_demand_forecast(self):
        """Build demand forecast from flight patterns (departures from each airport by day)"""
        # Count flights departing from each airport on each day of week
        self.departures_by_airport_day: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self.arrivals_by_airport_day: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
        
        for pattern in self.flight_patterns:
            for day in pattern.days_of_week:
                self.departures_by_airport_day[pattern.origin][day] += 1
                self.arrivals_by_airport_day[pattern.destination][day] += 1
        
        logger.info(f"Built demand forecast for {len(self.departures_by_airport_day)} airports")
    
    def _get_forecasted_departures(self, airport: str, current_hour: int, lookahead_hours: int) -> int:
        """Forecast number of departures from airport in next lookahead_hours"""
        total_departures = 0
        
        for h in range(current_hour, current_hour + lookahead_hours):
            day = (h // 24) % 7  # Day of week (0-6)
            hour_of_day = h % 24
            
            # Check flight patterns for this day/hour
            for pattern in self.flight_patterns:
                if pattern.origin == airport and day in pattern.days_of_week:
                    if pattern.departure_hour == hour_of_day:
                        total_departures += 1
        
        return total_departures
    
    def _get_distance(self, origin: str, destination: str, flight: dict) -> float:
        """
        Get flight distance - prefer API data, fallback to flight_plan.csv
        """
        # First try API distance (new feature!)
        api_distance = flight.get('distance') or flight.get('scheduledDistance')
        if api_distance and api_distance > 0:
            self.stats['distance_used_from_api'] += 1
            return float(api_distance)
        
        # Fallback to flight_plan.csv lookup
        csv_distance = self.route_distances.get((origin, destination))
        if csv_distance:
            self.stats['distance_used_from_csv'] += 1
            return csv_distance
        
        # Default estimate
        return 3000.0  # Average distance
    
    def _get_inventory(self, airport: str, class_name: str) -> int:
        """Get current inventory at airport"""
        return max(0, self.inventory.get(airport, {}).get(class_name, 0))
    
    def _get_pending_arrivals(self, airport: str, class_name: str) -> int:
        """Get kits scheduled to arrive at airport (in transit + processing)"""
        return sum(m.quantity for m in self.scheduled_movements 
                  if m.airport == airport and m.class_name == class_name)
    
    def _get_available_space(self, airport: str, class_name: str, is_hub: bool) -> int:
        """
        Capacity-aware with different margins for HUB vs Outstations
        """
        capacity = self.airports[airport].get_capacity(class_name)
        current = self._get_inventory(airport, class_name)
        pending = self._get_pending_arrivals(airport, class_name)
        
        effective = current + pending
        
        # Different margins (from colleague strategy)
        margin = 0.70 if is_hub else 0.90
        safe_capacity = int(capacity * margin)
        
        return max(0, safe_capacity - effective)
    
    def _process_scheduled_movements(self, current_hour: int):
        """Process kit movements that complete this hour"""
        due = [m for m in self.scheduled_movements if m.hour == current_hour]
        
        for movement in due:
            self.inventory[movement.airport][movement.class_name] = \
                self.inventory[movement.airport].get(movement.class_name, 0) + movement.quantity
        
        self.scheduled_movements = [m for m in self.scheduled_movements if m.hour > current_hour]
    
    def _calculate_smart_repositioning(self, origin: str, destination: str, 
                                       distance: float, available_space: Dict[str, int],
                                       is_dest_hub: bool) -> Dict[str, int]:
        """
        Calculate smart repositioning - only economy on short flights
        """
        reposition = {'first': 0, 'business': 0, 'premiumEconomy': 0, 'economy': 0}
        
        # Only reposition on short flights
        if distance > MAX_REPOSITION_DISTANCE:
            return reposition
        
        # Only reposition specified classes (economy by default)
        for class_name in REPOSITION_CLASSES:
            # Check if destination needs kits (based on forecasted departures)
            current_hour = self.stats.get('current_hour', 0)
            forecasted_departures = self._get_forecasted_departures(destination, current_hour, FORECAST_HOURS)
            
            if forecasted_departures == 0:
                continue  # No upcoming departures, don't reposition
            
            # Check available stock at origin
            origin_stock = self._get_inventory(origin, class_name)
            dest_stock = self._get_inventory(destination, class_name)
            
            # Only reposition if origin has surplus and destination needs it
            # "Surplus" = more than what we need for upcoming departures from origin
            origin_departures = self._get_forecasted_departures(origin, current_hour, FORECAST_HOURS)
            origin_surplus = origin_stock - (origin_departures * 50)  # Estimate 50 kits per flight
            
            if origin_surplus <= 0:
                continue  # Origin needs its stock
            
            # Calculate how much to reposition (conservative)
            dest_need = max(0, (forecasted_departures * 50) - dest_stock)
            reposition_amount = min(
                int(origin_surplus * REPOSITION_PERCENTAGE),
                dest_need,
                available_space.get(class_name, 0)
            )
            
            if reposition_amount > 0:
                reposition[class_name] = reposition_amount
                self.stats['kits_repositioned'][class_name] += reposition_amount
        
        return reposition
    
    def _calculate_flight_loads(self, flights: list, current_hour: int) -> list:
        """
        Enhanced loading with:
        - Exact passenger loading (primary)
        - Distance-aware smart repositioning (economy, short flights)
        """
        self.stats['current_hour'] = current_hour
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
            
            # Get distance from API (new feature!) or fallback to CSV
            distance = self._get_distance(origin, destination, flight)
            
            loaded_kits = {}
            available_space = {}
            
            # First pass: load exact passenger needs
            for class_name in CLASS_NAMES:
                pax = passengers.get(class_name, 0)
                available_at_origin = self._get_inventory(origin, class_name)
                space_at_dest = self._get_available_space(destination, class_name, is_dest_hub)
                available_space[class_name] = space_at_dest
                
                # Load exactly what passengers need, respecting constraints
                desired = pax
                actual = min(desired, available_at_origin, space_at_dest)
                
                loaded_kits[class_name] = actual
                
                # Track reductions
                if actual < pax:
                    if available_at_origin < pax:
                        self.stats['unfulfilled'][class_name] += (pax - actual)
                    else:
                        self.stats['capacity_reduced'][class_name] += (pax - actual)
                
                # Update available space after passenger loading
                available_space[class_name] = max(0, space_at_dest - actual)
            
            # Second pass: smart repositioning (economy only, short flights)
            if not is_dest_hub:  # Don't reposition TO hub (it gets returns anyway)
                reposition = self._calculate_smart_repositioning(
                    origin, destination, distance, available_space, is_dest_hub
                )
                
                for class_name in CLASS_NAMES:
                    if reposition[class_name] > 0:
                        # Check we still have stock
                        current_stock = self._get_inventory(origin, class_name) - loaded_kits[class_name]
                        extra = min(reposition[class_name], current_stock)
                        loaded_kits[class_name] += extra
            
            # Update origin inventory
            for class_name in CLASS_NAMES:
                self.inventory[origin][class_name] = max(0,
                    self.inventory[origin].get(class_name, 0) - loaded_kits[class_name])
            
            flight_loads.append({'flightId': flight_id, 'loadedKits': loaded_kits})
            
            # Schedule arrival at destination (after flight + processing)
            arrival_info = flight.get('arrival', {})
            if isinstance(arrival_info, dict):
                arr_day = arrival_info.get('day', 0)
                arr_hour = arrival_info.get('hour', 0)
                arrival_time = arr_day * 24 + arr_hour
            else:
                arrival_time = current_hour + 2  # Fallback estimate
            
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
        """
        Proactive purchasing based on forecasted demand
        """
        purchases = {'first': 0, 'business': 0, 'premiumEconomy': 0, 'economy': 0}
        
        # Calculate kits needed this round
        needed_now = {c: 0 for c in CLASS_NAMES}
        for load in flight_loads:
            for c in CLASS_NAMES:
                needed_now[c] += load['loadedKits'].get(c, 0)
        
        hub = self.hub_code
        
        # Forecast future demand at HUB
        forecasted_departures = self._get_forecasted_departures(hub, current_hour, FORECAST_HOURS)
        
        for class_name in CLASS_NAMES:
            current = self._get_inventory(hub, class_name)
            
            # Get pending purchase arrivals
            pending = 0
            lead_time = KIT_TYPES[class_name]['lead_time']
            for t in range(current_hour, current_hour + lead_time + 24):
                pending += self.pending_purchases.get(t, {}).get(class_name, 0)
            
            effective = current + pending
            stock_after = effective - needed_now[class_name]
            
            # Proactive: also consider forecasted demand
            # Estimate ~50 kits per flight per class (rough average)
            estimated_future_need = forecasted_departures * 30  # Conservative estimate
            projected_stock = stock_after - estimated_future_need
            
            # Buy if projected stock would go negative
            if projected_stock < 0:
                buy = int(abs(projected_stock) * PURCHASE_BUFFER)
                purchases[class_name] = buy
                
                # Track purchase
                arrival = current_hour + lead_time
                self.pending_purchases[arrival][class_name] += buy
                self.stats['kits_purchased'][class_name] += buy
                
                logger.debug(f"PROACTIVE PURCHASE: {buy} {class_name} (current={current}, "
                            f"pending={pending}, needed_now={needed_now[class_name]}, "
                            f"forecasted_need={estimated_future_need})")
        
        return purchases
    
    def _process_response(self, response: dict, current_hour: int):
        """Process API response"""
        # Process scheduled movements for this hour
        self._process_scheduled_movements(current_hour)
        
        # Process pending purchases
        if current_hour in self.pending_purchases:
            for c, q in self.pending_purchases[current_hour].items():
                self.inventory[self.hub_code][c] = self.inventory[self.hub_code].get(c, 0) + q
            del self.pending_purchases[current_hour]
        
        # Track penalties
        for p in response.get('penalties', []):
            ptype = p.get('penaltyType', p.get('type', 'UNKNOWN'))
            pvalue = p.get('penalty', p.get('value', 0))
            self.stats['penalties'][ptype] += 1
            self.stats['penalty_cost'][ptype] += pvalue
    
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
                logger.warning(f"  - {penalty.get('penaltyType', penalty.get('code', 'UNKNOWN'))}: "
                             f"€{penalty.get('penalty', 0):,.2f}")
    
    def solve(self):
        """Main solving loop"""
        logger.info("=" * 60)
        logger.info("ENHANCED SOLVER (Distance-Aware + Demand Forecasting)")
        logger.info("=" * 60)
        logger.info(f"Strategy: Exact passenger loading + smart repositioning")
        logger.info(f"Repositioning: {REPOSITION_CLASSES} only, max {MAX_REPOSITION_DISTANCE}km")
        logger.info(f"Forecasting: {FORECAST_HOURS}h lookahead from flight_plan.csv")
        logger.info(f"Capacity margins: HUB=70%, Outstations=90%")
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
                
                # Progress logging every day
                if hour_of_day == 0:
                    elapsed = time.time() - self.stats['start_time']
                    progress = (hour / 720) * 100
                    logger.info(f"[Day {day}, Hour {hour_of_day}] Progress: {progress:.1f}%, Elapsed: {elapsed:.1f}s")
                
                # Process scheduled movements for this hour
                self._process_scheduled_movements(hour)
                
                if previous_response is None:
                    flight_loads = []
                    purchases = {'first': 0, 'business': 0, 'premiumEconomy': 0, 'economy': 0}
                else:
                    flights = previous_response.get("flightUpdates", [])
                    flight_loads = self._calculate_flight_loads(flights, hour)
                    purchases = self._calculate_purchases(flight_loads, hour)
                
                # Submit round
                try:
                    self.stats['api_requests'] += 1
                    previous_response = self.api_client.play_round(
                        day=day, hour=hour_of_day,
                        flight_loads=flight_loads,
                        kit_purchasing_orders=purchases
                    )
                    self.stats['api_successful'] += 1
                    self.stats['rounds_played'] += 1
                    
                    # Process response
                    self._process_response(previous_response, hour)
                    
                    # Display results
                    self._display_round_results(previous_response, day, hour_of_day)
                    self.last_response = previous_response
                    
                    # Check if we should continue
                    current_day = previous_response.get('currentDay', previous_response.get('day', day))
                    current_hour = previous_response.get('currentHour', previous_response.get('hour', hour_of_day))
                    if current_day >= 29 and current_hour >= 23:
                        logger.info("Reached end of simulation (Day 29, Hour 23)")
                        completed_all_rounds = True
                        break
                        
                except requests.exceptions.HTTPError as e:
                    self.stats['api_failed'] = self.stats.get('api_failed', 0) + 1
                    logger.error(f"Error in round Day {day}, Hour {hour_of_day}: {e}")
                    break
            
        except KeyboardInterrupt:
            logger.warning("Interrupted by user")
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
        finally:
            # Explicitly end session and capture response
            logger.info("=" * 60)
            logger.info("Ending session...")
            try:
                end_response = self.api_client.end_session()
                logger.info(f"END SESSION RESPONSE: {end_response}")
                
                if isinstance(end_response, dict):
                    if 'totalCost' in end_response:
                        self.last_response = end_response
                    logger.info(f"Final Total Cost from end_session: €{end_response.get('totalCost', 'N/A'):,}")
                    
                    end_penalties = end_response.get('penalties', [])
                    if end_penalties:
                        logger.info(f"End-game penalties ({len(end_penalties)}):")
                        for p in end_penalties[:10]:
                            logger.info(f"  - {p.get('penaltyType', 'UNKNOWN')}: €{p.get('penalty', 0):,.2f}")
                else:
                    logger.info(f"End session returned: {end_response}")
                    
            except Exception as e:
                logger.warning(f"Could not end session: {e}")
            
            if completed_all_rounds:
                logger.info("Completed all 720 rounds successfully")
            
            # Print comprehensive summary
            self._print_summary(self.last_response)
    
    def _print_summary(self, display_result: Optional[Dict]):
        """Print comprehensive execution summary"""
        total_duration = time.time() - self.stats['start_time'] if self.stats['start_time'] else 0
        
        print("\n" + "=" * 60)
        print("ENHANCED SOLVER EXECUTION SUMMARY")
        print("=" * 60)
        print()
        
        if display_result:
            total_cost = display_result.get('totalCost', 0)
            
            print("Final Results:")
            print(f"  Rounds Played:       {self.stats['rounds_played']}")
            print(f"  Final Day:           {display_result.get('currentDay', display_result.get('day', 29))}")
            print(f"  Final Hour:          {display_result.get('currentHour', display_result.get('hour', 23))}")
            print(f"  Total Cost:          €{total_cost:,.2f}")
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
            print(f"  Kits Repositioned:   "
                  f"F={self.stats['kits_repositioned']['first']}, "
                  f"B={self.stats['kits_repositioned']['business']}, "
                  f"PE={self.stats['kits_repositioned']['premiumEconomy']}, "
                  f"E={self.stats['kits_repositioned']['economy']}")
            print()
            
            print("Distance Data Source:")
            print(f"  From API:            {self.stats['distance_used_from_api']}")
            print(f"  From CSV fallback:   {self.stats['distance_used_from_csv']}")
            print()
            
            print("Demand Fulfillment:")
            print(f"  Unfulfilled (no stock): "
                  f"F={self.stats['unfulfilled']['first']}, "
                  f"B={self.stats['unfulfilled']['business']}, "
                  f"PE={self.stats['unfulfilled']['premiumEconomy']}, "
                  f"E={self.stats['unfulfilled']['economy']}")
            print(f"  Capacity-reduced:       "
                  f"F={self.stats['capacity_reduced']['first']}, "
                  f"B={self.stats['capacity_reduced']['business']}, "
                  f"PE={self.stats['capacity_reduced']['premiumEconomy']}, "
                  f"E={self.stats['capacity_reduced']['economy']}")
            print()
            
            # Calculate penalty totals from response
            penalties = display_result.get('penalties', [])
            total_penalty = sum(p.get('penalty', 0) for p in penalties)
            operational_cost = total_cost - total_penalty
            
            print("Penalty Statistics:")
            print(f"  Total Penalties:     {len(penalties)}")
            print(f"  Penalty Cost:        €{total_penalty:,.2f}")
            
            if penalties:
                print(f"  By Type:")
                penalty_by_type = defaultdict(lambda: {'count': 0, 'cost': 0.0})
                for penalty in penalties:
                    ptype = penalty.get('penaltyType', penalty.get('code', 'UNKNOWN'))
                    pcost = penalty.get('penalty', 0)
                    penalty_by_type[ptype]['count'] += 1
                    penalty_by_type[ptype]['cost'] += pcost
                
                sorted_penalties = sorted(penalty_by_type.items(), 
                                         key=lambda x: x[1]['cost'], reverse=True)
                for ptype, data in sorted_penalties:
                    print(f"    - {ptype}: {data['count']} (€{data['cost']:,.2f})")
            print()
            
            print("Cost Breakdown:")
            print(f"  Operational Cost:    €{operational_cost:,.2f}")
            print(f"  Penalty Cost:        €{total_penalty:,.2f} ({100*total_penalty/max(1,total_cost):.1f}%)")
            print()
        
        print("=" * 60)
        print("API REQUEST SUMMARY")
        print("=" * 60)
        print(f"Total Requests:      {self.stats.get('api_requests', 0)}")
        print(f"Successful:          {self.stats.get('api_successful', 0)}")
        print(f"Failed:              {self.stats.get('api_failed', 0)}")
        success_rate = 100 * self.stats.get('api_successful', 0) / max(1, self.stats.get('api_requests', 1))
        print(f"Success Rate:        {success_rate:.1f}%")
        print(f"Total Duration:      {total_duration:.1f}s")
        print(f"Requests/Second:     {self.stats.get('api_requests', 0) / max(1, total_duration):.2f}")
        print("=" * 60)
        
        if display_result:
            total_cost = display_result.get('totalCost', 0)
            print()
            if total_cost < 1_000_000_000:
                print("🎉 GOAL ACHIEVED: Under €1 BILLION!")
            print(f"✓ Solver completed successfully!")
            print(f"  Final Cost: €{total_cost:,.2f}")


def main():
    """Main entry point"""
    import argparse
    
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    
    default_api_key = os.getenv("API_KEY", "43b9ab90-b593-404c-a8d8-aaa074e181e1")
    default_base_url = os.getenv("BASE_URL", "http://127.0.0.1:8080/api/v1")
    
    parser = argparse.ArgumentParser(description="Enhanced solver with distance-awareness and demand forecasting")
    parser.add_argument("--api-key", type=str, default=default_api_key,
                       help="API key for authentication")
    parser.add_argument("--base-url", type=str, default=default_base_url,
                       help="Base URL of the evaluation platform")
    parser.add_argument("--log-level", type=str, default="INFO",
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="Logging level")
    parser.add_argument("--resources-dir", type=str, default="resources",
                       help="Directory containing CSV data files")
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(log_level=args.log_level)
    
    logger.info("=" * 60)
    logger.info("Rotables Challenge - ENHANCED Solver")
    logger.info("=" * 60)
    logger.info(f"API Base URL: {args.base_url}")
    logger.info(f"API Key: {args.api_key[:8]}...")
    logger.info(f"Features: Distance-aware, demand forecasting, smart repositioning")
    
    # Load data
    data_loader = DataLoader(args.resources_dir)
    
    # Create API client
    api_client = ApiClient(base_url=args.base_url, api_key=args.api_key)
    
    # Create and run solver
    solver = EnhancedSolver(api_client, data_loader)
    solver.solve()


if __name__ == "__main__":
    main()

