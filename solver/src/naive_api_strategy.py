"""
API-based Naive Strategy Implementation
Integrates with backend API instead of local simulation
"""
import logging
from typing import Dict, List, Tuple
from uuid import UUID
from src.models import KitType
from src.data_warehouse import DataWarehouse
from src.api_client import APIClient
from src.inventory_tracker import AirportInventoryTracker

logger = logging.getLogger(__name__)


class NaiveAPIStrategy:
    """
    Naive baseline strategy that works with the backend API
    
    Strategy:
    - Load exact passenger counts on each CHECKED_IN flight
    - Purchase kits reactively when HUB stock drops below safety levels
    - Simple, no optimization - establishes baseline cost
    """
    
    def __init__(self, data_warehouse: DataWarehouse):
        """
        Initialize naive strategy with full network state tracking
        
        Args:
            data_warehouse: Data warehouse with flights, airports, etc.
        """
        self.dw = data_warehouse
        self.hub = self.dw.get_hub_airport()
        
        # Initialize inventory tracker for capacity-aware loading
        self.inventory_tracker = AirportInventoryTracker(self.dw.airports_by_id)
        
        # Simple stock tracking - sync from API responses
        # Initialize with HUB's starting inventory from CSV
        self.hub_stock = {
            KitType.FIRST: self.hub.initial_fc_stock,
            KitType.BUSINESS: self.hub.initial_bc_stock,
            KitType.PREMIUM_ECONOMY: self.hub.initial_pe_stock,
            KitType.ECONOMY: self.hub.initial_ec_stock
        }
        
        # Track pending purchase arrivals
        self.pending_arrivals = {kt: [] for kt in KitType}  # [(arrival_hour_absolute, quantity)]
        
        # Track in-flight kits returning to HUB
        # When we load an outbound flight, we track when those kits will return
        self.returning_kits = {kt: [] for kt in KitType}  # [(return_hour_absolute, quantity)]
        
        # Track kits at outstations being processed
        self.processing_kits = {kt: [] for kt in KitType}  # [(completion_hour_absolute, quantity)]
        
        # Track inventory at each airport (for capacity checks)
        # Format: {airport_id: {KitType: quantity}}
        self.airport_inventory = {}
        for airport_id in self.dw.airports_by_id.keys():
            self.airport_inventory[airport_id] = {kt: 0 for kt in KitType}
        
        # Initialize HUB inventory
        self.airport_inventory[self.hub.id] = {
            KitType.FIRST: self.hub.initial_fc_stock,
            KitType.BUSINESS: self.hub.initial_bc_stock,
            KitType.PREMIUM_ECONOMY: self.hub.initial_pe_stock,
            KitType.ECONOMY: self.hub.initial_ec_stock
        }
        
        # Safety stock levels at HUB (trigger purchases below these levels)
        # TEMPORARILY DISABLED TO TEST RETURN FLIGHT TRACKING
        self.safety_stock = {
            KitType.FIRST: 0,
            KitType.BUSINESS: 0,
            KitType.PREMIUM_ECONOMY: 0,
            KitType.ECONOMY: 0
        }
        
        # Reorder quantities
        self.reorder_quantity = {
            KitType.FIRST: 300,
            KitType.BUSINESS: 800,
            KitType.PREMIUM_ECONOMY: 500,
            KitType.ECONOMY: 5000
        }
        
        # Lead times for purchases (hours)
        self.lead_times = {
            KitType.FIRST: 45,
            KitType.BUSINESS: 28,
            KitType.PREMIUM_ECONOMY: 12,
            KitType.ECONOMY: 4
        }
        
        logger.info("Naive API Strategy initialized")
        logger.info(f"Initial HUB stock: {self.hub_stock}")
        logger.info(f"Safety stock: {self.safety_stock}")
        logger.info(f"Reorder quantities: {self.reorder_quantity}")
    
    def get_decisions_for_round(self, day: int, hour: int, 
                                flight_updates: List[Dict]) -> Tuple[List[Dict], Dict[str, int]]:
        """
        Generate decisions for a single round based on flight updates from API
        
        Strategy: Load exact passenger counts, purchase conservatively when stock low
        
        Args:
            day: Current day (0-29)
            hour: Current hour (0-23)
            flight_updates: List of flight events from API response
        
        Returns:
            Tuple of (flight_loads, kit_purchases)
        """
        # Update inventory tracker for this hour
        current_hour_absolute = day * 24 + hour
        self.inventory_tracker.update_for_hour(current_hour_absolute)
        
        # Process any kits arriving this hour
        self._process_arriving_kits(day, hour)
        
        # Log first few rounds for debugging
        if day == 0 and hour < 5:
            logger.info(f"D{day}H{hour}: Received {len(flight_updates)} flight updates")
            if flight_updates and hour == 0:
                logger.info(f"Sample flight update: {flight_updates[0]}")
        
        # Step 1: Generate flight loads for CHECKED_IN flights (know demand FIRST)
        flight_loads = self._generate_flight_loads(flight_updates, day, hour)
        
        # Step 2: Calculate required kits for these loads
        required_kits = self._calculate_required_kits(flight_loads)
        
        # Step 3: Purchase kits to meet demand + safety stock
        kit_purchases = self._purchase_kits_for_demand(required_kits, day, hour)
        
        # Step 4: Update our local stock tracking (simulate what backend will do)
        self._update_local_stock(flight_loads, kit_purchases)
        return flight_loads, kit_purchases

    def _process_arriving_kits(self, day: int, hour: int):
        """Process purchase arrivals and returning kits for this hour"""
        current_time = day * 24 + hour
        
        # Process purchase arrivals
        for kit_type in KitType:
            arrivals = [qty for (arr_time, qty) in self.pending_arrivals[kit_type]
                       if arr_time == current_time]
            
            if arrivals:
                total = int(sum(arrivals))
                self.hub_stock[kit_type] += total
                logger.info(f"D{day}H{hour}: {total} {kit_type.name} kits PURCHASED ARRIVED "
                           f"(HUB stock now: {self.hub_stock[kit_type]})")
            
            # Remove processed arrivals
            self.pending_arrivals[kit_type] = [
                (arr_time, qty) for (arr_time, qty) in self.pending_arrivals[kit_type]
                if arr_time != current_time
            ]
            
            # DISABLED: Don't track returning kits - causes capacity violations
            # Backend handles returns automatically, we can't control them
            # # Process returning kits (kits coming back from outstations)
            # returns = [qty for (ret_time, qty) in self.returning_kits[kit_type]
            #           if ret_time == current_time]
            # 
            # if returns:
            #     total_returning = int(sum(returns))
            #     self.hub_stock[kit_type] += total_returning
            #     logger.info(f"D{day}H{hour}: {total_returning} {kit_type.name} kits RETURNED from outstations "
            #                f"(HUB stock now: {self.hub_stock[kit_type]})")
            # 
            # # Remove processed returns
            # self.returning_kits[kit_type] = [
            #     (ret_time, qty) for (ret_time, qty) in self.returning_kits[kit_type]
            #     if ret_time != current_time
            # ]

    def _generate_flight_loads(self, flight_updates: List[Dict], day: int, hour: int) -> List[Dict]:
        """
        Generate loading decisions for CHECKED_IN flights.
        
        For outbound flights from HUB, track when kits will return
        
        Args:
            flight_updates: Flight events from API
            day: Current day
            hour: Current hour
        
        Returns:
            List of flight load decisions
        """
        flight_loads = []
        
        logger.debug(f"Processing {len(flight_updates)} flight updates")
        
        for flight_event in flight_updates:
            event_type = flight_event.get('eventType')
            
            # Only load flights at CHECK_IN event (1 hour before departure)
            if event_type != 'CHECKED_IN':
                logger.debug(f"Skipping flight event type: {event_type}")
                continue
            
            flight_id = flight_event.get('flightId')
            passengers = flight_event.get('passengers', {})
            
            # Extract IDs - originAirport and destinationAirport are strings (airport IDs)
            origin_airport_id = flight_event.get('originAirport')
            dest_airport_id = flight_event.get('destinationAirport')
            aircraft_type_id = flight_event.get('aircraftType')
            actual_distance = flight_event.get('distance', 0)
            
            logger.debug(f"Loading CHECKED_IN flight {flight_id}: {passengers}")
            
            # Phase 2: Capacity-aware loading
            # Use inventory tracker to check destination capacity
            # API returns airport codes - look up by code first, then use the airport object
            dest_airport = self.dw.airports.get(dest_airport_id)
            if not dest_airport:
                logger.warning(f"Destination airport code {dest_airport_id} not found")
                continue
            
            origin_airport = self.dw.airports.get(origin_airport_id)
            if not origin_airport:
                logger.warning(f"Origin airport code {origin_airport_id} not found")
                continue
            
            # API returns aircraft type code, not ID
            aircraft_type = self.dw.aircraft_types.get(aircraft_type_id)
            if not aircraft_type:
                logger.warning(f"Aircraft type code {aircraft_type_id} not found")
                continue
            
            loaded_kits = self._apply_capacity_aware_loading(
                flight_event, dest_airport, origin_airport, aircraft_type, passengers
            )
            
            flight_loads.append({
                "flightId": str(flight_id),
                "loadedKits": loaded_kits
            })
            
            # Update inventory tracker with this loading decision
            current_hour_absolute = day * 24 + hour
            self.inventory_tracker.process_flight_loading(
                flight_event, loaded_kits, current_hour_absolute,
                origin_airport, dest_airport, aircraft_type, actual_distance
            )
            
            logger.debug(f"Added load for flight {flight_id}: {loaded_kits}")
        
        logger.info(f"Generated {len(flight_loads)} flight loads from {len(flight_updates)} updates")
        
        return flight_loads
    
    def _apply_capacity_aware_loading(self, flight_event: Dict, dest_airport: 'Airport',
                                      origin_airport: 'Airport', aircraft_type: 'AircraftType',
                                      passengers: Dict[str, int]) -> Dict[str, int]:
        """
        Apply capacity-aware loading logic.
        
        Checks estimated destination inventory and reduces loading if needed
        to avoid capacity violations.
        
        Args:
            flight_event: Flight event from API
            dest_airport: Destination airport
            origin_airport: Origin airport
            aircraft_type: Aircraft type
            passengers: Passenger counts from API
        
        Returns:
            Dict with actual loaded kits (may be less than desired)
        """
        loaded_kits = {}
        dest_id = dest_airport.id
        
        # Adaptive safety margin based on destination
        # HUB needs more conservative margin due to return flights
        # Outstations can use higher margin as they don't accumulate
        if dest_id == self.hub.id:
            safety_margin = 0.70  # Very conservative for HUB (70%) - optimal from testing
        else:
            safety_margin = 0.90  # Normal for outstations (90%)
        
        kit_mapping = {
            'first': KitType.FIRST,
            'business': KitType.BUSINESS,
            'premiumEconomy': KitType.PREMIUM_ECONOMY,
            'economy': KitType.ECONOMY
        }
        
        reductions = []
        
        for api_field, kit_type in kit_mapping.items():
            desired = passengers.get(api_field, 0)
            
            if desired == 0:
                loaded_kits[api_field] = 0
                continue
            
            # Check available space at destination
            available_space = self.inventory_tracker.get_available_space(
                dest_id, kit_type, safety_margin
            )
            
            # Load min of desired and available space
            actual = min(desired, available_space)
            loaded_kits[api_field] = actual
            
            if actual < desired:
                current = self.inventory_tracker.get_inventory(dest_id, kit_type)
                capacity = self.inventory_tracker.get_capacity(dest_id, kit_type)
                reductions.append(
                    f"{kit_type.name}: {desired}->{actual} "
                    f"(dest {dest_airport.code} at {current}/{capacity})"
                )
        
        if reductions:
            flight_number = flight_event.get('flightNumber', flight_event.get('flightId'))
            logger.info(
                f"Flight {flight_number} capacity-reduced loading: " + ", ".join(reductions)
            )
        
        return loaded_kits
    
    def _OLD_apply_capacity_constraints(self, flight_id: str, dest_airport: 'Airport', 
                                     desired_kits: Dict[str, int]) -> Dict[str, int]:
        """Apply capacity constraints to prevent exceeding destination airport capacity"""
        loaded_kits = desired_kits.copy()
        dest_id = dest_airport.id
        current_inventory = self.airport_inventory.get(dest_id, {})
        
        # Check each kit type
        kit_mapping = {
            'first': (KitType.FIRST, dest_airport.capacity_fc),
            'business': (KitType.BUSINESS, dest_airport.capacity_bc),
            'premiumEconomy': (KitType.PREMIUM_ECONOMY, dest_airport.capacity_pe),
            'economy': (KitType.ECONOMY, dest_airport.capacity_ec)
        }
        
        for api_field, (kit_type, capacity) in kit_mapping.items():
            desired = desired_kits.get(api_field, 0)
            if desired == 0:
                continue
            
            current = current_inventory.get(kit_type, 0)
            available_space = max(0, capacity - current)
            
            if desired > available_space:
                # Reduce load to fit capacity
                loaded_kits[api_field] = available_space
                if available_space == 0:
                    logger.warning(
                        f"Flight {flight_id}: Cannot load {desired} {api_field} kits - "
                        f"destination {dest_airport.code} at capacity ({current}/{capacity})"
                    )
                else:
                    logger.info(
                        f"Flight {flight_id}: Reduced {api_field} load from {desired} to {available_space} "
                        f"due to capacity constraint at {dest_airport.code} ({current}/{capacity})"
                    )
        
        return loaded_kits
    
    def _update_inventory_after_loading(self, flight: 'Flight', loaded_kits: Dict[str, int]):
        """Update airport inventories after loading a flight"""
        origin_id = flight.origin_airport_id
        dest_id = flight.destination_airport_id
        
        kit_mapping = {
            'first': KitType.FIRST,
            'business': KitType.BUSINESS,
            'premiumEconomy': KitType.PREMIUM_ECONOMY,
            'economy': KitType.ECONOMY
        }
        
        # Remove from origin
        for api_field, kit_type in kit_mapping.items():
            quantity = loaded_kits.get(api_field, 0)
            if quantity > 0:
                if origin_id in self.airport_inventory:
                    self.airport_inventory[origin_id][kit_type] -= quantity
        
        # Add to destination (will arrive after processing)
        arrival_hour = flight.actual_arrival_hour_absolute
        dest_airport = self.dw.airports_by_id.get(dest_id)
        
        if dest_airport:
            for api_field, kit_type in kit_mapping.items():
                quantity = loaded_kits.get(api_field, 0)
                if quantity > 0:
                    processing_time = dest_airport.get_processing_time(kit_type)
                    ready_hour = arrival_hour + processing_time
                    # Kits immediately add to destination inventory upon arrival
                    # (backend handles processing time internally)
                    if dest_id in self.airport_inventory:
                        self.airport_inventory[dest_id][kit_type] += quantity
    
    def _track_returning_kits(self, outbound_flight, loaded_kits: Dict[str, int]):
        """Track when kits loaded on outbound flight will return to HUB"""
        try:
            dest_airport = self.dw.airports_by_id[outbound_flight.destination_airport_id]
            arrival_at_outstation = outbound_flight.actual_arrival_hour_absolute
            
            # Find next return flight
            return_flights = self._find_return_flights(
                dest_airport.id,
                self.hub.id,
                after_hour=arrival_at_outstation
            )
            
            if not return_flights:
                return
            
            return_flight = return_flights[0]
            return_departure = return_flight.scheduled_depart_day * 24 + return_flight.scheduled_depart_hour
            
            for kit_field, quantity in loaded_kits.items():
                if quantity == 0:
                    continue
                
                kit_type = self._api_field_to_kit_type(kit_field)
                processing_time = dest_airport.get_processing_time(kit_type)
                processing_complete = arrival_at_outstation + processing_time
                
                if processing_complete <= return_departure:
                    return_arrival = return_flight.actual_arrival_hour_absolute
                    self.returning_kits[kit_type].append((return_arrival, quantity))
                else:
                    # Find later return flight
                    later_returns = self._find_return_flights(dest_airport.id, self.hub.id, after_hour=processing_complete)
                    if later_returns:
                        return_arrival = later_returns[0].actual_arrival_hour_absolute
                        self.returning_kits[kit_type].append((return_arrival, quantity))
                        
        except Exception as e:
            logger.debug(f"Error tracking returning kits: {e}")
    
    # Note: Return flight tracking now handled by inventory_tracker based on actual API events
    
    def _api_field_to_kit_type(self, field: str) -> KitType:
        """Convert API field name to KitType"""
        return {'first': KitType.FIRST, 'business': KitType.BUSINESS,
                'premiumEconomy': KitType.PREMIUM_ECONOMY, 'economy': KitType.ECONOMY}[field]
    
    def _calculate_required_kits(self, flight_loads: List[Dict]) -> Dict[KitType, int]:
        """
        Calculate total kits required for given flight loads
        
        Args:
            flight_loads: List of flight load decisions
        
        Returns:
            Dict mapping KitType to required quantity
        """
        required = {kt: 0 for kt in KitType}
        
        for load in flight_loads:
            kits = load['loadedKits']
            required[KitType.FIRST] += kits['first']
            required[KitType.BUSINESS] += kits['business']
            required[KitType.PREMIUM_ECONOMY] += kits['premiumEconomy']
            required[KitType.ECONOMY] += kits['economy']
        
        return required
    
    def _purchase_kits_for_demand(self, required_kits: Dict[KitType, int], 
                                  day: int, hour: int) -> Dict[str, int]:
        """
        Purchase kits to meet demand and maintain safety stock
        
        Uses simple HUB stock tracking synced from backend
        
        Args:
            required_kits: Kits needed this round
            day: Current day
            hour: Current hour
        
        Returns:
            Purchase orders dict: {"first": qty, "business": qty, ...}
        """
        purchases = {
            "first": 0,
            "business": 0,
            "premiumEconomy": 0,
            "economy": 0
        }
        
        for kit_type in KitType:
            # Get current HUB stock
            current_stock = self.hub_stock[kit_type]
            needed_this_round = required_kits[kit_type]
            
            # Calculate pending arrivals (purchases in transit)
            current_hour_absolute = day * 24 + hour
            pending_purchases = sum(
                qty for (arr_time, qty) in self.pending_arrivals[kit_type]
                if arr_time > current_hour_absolute
            )
            
            # DISABLED: Don't consider returning kits (causes capacity issues)
            # Backend handles returns automatically
            # pending_returns = sum(
            #     qty for (ret_time, qty) in self.returning_kits[kit_type]
            #     if ret_time > current_hour_absolute
            # )
            pending_returns = 0
            
            # Effective stock = current + pending purchases (no returns considered)
            effective_stock = current_stock + pending_purchases + pending_returns
            stock_after_loads = effective_stock - needed_this_round
            
            # AGGRESSIVE UPFRONT PURCHASING: Buy early to build buffer
            # Only avoid purchasing if we have plenty of stock
            
            # If we're about to go negative (considering all pending arrivals), buy to recover PLUS buffer
            if stock_after_loads < 0:
                purchase_qty = int(abs(stock_after_loads) + self.safety_stock[kit_type])
                
                api_field = self._kit_type_to_api_field(kit_type)
                purchases[api_field] = purchase_qty
                
                # Schedule arrival
                arrival_time = day * 24 + hour + self.lead_times[kit_type]
                self.pending_arrivals[kit_type].append((arrival_time, purchase_qty))
                
                # Update inventory tracker
                self.inventory_tracker.process_purchase(
                    kit_type, purchase_qty, arrival_time, self.hub.id
                )
                
                logger.warning(f"CRITICAL: {kit_type.name} would go NEGATIVE! Purchasing {purchase_qty} kits "
                             f"(current: {int(current_stock)}, pending_purchases: {int(pending_purchases)}, "
                             f"pending_returns: {int(pending_returns)}, needed: {needed_this_round}, "
                             f"after: {int(stock_after_loads)})")
                continue
            
            # If stock is below safety level, buy up to safety stock
            if stock_after_loads < self.safety_stock[kit_type]:
                deficit = self.safety_stock[kit_type] - stock_after_loads
                purchase_qty = int(deficit)
                
                api_field = self._kit_type_to_api_field(kit_type)
                purchases[api_field] = purchase_qty
                
                # Schedule arrival
                arrival_time = day * 24 + hour + self.lead_times[kit_type]
                self.pending_arrivals[kit_type].append((arrival_time, purchase_qty))
                
                # Update inventory tracker
                self.inventory_tracker.process_purchase(
                    kit_type, purchase_qty, arrival_time, self.hub.id
                )
                
                logger.info(f"PURCHASING {purchase_qty} {kit_type.name} kits "
                           f"(current: {int(current_stock)}, pending_purchases: {int(pending_purchases)}, "
                           f"pending_returns: {int(pending_returns)}, after: {int(stock_after_loads)}, "
                           f"target: {self.safety_stock[kit_type]})")
        
        return purchases
    
    def _update_local_stock(self, flight_loads: List[Dict], kit_purchases: Dict[str, int]):
        """
        Update local HUB stock to mirror backend's updates
        
        Deducts kits loaded on flights. Purchases arrive later (tracked separately).
        
        Args:
            flight_loads: Flights we're loading
            kit_purchases: Purchases we're making (don't add immediately)
        """
        for load in flight_loads:
            kits = load['loadedKits']
            self.hub_stock[KitType.FIRST] -= kits['first']
            self.hub_stock[KitType.BUSINESS] -= kits['business']
            self.hub_stock[KitType.PREMIUM_ECONOMY] -= kits['premiumEconomy']
            self.hub_stock[KitType.ECONOMY] -= kits['economy']
    
    def _kit_type_to_api_field(self, kit_type: KitType) -> str:
        """Convert KitType to API field name"""
        mapping = {
            KitType.FIRST: 'first',
            KitType.BUSINESS: 'business',
            KitType.PREMIUM_ECONOMY: 'premiumEconomy',
            KitType.ECONOMY: 'economy'
        }
        return mapping[kit_type]
    
    def update_from_api_response(self, response: Dict):
        """
        Update internal state based on API response
        
        Args:
            response: Response from /play/round endpoint
        """
        # Log penalties if any
        penalties = response.get('penalties', [])
        if penalties:
            for penalty in penalties:
                penalty_code = penalty.get('code', 'UNKNOWN')
                penalty_amount = penalty.get('penalty', 0)
                penalty_reason = penalty.get('reason', '')
                logger.warning(f"Penalty: {penalty_code} - EUR{penalty_amount:,.2f} - {penalty_reason}")
        
        # Stock is already updated locally in _update_local_stock()
        # This could sync from backend if needed, but for now we trust our tracking

    
    def _kit_type_to_api_field(self, kit_type: KitType) -> str:
        """Convert KitType enum to API field name"""
        mapping = {
            KitType.FIRST: "first",
            KitType.BUSINESS: "business",
            KitType.PREMIUM_ECONOMY: "premiumEconomy",
            KitType.ECONOMY: "economy"
        }
        return mapping[kit_type]


