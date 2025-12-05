"""
Greedy Solver for HackITAll 2025 - Rotables Challenge
Implements a greedy algorithm that uses CSV data to make informed decisions
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


@dataclass
class AircraftType:
    """Represents an aircraft type with capacities and costs"""
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
    initial_fc_stock: int
    initial_bc_stock: int
    initial_pe_stock: int
    initial_ec_stock: int
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
    
    def get_initial_stock(self, class_name: str) -> int:
        """Get initial stock for a class"""
        mapping = {
            'first': self.initial_fc_stock,
            'business': self.initial_bc_stock,
            'premiumEconomy': self.initial_pe_stock,
            'economy': self.initial_ec_stock
        }
        return mapping.get(class_name, 0)


class DataLoader:
    """Loads and parses CSV data files"""
    
    def __init__(self, resources_dir: str = "resources"):
        self.resources_dir = Path(resources_dir)
        if not self.resources_dir.exists():
            # Try relative to solver directory
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
                    first_class_seats=int(row['first_class_seats']),
                    business_seats=int(row['business_seats']),
                    premium_economy_seats=int(row['premium_economy_seats']),
                    economy_seats=int(row['economy_seats']),
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
                    initial_fc_stock=int(row['initial_fc_stock']),
                    initial_bc_stock=int(row['initial_bc_stock']),
                    initial_pe_stock=int(row['initial_pe_stock']),
                    initial_ec_stock=int(row['initial_ec_stock']),
                    capacity_fc=int(row['capacity_fc']),
                    capacity_bc=int(row['capacity_bc']),
                    capacity_pe=int(row['capacity_pe']),
                    capacity_ec=int(row['capacity_ec'])
                )
                airports[airport.code] = airport
        
        logger.info(f"Loaded {len(airports)} airports")
        return airports


class InventoryTracker:
    """Tracks kit inventory at HUB1 and pending purchases"""
    
    def __init__(self, hub_airport: Airport):
        self.hub = hub_airport
        # Current inventory at HUB1
        self.inventory = {
            'first': hub_airport.initial_fc_stock,
            'business': hub_airport.initial_bc_stock,
            'premiumEconomy': hub_airport.initial_pe_stock,
            'economy': hub_airport.initial_ec_stock
        }
        # Pending purchases: (arrival_day, arrival_hour) -> {class: quantity}
        self.pending_purchases = defaultdict(lambda: defaultdict(int))
        # Safety buffer percentage (5% extra)
        self.safety_buffer = 0.05
    
    def get_available(self, class_name: str) -> int:
        """Get available inventory for a class"""
        return max(0, int(self.inventory[class_name]))
    
    def consume(self, class_name: str, quantity: int):
        """Consume kits from inventory"""
        self.inventory[class_name] -= quantity
        logger.debug(f"Consumed {quantity} {class_name} kits. Remaining: {self.inventory[class_name]}")
    
    def add_purchase(self, class_name: str, quantity: int, arrival_day: int, arrival_hour: int):
        """Record a pending purchase"""
        key = (arrival_day, arrival_hour)
        self.pending_purchases[key][class_name] += quantity
        logger.debug(f"Scheduled purchase: {quantity} {class_name} kits arriving at Day {arrival_day}, Hour {arrival_hour}")
    
    def process_arrivals(self, current_day: int, current_hour: int):
        """Process purchases that have arrived"""
        keys_to_remove = []
        for (arrival_day, arrival_hour), purchases in self.pending_purchases.items():
            if arrival_day < current_day or (arrival_day == current_day and arrival_hour <= current_hour):
                for class_name, quantity in purchases.items():
                    self.inventory[class_name] += quantity
                    logger.info(f"Purchase arrived: {quantity} {class_name} kits added to inventory (now: {self.inventory[class_name]})")
                keys_to_remove.append((arrival_day, arrival_hour))
        
        for key in keys_to_remove:
            del self.pending_purchases[key]
    
    def get_status(self) -> Dict[str, int]:
        """Get current inventory status"""
        return self.inventory.copy()


class GreedySolver:
    """
    Simplified greedy solver - essentially the same as naive solver
    Loads exactly passenger demand and purchases kits periodically
    The "greedy" part is just using CSV data for aircraft capacities
    """
    
    def __init__(self, api_client: ApiClient, data_loader: DataLoader, safety_buffer: float = 0.05):
        self.api_client = api_client
        self.data_loader = data_loader
        self.safety_buffer = safety_buffer
        
        # Load data (for aircraft capacities)
        self.aircraft_types = data_loader.load_aircraft_types()
        self.airports = data_loader.load_airports()
        
        # Track statistics (optional)
        self.stats = {
            'total_purchases': defaultdict(int),
            'total_loads': defaultdict(int)
        }
        
        logger.info("Greedy solver initialized (simplified - same as naive)")
    
    def solve(self):
        """Main solving loop"""
        logger.info("=" * 60)
        logger.info("Starting Greedy Solver")
        logger.info("=" * 60)
        
        # Start session
        self.api_client.start_session()
        
        try:
            previous_response = None
            start_time = time.time()
            
            for hour in range(720):  # 30 days * 24 hours
                day = hour // 24
                hour_of_day = hour % 24
                
                # No inventory tracking - just like naive solver
                
                # Progress logging
                if hour_of_day == 0:
                    elapsed = time.time() - start_time
                    progress = (hour / 720) * 100
                    logger.info(f"[Day {day}, Hour {hour_of_day}] Progress: {progress:.1f}%, "
                               f"Elapsed: {elapsed:.1f}s")
                
                # Calculate decisions
                if previous_response is None:
                    flight_loads = []
                    kit_purchasing_orders = self._calculate_initial_purchases(day, hour_of_day)
                else:
                    flight_updates = previous_response.get("flightUpdates", [])
                    flight_loads = self._calculate_flight_loads(flight_updates, day, hour_of_day)
                    kit_purchasing_orders = self._calculate_purchases(flight_updates, day, hour_of_day)
                
                # Validate purchases before submitting
                MAX_PURCHASES = {
                    'first': 42000,
                    'business': 42000,
                    'premiumEconomy': 1000,  # Special limit!
                    'economy': 42000
                }
                
                for class_name in CLASS_NAMES:
                    if kit_purchasing_orders[class_name] > MAX_PURCHASES[class_name]:
                        logger.warning(f"Capping {class_name} purchase from {kit_purchasing_orders[class_name]} "
                                     f"to {MAX_PURCHASES[class_name]}")
                        kit_purchasing_orders[class_name] = MAX_PURCHASES[class_name]
                
                # Submit round
                try:
                    previous_response = self.api_client.play_round(
                        day=day,
                        hour=hour_of_day,
                        flight_loads=flight_loads,
                        kit_purchasing_orders=kit_purchasing_orders
                    )
                    
                    # Display results
                    self._display_round_results(previous_response, day, hour_of_day)
                    self.last_response = previous_response
                    
                    # Check if we should continue
                    if previous_response.get("day") >= 29 and previous_response.get("hour") >= 23:
                        logger.info("Reached end of simulation (Day 29, Hour 23)")
                        break
                        
                except requests.exceptions.HTTPError as e:
                    logger.error(f"Error in round Day {day}, Hour {hour_of_day}: {e}")
                    if e.response is not None:
                        logger.error(f"Response: {e.response.text}")
                    break
                    
        except KeyboardInterrupt:
            logger.warning("Interrupted by user")
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
        finally:
            # End session
            logger.info("=" * 60)
            logger.info("Ending session...")
            final_result = self.api_client.end_session()
            
            display_result = final_result if final_result is not None else self.last_response
            
            logger.info("=" * 60)
            if display_result:
                logger.info(f"Final Total Cost: €{display_result.get('totalCost', 0):,.2f}")
                logger.info(f"Final Day: {display_result.get('day', 0)}")
                logger.info(f"Final Hour: {display_result.get('hour', 0)}")
                penalties = display_result.get('penalties', [])
                if penalties:
                    total_penalty = sum(p.get('penalty', 0) for p in penalties)
                    logger.info(f"Final Penalties: {len(penalties)} (Total: €{total_penalty:,.2f})")
            
            # Print summary
            print("\n" + "=" * 60)
            if display_result:
                print(f"Final Total Cost: €{display_result.get('totalCost', 0):,.2f}")
                print(f"Final Day: {display_result.get('day', 0)}")
                print(f"Final Hour: {display_result.get('hour', 0)}")
            print("=" * 60)
    
    def _calculate_flight_loads(self, flight_updates: List[Dict], day: int, hour: int) -> List[Dict]:
        """
        Simplified greedy: Load exactly passenger demand (like naive solver)
        Don't try to track inventory - just load what's needed and let purchases handle stock
        """
        flight_loads = []
        
        for flight in flight_updates:
            if flight.get("eventType") != "CHECKED_IN":
                continue
            
            flight_id = flight.get("flightId")
            aircraft_type_code = flight.get("aircraftType")
            passengers = flight.get("passengers", {})
            origin = flight.get("originAirport")
            
            # Only load from HUB1
            if origin != "HUB1":
                continue
            
            # Get aircraft type
            aircraft = self.aircraft_types.get(aircraft_type_code)
            if not aircraft:
                logger.warning(f"Unknown aircraft type: {aircraft_type_code}")
                continue
            
            loaded_kits = {}
            total_kits_loaded = 0
            
            for class_name in CLASS_NAMES:
                demand = passengers.get(class_name, 0)
                if demand == 0:
                    loaded_kits[class_name] = 0
                    continue
                
                # Get aircraft capacity
                capacity = aircraft.get_capacity(class_name)
                
                # SIMPLIFIED: Just load exactly what passengers need (up to capacity)
                # Don't try to track inventory - the API will handle it
                # This is the same as naive solver but with better purchase logic
                kits_to_load = min(demand, capacity)
                
                loaded_kits[class_name] = kits_to_load
                total_kits_loaded += kits_to_load
                
                # Track for statistics (but don't use for decisions)
                if kits_to_load > 0:
                    self.stats['total_loads'][class_name] += kits_to_load
            
            # Only add if we're loading at least one kit
            if total_kits_loaded > 0:
                flight_loads.append({
                    "flightId": flight_id,
                    "loadedKits": loaded_kits
                })
                logger.debug(f"Flight {flight.get('flightNumber')}: Loaded "
                           f"F={loaded_kits['first']}, B={loaded_kits['business']}, "
                           f"PE={loaded_kits['premiumEconomy']}, E={loaded_kits['economy']}")
        
        return flight_loads
    
    def _calculate_purchases(self, flight_updates: List[Dict], day: int, hour: int) -> Dict[str, int]:
        """
        Simple purchase logic: Just buy a fixed amount every 12 hours (like naive solver)
        The naive solver worked better, so let's use the same approach
        """
        purchases = {cls: 0 for cls in CLASS_NAMES}
        
        # Buy a fixed amount every 12 hours (exactly like naive solver)
        if hour % 12 == 0:
            purchases = {
                'first': 10,
                'business': 50,
                'premiumEconomy': 100,
                'economy': 500
            }
            logger.info(f"Purchasing kits: F={purchases['first']}, B={purchases['business']}, "
                       f"PE={purchases['premiumEconomy']}, E={purchases['economy']}")
        
        return purchases
    
    def _calculate_initial_purchases(self, day: int, hour: int) -> Dict[str, int]:
        """Calculate initial purchases - same as naive solver"""
        purchases = {cls: 0 for cls in CLASS_NAMES}
        # No initial purchases - just like naive solver
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
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    default_api_key = os.getenv("API_KEY", "43b9ab90-b593-404c-a8d8-aaa074e181e1")
    default_base_url = os.getenv("BASE_URL", "http://127.0.0.1:8080/api/v1")
    
    parser = argparse.ArgumentParser(description="Greedy solver for Rotables Challenge")
    parser.add_argument("--api-key", type=str, default=default_api_key,
                       help="API key for authentication")
    parser.add_argument("--base-url", type=str, default=default_base_url,
                       help="Base URL of the evaluation platform")
    parser.add_argument("--log-level", type=str, default="INFO",
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="Logging level")
    parser.add_argument("--no-log-file", action="store_true",
                       help="Disable logging to file")
    parser.add_argument("--safety-buffer", type=float, default=0.05,
                       help="Safety buffer percentage (default: 0.05 = 5%%)")
    parser.add_argument("--resources-dir", type=str, default="resources",
                       help="Directory containing CSV data files")
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(log_to_file=not args.no_log_file, log_level=args.log_level)
    logger.info("=" * 60)
    logger.info("Rotables Challenge - Greedy Solver")
    logger.info("=" * 60)
    logger.info(f"API Base URL: {args.base_url}")
    logger.info(f"Safety Buffer: {args.safety_buffer * 100:.1f}%")
    logger.info(f"Resources Directory: {args.resources_dir}")
    
    # Load data
    data_loader = DataLoader(args.resources_dir)
    
    # Create API client
    api_client = ApiClient(base_url=args.base_url, api_key=args.api_key)
    
    # Create and run solver
    solver = GreedySolver(api_client, data_loader, safety_buffer=args.safety_buffer)
    solver.solve()


if __name__ == "__main__":
    main()

