"""
Stage 2 COLLEAGUE-STYLE Solver
================================

Based on analysis of colleague's solution that achieves < €1B:

Key strategies:
1. EXACT PASSENGER LOADING - no repositioning at all
2. ZERO SAFETY STOCK - only buy when stock would go negative  
3. CAPACITY-AWARE with different margins (HUB: 70%, Outstations: 90%)
4. Track ALL airport inventories (not just HUB)
5. Reactive purchasing only
"""

import csv
import os
import time
import logging
import requests
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict
from dataclasses import dataclass

from simple_solver import ApiClient, setup_logging, logger

KIT_TYPES = {
    'first': {'cost': 200.0, 'weight': 5.0, 'lead_time': 48},
    'business': {'cost': 150.0, 'weight': 3.0, 'lead_time': 36},
    'premiumEconomy': {'cost': 100.0, 'weight': 2.5, 'lead_time': 24},
    'economy': {'cost': 50.0, 'weight': 1.5, 'lead_time': 12}
}

CLASS_NAMES = ['first', 'business', 'premiumEconomy', 'economy']
TIME_HORIZON = 720


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


class KitMovement:
    """Scheduled kit movement (arrival after processing)"""
    def __init__(self, hour: int, airport: str, class_name: str, quantity: int):
        self.hour = hour
        self.airport = airport
        self.class_name = class_name
        self.quantity = quantity


