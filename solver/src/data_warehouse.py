"""
Complete Data Ingestion & Parsing Module
Loads all CSV files and builds comprehensive data structures.
"""
import csv
import os
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import logging

from .models import (
    Airport, AircraftType, Flight, KitType, 
    RouteMetrics, FlightSchedulePattern
)

logger = logging.getLogger(__name__)


class DataWarehouse:
    """
    Central repository for all static game data.
    Loads and pre-processes all CSV files from eval-platform.
    """
    
    def __init__(self, data_dir: str = None):
        """
        Initialize data warehouse.
        
        Args:
            data_dir: Path to liquibase/data directory. 
                     If None, auto-detects from project structure.
        """
        if data_dir is None:
            # Auto-detect path
            current_dir = Path(__file__).parent.parent
            data_dir = current_dir.parent / "eval-platform" / "src" / "main" / "resources" / "liquibase" / "data"
        
        self.data_dir = Path(data_dir)
        
        # Core data structures
        self.airports: Dict[str, Airport] = {}  # code -> Airport
        self.airports_by_id: Dict[str, Airport] = {}  # id -> Airport
        self.aircraft_types: Dict[str, AircraftType] = {}  # type_code -> AircraftType
        self.aircraft_types_by_id: Dict[str, AircraftType] = {}  # id -> AircraftType
        # NOTE: flights come from API at runtime, not pre-loaded
        self.flight_schedule_patterns: List[FlightSchedulePattern] = []
        
        # Indexed data structures for fast lookup (based on flight_plan patterns)
        self.flights_by_route_pattern: Dict[Tuple[str, str], FlightSchedulePattern] = {}  # (origin, dest) -> pattern
        
        # Pre-calculated metrics
        self.route_metrics: Dict[Tuple[str, str], RouteMetrics] = {}  # (origin, dest) -> RouteMetrics
        self.turnaround_times: Dict[str, Dict[Tuple[str, str], List[int]]] = {}  # airport -> route -> [turnaround_hours]
        
        # Network structure
        self.hub_code = "HUB1"
        self.outstation_codes: List[str] = []
        
        logger.info(f"DataWarehouse initialized with data directory: {self.data_dir}")
    
    def load_all_data(self):
        """Load and pre-process all CSV files in the correct order"""
        logger.info("Starting complete data load...")
        
        # Load in dependency order
        self.load_aircraft_types()
        self.load_airports()
        self.load_flight_schedule_patterns()
        
        # Build indices and calculate metrics
        self.identify_network_structure()
        self.index_flight_patterns()
        
        logger.info("Data load complete!")
        self.print_summary()
    
    def load_aircraft_types(self):
        """Load aircraft_types.csv"""
        filepath = self.data_dir / "aircraft_types.csv"
        logger.info(f"Loading aircraft types from {filepath}")
        
        with open(filepath, 'r', encoding='utf-8') as f:
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
                self.aircraft_types[aircraft.type_code] = aircraft
                self.aircraft_types_by_id[aircraft.id] = aircraft
        
        logger.info(f"Loaded {len(self.aircraft_types)} aircraft types")
    
    def load_airports(self):
        """Load airports_with_stocks.csv"""
        filepath = self.data_dir / "airports_with_stocks.csv"
        logger.info(f"Loading airports from {filepath}")
        
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                airport = Airport(
                    id=row['id'],
                    code=row['code'],
                    name=row['name'],
                    first_processing_time=int(row['first_processing_time']),
                    business_processing_time=int(row['business_processing_time']),
                    premium_economy_processing_time=int(row['premium_economy_processing_time']),
                    economy_processing_time=int(row['economy_processing_time']),
                    first_processing_cost=float(row['first_processing_cost']),
                    business_processing_cost=float(row['business_processing_cost']),
                    premium_economy_processing_cost=float(row['premium_economy_processing_cost']),
                    economy_processing_cost=float(row['economy_processing_cost']),
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
                self.airports[airport.code] = airport
                self.airports_by_id[airport.id] = airport
        
        logger.info(f"Loaded {len(self.airports)} airports")
    
    def load_flight_schedule_patterns(self):
        """Load flight_plan.csv - weekly recurring patterns"""
        filepath = self.data_dir / "flight_plan.csv"
        logger.info(f"Loading flight schedule patterns from {filepath}")
        
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                pattern = FlightSchedulePattern(
                    route_key=(row['depart_code'], row['arrival_code']),
                    scheduled_hour=int(row['scheduled_hour']),
                    scheduled_arrival_hour=int(row['scheduled_arrival_hour']),
                    arrival_next_day=bool(int(row['arrival_next_day'])),
                    distance_km=int(row['distance_km']),
                    monday=bool(int(row['Mon'])),
                    tuesday=bool(int(row['Tue'])),
                    wednesday=bool(int(row['Wed'])),
                    thursday=bool(int(row['Thu'])),
                    friday=bool(int(row['Fri'])),
                    saturday=bool(int(row['Sat'])),
                    sunday=bool(int(row['Sun']))
                )
                self.flight_schedule_patterns.append(pattern)
        
        logger.info(f"Loaded {len(self.flight_schedule_patterns)} flight schedule patterns")
    
    def index_flight_patterns(self):
        """Build lookup index for flight schedule patterns"""
        logger.info("Indexing flight schedule patterns...")
        
        for pattern in self.flight_schedule_patterns:
            route_key = pattern.route_key
            self.flights_by_route_pattern[route_key] = pattern
        
        logger.info(f"Indexed {len(self.flights_by_route_pattern)} route patterns")
    

    
    def identify_network_structure(self):
        """Identify hub and outstations"""
        logger.info("Identifying network structure...")
        
        self.outstation_codes = [code for code in self.airports.keys() if code != self.hub_code]
        
        logger.info(f"Network: 1 HUB ({self.hub_code}) + {len(self.outstation_codes)} outstations")
    

    

    

    
    def get_flight_pattern(self, origin: str, destination: str) -> Optional[FlightSchedulePattern]:
        """Get flight schedule pattern for a route"""
        return self.flights_by_route_pattern.get((origin, destination))
    
    def get_hub_airport(self) -> Airport:
        """Get the hub airport object"""
        return self.airports[self.hub_code]
    
    def print_summary(self):
        """Print summary statistics of loaded data"""
        print("\n" + "="*80)
        print("DATA WAREHOUSE SUMMARY")
        print("="*80)
        
        print(f"\n[Airports] {len(self.airports)}")
        print(f"   - HUB: {self.hub_code}")
        print(f"   - Outstations: {len(self.outstation_codes)}")
        
        print(f"\n[Aircraft Types] {len(self.aircraft_types)}")
        for aircraft in self.aircraft_types.values():
            print(f"   - {aircraft.type_code}: "
                  f"Seats={aircraft.first_class_seats}F/"
                  f"{aircraft.business_seats}B/"
                  f"{aircraft.premium_economy_seats}PE/"
                  f"{aircraft.economy_seats}E, "
                  f"Cost/kg/km=EUR{aircraft.cost_per_kg_per_km}")
        
        print(f"\n[Flight Schedule Patterns] {len(self.flight_schedule_patterns)}")
        print(f"   - Unique routes: {len(self.flights_by_route_pattern)}")
        
        # Count patterns by day
        day_counts = {'Mon': 0, 'Tue': 0, 'Wed': 0, 'Thu': 0, 'Fri': 0, 'Sat': 0, 'Sun': 0}
        for pattern in self.flight_schedule_patterns:
            if pattern.monday: day_counts['Mon'] += 1
            if pattern.tuesday: day_counts['Tue'] += 1
            if pattern.wednesday: day_counts['Wed'] += 1
            if pattern.thursday: day_counts['Thu'] += 1
            if pattern.friday: day_counts['Fri'] += 1
            if pattern.saturday: day_counts['Sat'] += 1
            if pattern.sunday: day_counts['Sun'] += 1
        print(f"   - Flights per day: {day_counts}")
        
        # Hub stock summary
        hub = self.get_hub_airport()
        print(f"\n[HUB Initial Stock]")
        print(f"   - First Class: {hub.initial_fc_stock} / {hub.capacity_fc}")
        print(f"   - Business: {hub.initial_bc_stock} / {hub.capacity_bc}")
        print(f"   - Premium Economy: {hub.initial_pe_stock} / {hub.capacity_pe}")
        print(f"   - Economy: {hub.initial_ec_stock} / {hub.capacity_ec}")
        
        print("\n" + "="*80 + "\n")


if __name__ == "__main__":
    # Test data loading
    logging.basicConfig(level=logging.INFO, 
                       format='%(asctime)s - %(levelname)s - %(message)s')
    
    warehouse = DataWarehouse()
    warehouse.load_all_data()
