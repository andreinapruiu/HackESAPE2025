"""
API Client for Rotables Challenge Backend
Handles communication with /session/start, /play/round, /session/end endpoints
"""
import requests
import logging
from typing import Dict, List, Optional, Tuple
from uuid import UUID
import time

logger = logging.getLogger(__name__)


class APIClient:
    """Client for interacting with the evaluation platform backend"""
    
    def __init__(self, base_url: str, api_key: str):
        """
        Initialize API client
        
        Args:
            base_url: Base URL of the backend API (e.g., "http://localhost:8080")
            api_key: UUID API key for authentication
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session_id: Optional[str] = None
        self.current_day = 0
        self.current_hour = 0
        
        # Configure session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            'API-KEY': str(api_key),
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
    
    def start_session(self) -> str:
        """
        Start a new evaluation session
        
        Returns:
            Session ID as string
        
        Raises:
            requests.HTTPError: If session creation fails
        """
        url = f"{self.base_url}/api/v1/session/start"
        
        logger.info(f"Starting new session at {url}")
        
        try:
            response = self.session.post(url, timeout=30)
            response.raise_for_status()
            
            self.session_id = response.text.strip().strip('"')
            self.current_day = 0
            self.current_hour = 0
            
            logger.info(f"Session started successfully: {self.session_id}")
            return self.session_id
            
        except requests.exceptions.HTTPError as e:
            # If 409 Conflict, try to end existing session and retry
            if e.response.status_code == 409:
                logger.warning("Session already exists (409 Conflict). Attempting to end existing session...")
                try:
                    # Try to end the existing session
                    end_url = f"{self.base_url}/api/v1/session/end"
                    end_response = self.session.post(end_url, timeout=30)
                    if end_response.status_code in (200, 404):  # 404 means no session exists
                        logger.info("Successfully ended existing session. Retrying start...")
                        # Retry starting the session
                        response = self.session.post(url, timeout=30)
                        response.raise_for_status()
                        
                        self.session_id = response.text.strip().strip('"')
                        self.current_day = 0
                        self.current_hour = 0
                        
                        logger.info(f"Session started successfully after retry: {self.session_id}")
                        return self.session_id
                except Exception as retry_error:
                    logger.error(f"Failed to end existing session and retry: {retry_error}")
            
            logger.error(f"Failed to start session: {e}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to start session: {e}")
            raise
    
    def play_round(self, day: int, hour: int, flight_loads: List[Dict], 
                   kit_purchases: Dict[str, int]) -> Dict:
        """
        Submit decisions for a single hour and receive response
        
        Args:
            day: Current day (0-29 for 30 days)
            hour: Current hour (0-23)
            flight_loads: List of flight load decisions
                [{"flightId": "uuid", "loadedKits": {"first": 10, "business": 20, ...}}, ...]
            kit_purchases: Purchase orders per kit class
                {"first": 100, "business": 200, "premiumEconomy": 150, "economy": 500}
        
        Returns:
            Response dictionary with:
                - day: int
                - hour: int
                - flightUpdates: List of flight events
                - penalties: List of penalties
                - totalCost: float
        
        Raises:
            requests.HTTPError: If round submission fails
        """
        if not self.session_id:
            raise ValueError("No active session. Call start_session() first.")
        
        url = f"{self.base_url}/api/v1/play/round"
        
        # Prepare request payload
        payload = {
            "day": day,
            "hour": hour,
            "flightLoads": flight_loads,
            "kitPurchasingOrders": kit_purchases
        }
        
        # Validate payload structure
        if not isinstance(flight_loads, list):
            logger.error(f"flightLoads must be a list, got {type(flight_loads)}")
            raise ValueError("Invalid flightLoads type")
        
        for i, load in enumerate(flight_loads):
            if not isinstance(load.get('flightId'), str):
                logger.error(f"Flight {i}: flightId must be string, got {type(load.get('flightId'))}: {load.get('flightId')}")
                # Convert to string if it's a UUID
                flight_loads[i]['flightId'] = str(load['flightId'])
            
            kits = load.get('loadedKits', {})
            for kit_type in ['first', 'business', 'premiumEconomy', 'economy']:
                if not isinstance(kits.get(kit_type, 0), int):
                    logger.error(f"Flight {i}: {kit_type} must be int, got {type(kits.get(kit_type))}: {kits.get(kit_type)}")
                    flight_loads[i]['loadedKits'][kit_type] = int(kits[kit_type])
        
        # Validate purchase orders
        for kit_type in ['first', 'business', 'premiumEconomy', 'economy']:
            if not isinstance(kit_purchases.get(kit_type, 0), int):
                logger.error(f"Purchase {kit_type} must be int, got {type(kit_purchases.get(kit_type))}: {kit_purchases.get(kit_type)}")
                kit_purchases[kit_type] = int(kit_purchases[kit_type])
        
        logger.debug(f"Playing round D{day}H{hour} - Loads: {len(flight_loads)}, "
                    f"Purchases: {kit_purchases}")
        
        # Log detailed payload for debugging 400 errors  
        if day == 0 and hour == 18:
            import json
            logger.error(f"D0H18 PAYLOAD: {json.dumps(payload, indent=2)}")
            # Log all headers being sent
            all_headers = self.session.headers.copy()
            all_headers['SESSION-ID'] = self.session_id
            logger.error(f"D0H18 HEADERS: {dict(all_headers)}")
        
        # Log detailed payload for debugging 400 errors
        if len(flight_loads) > 20 or any(v > 10000 for v in kit_purchases.values()):
            logger.warning(f"Large payload - Loads: {len(flight_loads)}, Purchases: {kit_purchases}")
        
        try:
            # Session headers already have API-KEY and Content-Type
            # Add SESSION-ID for this specific request
            response = self.session.post(url, json=payload, 
                                        headers={'SESSION-ID': self.session_id}, 
                                        timeout=30)
            
            # Log response details if there's an error
            if response.status_code >= 400:
                logger.error(f"HTTP {response.status_code}: {response.text[:500]}")
            
            response.raise_for_status()
            
            result = response.json()
            
            # Update current time
            self.current_day = result.get('day', day)
            self.current_hour = result.get('hour', hour)
            
            # Log response summary
            total_cost = result.get('totalCost', 0)
            penalties = result.get('penalties', [])
            flight_updates = result.get('flightUpdates', [])
            
            logger.debug(f"Round complete - Total cost: EUR{total_cost:,.2f}, "
                        f"Penalties: {len(penalties)}, Flight updates: {len(flight_updates)}")
            
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to play round D{day}H{hour}: {e}")
            raise
    
    def end_session(self) -> Dict:
        """
        End the current evaluation session
        
        Returns:
            Final response with total cost and penalties
        
        Raises:
            requests.HTTPError: If session end fails
        """
        if not self.session_id:
            raise ValueError("No active session to end.")
        
        url = f"{self.base_url}/api/v1/session/end"
        
        logger.info("Ending session...")
        
        try:
            response = self.session.post(url, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            total_cost = result.get('totalCost', 0)
            
            logger.info(f"Session ended - Final cost: EUR{total_cost:,.2f}")
            
            self.session_id = None
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to end session: {e}")
            raise
    
    def close(self):
        """Close the HTTP session"""
        self.session.close()
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure session is closed"""
        self.close()