class ColleagueStyleSolver:
    """
    Replicates colleague's winning strategy:
    - Exact passenger loading (no repositioning)
    - Zero safety stock (reactive purchasing only)
    - Capacity-aware with different margins
    - Track all airport inventories
    """
    
    def __init__(self, api_client: ApiClient, data_loader: DataLoader):
        self.api_client = api_client
        self.airports = data_loader.load_airports()
        
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
        
        # COLLEAGUE STYLE: Zero safety stock!
        self.safety_stock = {'first': 0, 'business': 0, 'premiumEconomy': 0, 'economy': 0}
        
        # Statistics
        self.stats = {
            'rounds_played': 0, 'flights_loaded': 0,
            'kits_loaded': defaultdict(int), 'kits_purchased': defaultdict(int),
            'unfulfilled': defaultdict(int), 'capacity_reduced': defaultdict(int),
            'start_time': None, 'penalties': defaultdict(int), 'penalty_cost': defaultdict(float)
        }
        
        total = {c: sum(self.inventory[a].get(c, 0) for a in self.inventory) for c in CLASS_NAMES}
        logger.info(f"Initial inventory: F={total['first']}, B={total['business']}, "
                   f"PE={total['premiumEconomy']}, E={total['economy']}")
        logger.info(f"HUB identified: {self.hub_code}")
        logger.info("COLLEAGUE STYLE: Zero safety stock, exact passenger loading, capacity-aware")
    
    def _get_inventory(self, airport: str, class_name: str) -> int:
        """Get current inventory at airport"""
        return max(0, self.inventory.get(airport, {}).get(class_name, 0))
    
    def _get_pending_arrivals(self, airport: str, class_name: str) -> int:
        """Get kits scheduled to arrive at airport (in transit + processing)"""
        return sum(m.quantity for m in self.scheduled_movements 
                  if m.airport == airport and m.class_name == class_name)
    
    def _get_available_space(self, airport: str, class_name: str, is_hub: bool) -> int:
        """
        COLLEAGUE STYLE: Different capacity margins for HUB vs Outstations
        - HUB: 70% (conservative, handles returns)
        - Outstations: 90% (more lenient)
        """
        capacity = self.airports[airport].get_capacity(class_name)
        current = self._get_inventory(airport, class_name)
        pending = self._get_pending_arrivals(airport, class_name)
        
        effective = current + pending
        
        # COLLEAGUE'S KEY INSIGHT: Different margins
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
    
    def _calculate_flight_loads(self, flights: list, current_hour: int) -> list:
        """
        COLLEAGUE STYLE: Load EXACT passenger count, capacity-aware
        """
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
            loaded_kits = {}
            
            for class_name in CLASS_NAMES:
                pax = passengers.get(class_name, 0)
                available_at_origin = self._get_inventory(origin, class_name)
                available_space_at_dest = self._get_available_space(destination, class_name, is_dest_hub)
                
                # COLLEAGUE STYLE: Load exactly passengers, but respect capacity
                desired = pax
                actual = min(desired, available_at_origin, available_space_at_dest)
                
                loaded_kits[class_name] = actual
                
                # Track reductions
                if actual < pax:
                    if available_at_origin < pax:
                        self.stats['unfulfilled'][class_name] += (pax - actual)
                    else:
                        self.stats['capacity_reduced'][class_name] += (pax - actual)
                
                # Update origin inventory
                self.inventory[origin][class_name] = max(0,
                    self.inventory[origin].get(class_name, 0) - actual)
            
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
        COLLEAGUE STYLE: Reactive purchasing only - buy when stock would go negative
        """
        purchases = {'first': 0, 'business': 0, 'premiumEconomy': 0, 'economy': 0}
        
        # Calculate kits needed this round
        needed = {c: 0 for c in CLASS_NAMES}
        for load in flight_loads:
            for c in CLASS_NAMES:
                needed[c] += load['loadedKits'].get(c, 0)
        
        hub = self.hub_code
        
        for class_name in CLASS_NAMES:
            current = self._get_inventory(hub, class_name)
            
            # Get pending purchase arrivals
            pending = 0
            lead_time = KIT_TYPES[class_name]['lead_time']
            for t in range(current_hour, current_hour + lead_time + 24):
                pending += self.pending_purchases.get(t, {}).get(class_name, 0)
            
            effective = current + pending
            stock_after = effective - needed[class_name]
            
            # COLLEAGUE STYLE: Only buy if going negative
            if stock_after < 0:
                buy = abs(stock_after) + self.safety_stock[class_name]
                purchases[class_name] = int(buy)
                
                # Track purchase
                arrival = current_hour + lead_time
                self.pending_purchases[arrival][class_name] += int(buy)
                self.stats['kits_purchased'][class_name] += int(buy)
                
                logger.debug(f"PURCHASE: {int(buy)} {class_name} (current={current}, pending={pending}, "
                            f"needed={needed[class_name]}, after={stock_after})")
        
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
                logger.warning(f"  - {penalty.get('penaltyType', penalty.get('code', 'UNKNOWN'))}: €{penalty.get('penalty', 0):,.2f}")
    
    def solve(self):
        """Main solving loop"""
        logger.info("=" * 60)
        logger.info("COLLEAGUE-STYLE SOLVER (Exact Loading + Zero Safety Stock)")
        logger.info("=" * 60)
        logger.info(f"Strategy: Exact passenger loading, no repositioning")
        logger.info(f"Capacity margins: HUB=70%, Outstations=90%")
        logger.info(f"Safety stock: ZERO (reactive purchasing only)")
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
                
                # If end_response has useful data, use it for summary
                if isinstance(end_response, dict):
                    if 'totalCost' in end_response:
                        self.last_response = end_response
                    logger.info(f"Final Total Cost from end_session: €{end_response.get('totalCost', 'N/A'):,}")
                    
                    # Log all penalties from end response
                    end_penalties = end_response.get('penalties', [])
                    if end_penalties:
                        logger.info(f"End-game penalties ({len(end_penalties)}):")
                        for p in end_penalties[:10]:  # Log first 10
                            logger.info(f"  - {p.get('penaltyType', 'UNKNOWN')}: €{p.get('penalty', 0):,.2f}")
                        if len(end_penalties) > 10:
                            logger.info(f"  ... and {len(end_penalties) - 10} more penalties")
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
        print("SOLVER EXECUTION SUMMARY")
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
            print()
            
            # Unfulfilled and capacity-reduced stats
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
                # Group penalties by type
                penalty_by_type = defaultdict(lambda: {'count': 0, 'cost': 0.0})
                for penalty in penalties:
                    ptype = penalty.get('penaltyType', penalty.get('code', 'UNKNOWN'))
                    pcost = penalty.get('penalty', 0)
                    penalty_by_type[ptype]['count'] += 1
                    penalty_by_type[ptype]['cost'] += pcost
                
                # Sort by cost (descending)
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
    
    parser = argparse.ArgumentParser(description="Colleague-style solver (exact loading, zero safety stock)")
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
    logger.info("Rotables Challenge - Colleague-Style Solver")
    logger.info("=" * 60)
    logger.info(f"API Base URL: {args.base_url}")
    logger.info(f"API Key: {args.api_key[:8]}...")
    logger.info(f"Strategy: Exact passenger loading, zero safety stock")
    logger.info(f"Capacity margins: HUB=70%, Outstations=90%")
    
    # Load data
    data_loader = DataLoader(args.resources_dir)
    
    # Create API client
    api_client = ApiClient(base_url=args.base_url, api_key=args.api_key)
    
    # Create and run solver
    solver = ColleagueStyleSolver(api_client, data_loader)
    solver.solve()


if __name__ == "__main__":
    main()

