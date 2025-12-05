"""
Simple Solver for HackITAll 2025 - Rotables Challenge
Implements a naive algorithm: load exactly the number of kits equal to passengers
"""

import requests
import uuid
import time
import os
from typing import Dict, List, Optional
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


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
        response = requests.post(url, headers=self.headers)
        response.raise_for_status()
        self.session_id = response.text.strip().strip('"')
        print(f"✓ Session started: {self.session_id}")
        return self.session_id
    
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
        
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()
    
    def end_session(self) -> Optional[Dict]:
        """End the current session. Returns None if session already ended (404)"""
        url = f"{self.base_url}/session/end"
        try:
            response = requests.post(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                # Session already ended or not found - this is okay
                print("  ℹ Session already ended or not found (404)")
                return None
            else:
                # Re-raise other HTTP errors
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
        print("=" * 60)
        print("Starting Naive Solver")
        print("=" * 60)
        
        # Start session
        self.api_client.start_session()
        
        try:
            # Process each hour
            previous_response = None
            for hour in range(self.total_hours):
                day = hour // 24
                hour_of_day = hour % 24
                
                self.current_day = day
                self.current_hour = hour_of_day
                
                print(f"\n[Day {day}, Hour {hour_of_day}] Processing...")
                
                # Get flight updates from previous round (first round will be empty)
                if previous_response is None:
                    # First round - we need to make initial decisions
                    # For the first round, we'll submit empty loads and see what flights are scheduled
                    flight_loads = []
                    kit_purchasing_orders = self._calculate_purchases(day, hour_of_day, [])
                else:
                    # Use flight updates from previous response
                    flight_loads = self._calculate_flight_loads(previous_response.get("flightUpdates", []))
                    kit_purchasing_orders = self._calculate_purchases(day, hour_of_day, previous_response.get("flightUpdates", []))
                
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
                        print("\n✓ Reached end of simulation (Day 29, Hour 23)")
                        break
                        
                except requests.exceptions.HTTPError as e:
                    print(f"✗ Error in round: {e}")
                    if e.response is not None:
                        print(f"  Response: {e.response.text}")
                    break
                    
        except KeyboardInterrupt:
            print("\n\n⚠ Interrupted by user")
        except Exception as e:
            print(f"\n✗ Error: {e}")
        finally:
            # End session
            print("\n" + "=" * 60)
            print("Ending session...")
            final_result = self.api_client.end_session()
            
            # Use final_result if available, otherwise use last_response
            display_result = final_result if final_result is not None else self.last_response
            
            print("=" * 60)
            if display_result:
                print(f"Final Total Cost: €{display_result.get('totalCost', 0):,.2f}")
                print(f"Final Day: {display_result.get('day', 0)}")
                print(f"Final Hour: {display_result.get('hour', 0)}")
                if display_result.get('penalties'):
                    print(f"Final Penalties: {len(display_result.get('penalties', []))}")
            else:
                print("⚠ Could not retrieve final results")
            print("=" * 60)
    
    def _calculate_flight_loads(self, flight_updates: List[Dict]) -> List[Dict]:
        """
        Calculate flight loads based on flight updates.
        Strategy: Load exactly the number of kits equal to passengers.
        """
        flight_loads = []
        
        for flight in flight_updates:
            # Only load kits for flights that are CHECKED_IN (1h before departure)
            # This is when we know the actual passenger count
            if flight.get("eventType") == "CHECKED_IN":
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
        
        return purchases
    
    def _display_round_results(self, response: Dict):
        """Display results from a round"""
        flight_updates = response.get("flightUpdates", [])
        penalties = response.get("penalties", [])
        total_cost = response.get("totalCost", 0)
        
        print(f"  Flight updates: {len(flight_updates)}")
        print(f"  Penalties: {len(penalties)}")
        print(f"  Total cost: €{total_cost:,.2f}")
        
        if penalties:
            print(f"  ⚠ Penalties incurred:")
            for penalty in penalties[:3]:  # Show first 3
                print(f"    - {penalty.get('code')}: €{penalty.get('penalty', 0):,.2f}")


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
    
    args = parser.parse_args()
    
    # Create API client
    api_client = ApiClient(base_url=args.base_url, api_key=args.api_key)
    
    # Create and run solver
    solver = NaiveSolver(api_client)
    solver.solve()


if __name__ == "__main__":
    main()