class APIStrategy:
    """
    Adapter to run strategy algorithms with the backend API
    Converts between API format and internal data structures
    """
    
    def __init__(self, api_client: APIClient, strategy):
        """
        Initialize API strategy adapter
        
        Args:
            api_client: APIClient instance
            strategy: Strategy implementation (e.g., NaiveStrategy)
        """
        self.api = api_client
        self.strategy = strategy
    
    def run_session(self) -> Dict:
        """
        Run complete 720-hour session with the backend API
        
        Returns:
            Final session results including total cost
        """
        # Start session
        session_id = self.api.start_session()
        logger.info(f"Starting session {session_id}")
        
        try:
            # Main loop - play 720 rounds (30 days × 24 hours)
            for day in range(30):
                for hour in range(24):
                    # Get decisions from strategy
                    flight_loads, kit_purchases = self._get_strategy_decisions(day, hour)
                    
                    # Submit round to API
                    response = self.api.play_round(day, hour, flight_loads, kit_purchases)
                    
                    # Update strategy state with response
                    self._update_strategy_state(response)
                    
                    # Log progress periodically
                    if hour == 0:
                        total_cost = response.get('totalCost', 0)
                        logger.info(f"Day {day} complete - Total cost: EUR{total_cost:,.2f}")
            
            # End session and get final results
            final_result = self.api.end_session()
            return final_result
            
        except Exception as e:
            logger.error(f"Session failed: {e}")
            # Try to end session on error
            try:
                self.api.end_session()
            except:
                pass
            raise
    
    def _get_strategy_decisions(self, day: int, hour: int) -> Tuple[List[Dict], Dict[str, int]]:
        """
        Get decisions from strategy for current hour
        
        Returns:
            Tuple of (flight_loads, kit_purchases)
        """
        # Strategy should implement a method to get decisions
        # For now, return empty decisions (will be implemented per strategy)
        
        # Check inventory and purchase if needed
        purchases = self.strategy.check_and_purchase_kits()
        
        # Process departing flights
        flight_loads = self.strategy.get_flight_loads_for_hour(day, hour)
        
        # Convert to API format
        api_flight_loads = [
            {
                "flightId": str(load['flight_id']),
                "loadedKits": {
                    "first": load['kits']['first'],
                    "business": load['kits']['business'],
                    "premiumEconomy": load['kits']['premium_economy'],
                    "economy": load['kits']['economy']
                }
            }
            for load in flight_loads
        ]
        
        api_purchases = {
            "first": purchases.get('FIRST', 0),
            "business": purchases.get('BUSINESS', 0),
            "premiumEconomy": purchases.get('PREMIUM_ECONOMY', 0),
            "economy": purchases.get('ECONOMY', 0)
        }
        
        return api_flight_loads, api_purchases
    
    def _update_strategy_state(self, response: Dict):
        """
        Update strategy internal state based on API response
        
        Args:
            response: API response from play_round
        """
        # Update strategy with flight events and penalties
        # This will be implemented per strategy
        pass