def run_naive_strategy_with_api(api_url: str, api_key: str, data_warehouse: DataWarehouse) -> Dict:
    """
    Run complete naive strategy session with backend API
    
    Args:
        api_url: Backend API base URL
        api_key: API authentication key
        data_warehouse: Data warehouse instance
    
    Returns:
        Final session results
    """
    logger.info("=" * 80)
    logger.info("STARTING NAIVE BASELINE STRATEGY WITH BACKEND API")
    logger.info("=" * 80)
    logger.info(f"API URL: {api_url}")
    logger.info(f"Total duration: 720 hours (30 days)")
    logger.info("")
    
    # Initialize API client and strategy
    api_client = APIClient(api_url, api_key)
    strategy = NaiveAPIStrategy(data_warehouse)
    
    try:
        # Start session
        session_id = api_client.start_session()
        logger.info(f"Session started: {session_id}\n")
        
        # Initialize flight_updates for first round
        flight_updates = []
        
        # Run 720 rounds (30 days × 24 hours)
        for day in range(30):
            day_start_cost = None
            
            for hour in range(24):
                # Generate decisions based on current flight updates
                flight_loads, kit_purchases = strategy.get_decisions_for_round(
                    day, hour, flight_updates
                )
                
                # Play round
                response = api_client.play_round(day, hour, flight_loads, kit_purchases)
                
                # Update strategy state
                strategy.update_from_api_response(response)
                
                # Track day start cost
                if hour == 0:
                    day_start_cost = response.get('totalCost', 0)
                
                # Get flight updates for next round
                flight_updates = response.get('flightUpdates', [])
            
            # Log daily progress
            day_end_cost = response.get('totalCost', 0)
            day_cost = day_end_cost - (day_start_cost or 0)
            logger.info(f"Day {day:2d} complete - Total: EUR{day_end_cost:,.2f} "
                       f"(Day cost: EUR{day_cost:,.2f})")
        
        # End session (may already be ended if we completed 720 hours)
        logger.info("\n" + "=" * 80)
        logger.info("Ending session...")
        
        try:
            final_result = api_client.end_session()
            final_cost = final_result.get('totalCost', 0)
        except Exception as e:
            # Session may have auto-ended after 720 hours
            if '404' in str(e):
                logger.info("Session already ended (completed 720 hours)")
                # Use last response as final result
                final_cost = response.get('totalCost', 0)
                final_result = response
            else:
                raise
        
        # Display final results
        logger.info("=" * 80)
        logger.info("SESSION COMPLETE")
        logger.info("=" * 80)
        logger.info(f"Final Total Cost: EUR{final_cost:,.2f}")
        logger.info("=" * 80)
        
        return final_result
        
    except Exception as e:
        logger.error(f"Session failed: {e}")
        # Try to end session on error (ignore if already ended)
        try:
            api_client.end_session()
        except:
            logger.debug("Could not end session (may already be ended)")
        raise
    
    finally:
        api_client.close()


if __name__ == "__main__":
    import sys
    import os
    if len(sys.argv) < 3:
        print("Usage: python naive_api_strategy.py <api_key> <base_url>")
        sys.exit(1)
    
    api_key = sys.argv[1]
    base_url = sys.argv[2]
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s'
    )
    
    # Initialize data warehouse
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(script_dir, '..', '..', 'eval-platform', 'src', 'main', 'resources', 'liquibase', 'data')
    data_dir = os.path.abspath(data_dir)
    
    dw = DataWarehouse(data_dir)
    dw.load_all_data()  # Load airports, aircraft types, and flight schedules
    
    # Run strategy
    result = run_naive_strategy_with_api(base_url, api_key, dw)
    final_cost = result.get('totalCost', 0)
    print(f"\n✅ Session complete! Final cost: EUR {final_cost:,.2f}")
