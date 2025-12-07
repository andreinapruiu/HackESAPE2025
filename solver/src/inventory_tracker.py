"""
Airport Inventory Tracker - Shadow Backend State
Estimates kit inventory at all airports to enable capacity-aware loading decisions.
"""
from dataclasses import dataclass
from typing import Dict, List, Tuple
from collections import defaultdict
import logging

from .models import KitType, Airport

logger = logging.getLogger(__name__)


@dataclass
class KitMovement:
    """Represents a scheduled kit movement"""
    hour: int
    airport_id: str
    kit_type: KitType
    quantity: int
    movement_type: str  # 'arrival', 'processing_complete', 'purchase'


class AirportInventoryTracker:
    """
    Tracks estimated inventory at all airports.
    
    Mirrors backend behavior:
    - Removes kits when flights depart
    - Adds kits when flights arrive (after processing time)
    - Tracks purchases in transit
    - Checks capacity before loading decisions
    """
    
    def __init__(self, airports: Dict[str, Airport]):
        """
        Initialize tracker with airport data.
        
        Args:
            airports: Dictionary of airport_id -> Airport
        """
        self.airports = airports
        
        # Current inventory at each airport
        self.inventory: Dict[str, Dict[KitType, int]] = {}
        
        # Initialize with starting stocks
        for airport_id, airport in airports.items():
            self.inventory[airport_id] = {
                KitType.FIRST: airport.initial_fc_stock,
                KitType.BUSINESS: airport.initial_bc_stock,
                KitType.PREMIUM_ECONOMY: airport.initial_pe_stock,
                KitType.ECONOMY: airport.initial_ec_stock
            }
        
        # Scheduled movements (arrivals, processing completions, purchases)
        self.scheduled_movements: List[KitMovement] = []
        
        logger.info(f"Inventory tracker initialized for {len(airports)} airports")
    
    def get_inventory(self, airport_id: str, kit_type: KitType) -> int:
        """Get current estimated inventory at an airport"""
        return self.inventory.get(airport_id, {}).get(kit_type, 0)
    
    def get_capacity(self, airport_id: str, kit_type: KitType) -> int:
        """Get capacity limit at an airport"""
        airport = self.airports.get(airport_id)
        if not airport:
            return 0
        
        capacity_map = {
            KitType.FIRST: airport.capacity_fc,
            KitType.BUSINESS: airport.capacity_bc,
            KitType.PREMIUM_ECONOMY: airport.capacity_pe,
            KitType.ECONOMY: airport.capacity_ec
        }
        return capacity_map.get(kit_type, 0)
    
    def get_available_space(self, airport_id: str, kit_type: KitType, 
                           safety_margin: float = 0.9) -> int:
        """
        Calculate available space at an airport with safety margin.
        
        Args:
            airport_id: Airport to check
            kit_type: Type of kit
            safety_margin: Use this fraction of capacity (0.9 = 90%)
        
        Returns:
            Number of kits that can be safely loaded
        """
        current = self.get_inventory(airport_id, kit_type)
        capacity = self.get_capacity(airport_id, kit_type)
        
        # Count scheduled arrivals (kits in transit that will add to inventory)
        pending_arrivals = sum(
            m.quantity for m in self.scheduled_movements
            if m.airport_id == airport_id and m.kit_type == kit_type
        )
        
        # Effective current = actual current + kits in transit
        effective_current = current + pending_arrivals
        
        safe_capacity = int(capacity * safety_margin)
        available = max(0, safe_capacity - effective_current)
        
        return available
    
    def process_flight_loading(self, flight_event: Dict, loaded_kits: Dict[str, int], 
                               current_hour: int, origin_airport: 'Airport', 
                               dest_airport: 'Airport', aircraft_type: 'AircraftType',
                               actual_distance: int):
        """
        Update tracker when a flight is loaded.
        
        Removes kits from origin immediately.
        Schedules arrival at destination after flight time + processing time.
        
        Args:
            flight_event: Flight event from API
            loaded_kits: Dict with API field names {'first': qty, 'business': qty, ...}
            current_hour: Current absolute hour
            origin_airport: Origin airport object
            dest_airport: Destination airport object
            aircraft_type: Aircraft type object
            actual_distance: Actual flight distance
        """
        origin_id = origin_airport.id
        dest_id = dest_airport.id
        
        if not dest_airport:
            logger.warning(f"Destination airport {dest_id} not found")
            return
        
        # Map API fields to KitType
        kit_mapping = {
            'first': KitType.FIRST,
            'business': KitType.BUSINESS,
            'premiumEconomy': KitType.PREMIUM_ECONOMY,
            'economy': KitType.ECONOMY
        }
        
        # Remove from origin immediately
        for api_field, kit_type in kit_mapping.items():
            quantity = loaded_kits.get(api_field, 0)
            if quantity > 0:
                if origin_id in self.inventory:
                    self.inventory[origin_id][kit_type] -= quantity
                    logger.debug(
                        f"Removed {quantity} {kit_type.name} from {origin_id} "
                        f"(now: {self.inventory[origin_id][kit_type]})"
                    )
        
        # Calculate arrival time - get from API event
        # Check if arrival is a nested object
        arrival_info = flight_event.get('arrival', {})
        if isinstance(arrival_info, dict):
            actual_arrival_day = arrival_info.get('day')
            actual_arrival_hour = arrival_info.get('hour')
        else:
            # Fallback to top-level fields
            actual_arrival_day = flight_event.get('actualArrivalDay', flight_event.get('scheduledArrivalDay'))
            actual_arrival_hour = flight_event.get('actualArrivalHour', flight_event.get('scheduledArrivalHour'))
        
        if actual_arrival_day is None or actual_arrival_hour is None:
            logger.warning(f"Cannot determine arrival time for flight, using current hour + 1")
            arrival_hour = current_hour + 1
        else:
            arrival_hour = actual_arrival_day * 24 + actual_arrival_hour
        
        for api_field, kit_type in kit_mapping.items():
            quantity = loaded_kits.get(api_field, 0)
            if quantity > 0:
                processing_time = dest_airport.get_processing_time(kit_type)
                ready_hour = arrival_hour + processing_time
                
                # Schedule the kit movement
                self.scheduled_movements.append(
                    KitMovement(
                        hour=ready_hour,
                        airport_id=dest_id,
                        kit_type=kit_type,
                        quantity=quantity,
                        movement_type='arrival'
                    )
                )
                logger.debug(
                    f"Scheduled {quantity} {kit_type.name} arrival at {dest_id} "
                    f"at hour {ready_hour} (flight arrival: {arrival_hour}, "
                    f"processing: {processing_time}h)"
                )
    
    def process_purchase(self, kit_type: KitType, quantity: int, 
                        arrival_hour: int, hub_id: str):
        """
        Schedule a purchase arrival.
        
        Args:
            kit_type: Type of kit purchased
            quantity: Number of kits
            arrival_hour: When purchase will arrive
            hub_id: HUB airport ID
        """
        self.scheduled_movements.append(
            KitMovement(
                hour=arrival_hour,
                airport_id=hub_id,
                kit_type=kit_type,
                quantity=quantity,
                movement_type='purchase'
            )
        )
        logger.debug(
            f"Scheduled purchase of {quantity} {kit_type.name} arriving at hour {arrival_hour}"
        )
    
    def update_for_hour(self, current_hour: int):
        """
        Process all scheduled movements for the current hour.
        
        Args:
            current_hour: Current absolute hour
        """
        # Find movements due this hour
        due_movements = [m for m in self.scheduled_movements if m.hour == current_hour]
        
        if due_movements:
            logger.debug(f"Processing {len(due_movements)} movements for hour {current_hour}")
        
        # Apply movements to inventory
        for movement in due_movements:
            airport_id = movement.airport_id
            kit_type = movement.kit_type
            quantity = movement.quantity
            
            if airport_id in self.inventory:
                old_qty = self.inventory[airport_id][kit_type]
                self.inventory[airport_id][kit_type] += quantity
                new_qty = self.inventory[airport_id][kit_type]
                
                logger.debug(
                    f"{movement.movement_type.upper()}: {quantity} {kit_type.name} "
                    f"at {airport_id} ({old_qty} -> {new_qty})"
                )
        
        # Remove processed movements
        self.scheduled_movements = [
            m for m in self.scheduled_movements if m.hour > current_hour
        ]
    
    def get_inventory_summary(self, airport_id: str) -> Dict[str, Tuple[int, int]]:
        """
        Get inventory summary for an airport.
        
        Returns:
            Dict mapping kit type name to (current, capacity) tuple
        """
        summary = {}
        for kit_type in KitType:
            current = self.get_inventory(airport_id, kit_type)
            capacity = self.get_capacity(airport_id, kit_type)
            summary[kit_type.name] = (current, capacity)
        return summary
    
    def check_all_capacities(self) -> List[Tuple[str, KitType, int, int]]:
        """
        Check all airports for capacity violations.
        
        Returns:
            List of (airport_id, kit_type, current, capacity) for violations
        """
        violations = []
        for airport_id, inventory in self.inventory.items():
            for kit_type, quantity in inventory.items():
                capacity = self.get_capacity(airport_id, kit_type)
                if quantity > capacity:
                    violations.append((airport_id, kit_type, quantity, capacity))
        return violations
