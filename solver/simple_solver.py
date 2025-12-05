"""
Simple Solver for HackITAll 2025 - Rotables Challenge
Implements a naive algorithm: load exactly the number of kits equal to passengers
"""

import requests
import uuid
import time
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
def setup_logging(log_to_file: bool = True, log_level: str = "INFO"):
    """Setup logging configuration"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Create logger
    logger = logging.getLogger("solver")
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # Clear existing handlers
    logger.handlers.clear()
    
    # Console handler with formatting
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # File handler with detailed formatting
    if log_to_file:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"solver_{timestamp}.log"
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
        logger.info(f"Logging to file: {log_file}")
    
    return logger

# Initialize logger (will be configured in main)
logger = logging.getLogger("solver")


@dataclass
class PerClassAmount:
    """Represents kit amounts per passenger class"""
    first: int = 0
    business: int = 0
    premiumEconomy: int = 0
    economy: int = 0


@dataclass
class FlightEvent:
    """Represents a flight event from the API"""
    eventType: str
    flightNumber: str
    flightId: str
    originAirport: str
    destinationAirport: str
    departure: Dict[str, int]
    arrival: Dict[str, int]
    passengers: Dict[str, int]
    aircraftType: str


class ApiClient:
    """Client for interacting with the evaluation platform API"""
    
    def __init__(self, base_url: str = "http://127.0.0.1:8080/api/v1", api_key: str = None):
        self.base_url = base_url
        self.api_key = api_key or "43b9ab90-b593-404c-a8d8-aaa074e181e1"  # Testing-1 default
        self.session_id: Optional[str] = None
        self.headers = {
            "API-KEY": self.api_key,
            "Content-Type": "application/json"
        }
    
    def start_session(self) -> str:
        """Start a new evaluation session"""
        url = f"{self.base_url}/session/start"
        logger.info(f"Starting session at {url}")
        logger.debug(f"API Key: {self.api_key[:8]}...")
        
        try:
            response = requests.post(url, headers=self.headers)
            response.raise_for_status()
            self.session_id = response.text.strip().strip('"')
            logger.info(f"Session started successfully: {self.session_id}")
            return self.session_id
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to start session: {e}")
            raise
    
    def play_round(self, day: int, hour: int, flight_loads: List[Dict], 
                   kit_purchasing_orders: Dict[str, int]) -> Dict:
        """Play a round (submit decisions for one hour)"""
        url = f"{self.base_url}/play/round"
        headers = {
            **self.headers,
            "SESSION-ID": self.session_id
        }
        
        payload = {
            "day": day,
            "hour": hour,
            "flightLoads": flight_loads,
            "kitPurchasingOrders": kit_purchasing_orders
        }
        
        logger.debug(f"Submitting round - Day {day}, Hour {hour}")
        logger.debug(f"Flight loads: {len(flight_loads)} flights")
        logger.debug(f"Purchasing orders: {kit_purchasing_orders}")
        
        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
            logger.debug(f"Round response received - Total cost: €{result.get('totalCost', 0):,.2f}")
            return result
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to play round: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            raise
    
    def end_session(self) -> Optional[Dict]:
        """End the current session. Returns None if session already ended (404)"""
        url = f"{self.base_url}/session/end"
        logger.info("Ending session...")
        try:
            response = requests.post(url, headers=self.headers)
            response.raise_for_status()
            result = response.json()
            logger.info(f"Session ended successfully - Final cost: €{result.get('totalCost', 0):,.2f}")
            return result
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                # Session already ended or not found - this is okay
                logger.warning("Session already ended or not found (404) - this is normal if simulation completed")
                return None
            else:
                logger.error(f"Failed to end session: {e}")
                raise


class NaiveSolver:
    """
    Naive solver that:
    - Loads exactly the number of kits equal to passengers for each flight
    - Purchases kits when HUB1 stock might be low (simple threshold)
    """
    
    def __init__(self, api_client: ApiClient):
        self.api_client = api_client
        self.current_day = 0
        self.current_hour = 0
        self.total_hours = 720  # 30 days * 24 hours
        self.last_response: Optional[Dict] = None  # Store last response for final display
        
    def solve(self):
        """Main solving loop - runs through all 720 hours"""
        logger.info("=" * 60)
        logger.info("Starting Naive Solver")
        logger.info("=" * 60)
        logger.info(f"Total hours to process: {self.total_hours} (30 days)")
        
        # Start session
        self.api_client.start_session()
        
        try:
            # Process each hour
            previous_response = None
            start_time = time.time()
            
            for hour in range(self.total_hours):
                day = hour // 24
                hour_of_day = hour % 24
                
                self.current_day = day
                self.current_hour = hour_of_day
                
                # Progress logging every 24 hours (daily summary)
                if hour_of_day == 0:
                    elapsed = time.time() - start_time
                    progress = (hour / self.total_hours) * 100
                    logger.info(f"[Day {day}, Hour {hour_of_day}] Processing... (Progress: {progress:.1f}%, Elapsed: {elapsed:.1f}s)")
                else:
                    logger.debug(f"[Day {day}, Hour {hour_of_day}] Processing...")
                
                # Get flight updates from previous round (first round will be empty)
                if previous_response is None:
                    # First round - we need to make initial decisions
                    # For the first round, we'll submit empty loads and see what flights are scheduled
                    logger.debug("First round - no previous response, submitting empty loads")
                    flight_loads = []
                    kit_purchasing_orders = self._calculate_purchases(day, hour_of_day, [])
                else:
                    # Use flight updates from previous response
                    flight_updates = previous_response.get("flightUpdates", [])
                    logger.debug(f"Processing {len(flight_updates)} flight updates from previous round")
                    flight_loads = self._calculate_flight_loads(flight_updates)
                    kit_purchasing_orders = self._calculate_purchases(day, hour_of_day, flight_updates)
                
                # Submit round
                try:
                    previous_response = self.api_client.play_round(
                        day=day,
                        hour=hour_of_day,
                        flight_loads=flight_loads,
                        kit_purchasing_orders=kit_purchasing_orders
                    )
                    
                    # Display results
                    self._display_round_results(previous_response)
                    self.last_response = previous_response  # Store for final display
                    
                    # Check if we should continue
                    if previous_response.get("day") >= 29 and previous_response.get("hour") >= 23:
                        logger.info("Reached end of simulation (Day 29, Hour 23)")
                        break
                        
                except requests.exceptions.HTTPError as e:
                    logger.error(f"Error in round Day {day}, Hour {hour_of_day}: {e}")
                    if e.response is not None:
                        logger.error(f"Response status: {e.response.status_code}")
                        logger.error(f"Response body: {e.response.text}")
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
            
            # Use final_result if available, otherwise use last_response
            display_result = final_result if final_result is not None else self.last_response
            
            logger.info("=" * 60)
            if display_result:
                logger.info(f"Final Total Cost: €{display_result.get('totalCost', 0):,.2f}")
                logger.info(f"Final Day: {display_result.get('day', 0)}")
                logger.info(f"Final Hour: {display_result.get('hour', 0)}")
                penalties = display_result.get('penalties', [])
                if penalties:
                    logger.info(f"Final Penalties: {len(penalties)}")
                    total_penalty = sum(p.get('penalty', 0) for p in penalties)
                    logger.info(f"Total Penalty Cost: €{total_penalty:,.2f}")
            else:
                logger.warning("Could not retrieve final results")
            logger.info("=" * 60)
            
            # Print summary to console as well
            print("\n" + "=" * 60)
            if display_result:
                print(f"Final Total Cost: €{display_result.get('totalCost', 0):,.2f}")
                print(f"Final Day: {display_result.get('day', 0)}")
                print(f"Final Hour: {display_result.get('hour', 0)}")
                if display_result.get('penalties'):
                    print(f"Final Penalties: {len(display_result.get('penalties', []))}")
            print("=" * 60)
    
    def _calculate_flight_loads(self, flight_updates: List[Dict]) -> List[Dict]:
        """
        Calculate flight loads based on flight updates.
        Strategy: Load exactly the number of kits equal to passengers.
        """
        flight_loads = []
        checked_in_count = 0
        total_kits = {"first": 0, "business": 0, "premiumEconomy": 0, "economy": 0}
        
        for flight in flight_updates:
            # Only load kits for flights that are CHECKED_IN (1h before departure)
            # This is when we know the actual passenger count
            if flight.get("eventType") == "CHECKED_IN":
                checked_in_count += 1
                passengers = flight.get("passengers", {})
                
                # Load exactly the number of kits equal to passengers
                loaded_kits = {
                    "first": passengers.get("first", 0),
                    "business": passengers.get("business", 0),
                    "premiumEconomy": passengers.get("premiumEconomy", 0),
                    "economy": passengers.get("economy", 0)
                }
                
                # Only add if we're loading at least one kit
                if any(loaded_kits.values()):
                    flight_loads.append({
                        "flightId": flight.get("flightId"),
                        "loadedKits": loaded_kits
                    })
                    total_kits["first"] += loaded_kits["first"]
                    total_kits["business"] += loaded_kits["business"]
                    total_kits["premiumEconomy"] += loaded_kits["premiumEconomy"]
                    total_kits["economy"] += loaded_kits["economy"]
                    
                    logger.debug(f"Loading kits for flight {flight.get('flightNumber')}: "
                               f"F={loaded_kits['first']}, B={loaded_kits['business']}, "
                               f"PE={loaded_kits['premiumEconomy']}, E={loaded_kits['economy']}")
        
        if checked_in_count > 0:
            logger.info(f"Calculated loads for {len(flight_loads)}/{checked_in_count} CHECKED_IN flights - "
                       f"Total kits: F={total_kits['first']}, B={total_kits['business']}, "
                       f"PE={total_kits['premiumEconomy']}, E={total_kits['economy']}")
        
        return flight_loads
    
    def _calculate_purchases(self, day: int, hour: int, flight_updates: List[Dict]) -> Dict[str, int]:
        """
        Calculate kit purchases.
        Simple strategy: Buy a small amount each hour to maintain stock.
        """
        # For now, buy a small fixed amount each hour
        # This is very naive - in a real solution, we'd track inventory
        purchases = {
            "first": 0,
            "business": 0,
            "premiumEconomy": 0,
            "economy": 0
        }
        
        # Buy some kits every 12 hours to maintain stock
        if hour % 12 == 0:
            purchases = {
                "first": 10,
                "business": 50,
                "premiumEconomy": 100,
                "economy": 500
            }
            logger.info(f"Purchasing kits: F={purchases['first']}, B={purchases['business']}, "
                       f"PE={purchases['premiumEconomy']}, E={purchases['economy']}")
        
        return purchases
    
    def _display_round_results(self, response: Dict):
        """Display results from a round"""
        flight_updates = response.get("flightUpdates", [])
        penalties = response.get("penalties", [])
        total_cost = response.get("totalCost", 0)
        
        # Count flight event types
        event_counts = {}
        for flight in flight_updates:
            event_type = flight.get("eventType", "UNKNOWN")
            event_counts[event_type] = event_counts.get(event_type, 0) + 1
        
        logger.info(f"Round results - Updates: {len(flight_updates)} flights "
                   f"({', '.join(f'{k}={v}' for k, v in event_counts.items())}), "
                   f"Penalties: {len(penalties)}, Total cost: €{total_cost:,.2f}")
        
        if penalties:
            total_penalty = sum(p.get('penalty', 0) for p in penalties)
            logger.warning(f"⚠ {len(penalties)} penalties incurred (Total: €{total_penalty:,.2f})")
            for penalty in penalties[:5]:  # Log first 5 penalties
                logger.warning(f"  - {penalty.get('code')}: €{penalty.get('penalty', 0):,.2f} "
                             f"({penalty.get('reason', 'N/A')})")
            
            # Also print to console for visibility
            print(f"  ⚠ {len(penalties)} penalties (€{total_penalty:,.2f})")
        else:
            print(f"  ✓ No penalties")


def main():
    """Main entry point"""
    import argparse
    
    # Get defaults from environment variables or use fallback defaults
    default_api_key = os.getenv("API_KEY", "43b9ab90-b593-404c-a8d8-aaa074e181e1")
    default_base_url = os.getenv("BASE_URL", "http://127.0.0.1:8080/api/v1")
    
    parser = argparse.ArgumentParser(description="Simple solver for Rotables Challenge")
    parser.add_argument("--api-key", type=str, 
                       default=default_api_key,
                       help="API key for authentication (or set API_KEY in .env)")
    parser.add_argument("--base-url", type=str,
                       default=default_base_url,
                       help="Base URL of the evaluation platform (or set BASE_URL in .env)")
    parser.add_argument("--log-level", type=str,
                       default="INFO",
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="Logging level (default: INFO)")
    parser.add_argument("--no-log-file", action="store_true",
                       help="Disable logging to file (only log to console)")
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(log_to_file=not args.no_log_file, log_level=args.log_level)
    logger.info("=" * 60)
    logger.info("Rotables Challenge Solver")
    logger.info("=" * 60)
    logger.info(f"API Base URL: {args.base_url}")
    logger.info(f"API Key: {args.api_key[:8]}...")
    logger.info(f"Log Level: {args.log_level}")
    logger.info(f"Log to File: {not args.no_log_file}")
    
    # Create API client
    api_client = ApiClient(base_url=args.base_url, api_key=args.api_key)
    
    # Create and run solver
    solver = NaiveSolver(api_client)
    solver.solve()


if __name__ == "__main__":
    main()

