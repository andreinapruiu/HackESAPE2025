"""
Run Trained DQN Agent on Evaluation Platform
Loads best trained model and executes one complete session
"""

import sys
import os
import logging
import torch

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api_client import APIClient
from src.data_warehouse import DataWarehouse
from dqn_agent import DQNAgent


logger = logging.getLogger(__name__)


def run_trained_agent(data_warehouse: DataWarehouse, base_url: str, api_key: str, 
                      model_path: str = 'models/dqn_agent_best.pth'):
    """
    Run trained DQN agent on evaluation platform
    
    Args:
        data_warehouse: Loaded DataWarehouse
        base_url: Backend API base URL
        api_key: API authentication key
        model_path: Path to trained model file
    
    Returns:
        Final session results dict
    """
    logger.info(f"\n{'='*80}")
    logger.info("RUNNING TRAINED DQN AGENT")
    logger.info(f"{'='*80}")
    logger.info(f"Model: {model_path}")
    logger.info(f"API: {base_url}")
    logger.info(f"{'='*80}\n")
    
    # Initialize DQN agent
    airports_dict = {}
    for code, airport in data_warehouse.airports.items():
        airports_dict[code] = {
            'id': airport.id,
            'code': code,
            'capacity': {
                'FIRST': airport.capacity_fc,
                'BUSINESS': airport.capacity_bc,
                'PREMIUM_ECONOMY': airport.capacity_pe,
                'ECONOMY': airport.capacity_ec
            }
        }
    
    agent = DQNAgent(airports_dict)
    
    # Load trained model
    if os.path.exists(model_path):
        agent.load(model_path)
        logger.info(f"✅ Loaded trained model from {model_path}\n")
    else:
        logger.error(f"❌ Model file not found: {model_path}")
        logger.info("Run training first: python -m src.train_dqn_api <api_key> <base_url> --episodes 10\n")
        return None
    
    # Create API client
    api_client = APIClient(base_url, api_key)
    
    try:
        # Start session
        session_id = api_client.start_session()
        logger.info(f"Session started: {session_id}\n")
        
        # Get initial state
        api_response = api_client.play_round(0, 0, [], {
            'first': 0,
            'business': 0,
            'premiumEconomy': 0,
            'economy': 0
        })
        
        state = agent.encode_state(api_response)
        
        # Play through 30 days with trained policy (no exploration)
        for day in range(30):
            day_start_cost = None
            start_hour = 1 if day == 0 else 0
            
            for hour in range(start_hour, 24):
                if day_start_cost is None:
                    day_start_cost = api_response.get('totalCost', 0)
                
                # Select action using trained policy (greedy, no exploration)
                action_dict = agent.select_action(
                    state,
                    training=False,  # Use greedy policy
                    api_response=api_response
                )
                
                # Convert to API format
                flight_loads, kit_purchases = _action_to_api_format(
                    action_dict, api_response
                )
                
                # Execute action
                next_api_response = api_client.play_round(
                    day, hour, flight_loads, kit_purchases
                )
                
                # Update state
                state = agent.encode_state(next_api_response)
                api_response = next_api_response
            
            # Log day completion
            day_end_cost = api_response.get('totalCost', 0)
            day_cost = day_end_cost - day_start_cost
            penalties = api_response.get('penalties', [])
            
            logger.info(
                f"Day {day:2d}/29 | Cost: EUR {day_end_cost:>15,.2f} | "
                f"Day Cost: EUR {day_cost:>12,.2f} | "
                f"Penalties: {len(penalties):4d}"
            )
        
        # End session
        try:
            final_result = api_client.end_session()
        except Exception as e:
            if '404' in str(e):
                logger.info("\nSession already ended (auto-completed)")
                final_result = api_response
            else:
                raise
        
        final_cost = final_result.get('totalCost', 0)
        total_penalties = len(final_result.get('penalties', []))
        
        logger.info(f"\n{'='*80}")
        logger.info("SESSION COMPLETE")
        logger.info(f"{'='*80}")
        logger.info(f"Final Cost:      EUR {final_cost:>15,.2f}")
        logger.info(f"Total Penalties: {total_penalties:>15d}")
        logger.info(f"{'='*80}\n")
        
        return final_result
        
    except Exception as e:
        logger.error(f"Execution failed: {e}", exc_info=True)
        try:
            api_client.end_session()
        except:
            pass
        raise
    finally:
        api_client.close()


def _action_to_api_format(action_dict: dict, api_response: dict):
    """Convert DQN action to API format"""
    action_params = action_dict
    
    flight_updates = api_response.get('flightUpdates', [])
    inventories = api_response.get('inventories', {})
    day = api_response['day']
    hour = api_response['hour']
    
    # 1. Generate flight loads
    flight_loads = []
    for flight in flight_updates:
        if flight['eventType'] == 'CHECKED_IN':
            flight_id = str(flight['flightId'])
            passengers = flight['passengers']
            origin = flight['originAirport']
            
            # Apply loading policy with conservative 70% factor
            loading_factor = action_params['loading_policy'] * 0.70
            
            loaded_kits = {}
            for api_key, internal_key in [
                ('first', 'FIRST'),
                ('business', 'BUSINESS'),
                ('premiumEconomy', 'PREMIUM_ECONOMY'),
                ('economy', 'ECONOMY')
            ]:
                passenger_count = passengers.get(internal_key, 0)
                desired = int(passenger_count * loading_factor)
                
                # Don't exceed available inventory
                available = inventories.get(origin, {}).get(internal_key, 0)
                loaded_kits[api_key] = min(desired, max(0, available))
            
            flight_loads.append({
                'flightId': flight_id,
                'loadedKits': loaded_kits
            })
    
    # 2. Generate kit purchases
    purchase_qty = action_params['purchase_qty']
    freq = action_params['purchase_frequency']
    
    # Check if should purchase this hour
    should_purchase = False
    if freq == 2:  # Twice daily
        should_purchase = (hour == 0 or hour == 12)
    elif freq == 1:  # Daily
        should_purchase = (hour == 0)
    
    kit_purchases = {'first': 0, 'business': 0, 'premiumEconomy': 0, 'economy': 0}
    
    if should_purchase and purchase_qty > 0:
        # Apply 50% reduction factor
        reduced_qty = int(purchase_qty * 0.5)
        
        # Check HUB1 capacity
        hub_inv = inventories.get('HUB1', {})
        capacity_limit = 4500
        
        # Distribute purchases
        distribution = {
            'economy': 0.5,
            'business': 0.25,
            'premiumEconomy': 0.15,
            'first': 0.10
        }
        
        for api_key, ratio in distribution.items():
            qty = int(reduced_qty * ratio)
            
            # Map to internal key
            internal_key = {
                'first': 'FIRST',
                'business': 'BUSINESS',
                'premiumEconomy': 'PREMIUM_ECONOMY',
                'economy': 'ECONOMY'
            }[api_key]
            
            current_stock = hub_inv.get(internal_key, 0)
            safe_qty = min(qty, max(0, capacity_limit - current_stock))
            
            kit_purchases[api_key] = safe_qty
    
    return flight_loads, kit_purchases


def main():
    """Main execution script"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Run trained DQN agent')
    parser.add_argument('api_key', type=str, help='API authentication key')
    parser.add_argument('base_url', type=str, help='Backend API base URL')
    parser.add_argument('--model', type=str, default='models/dqn_agent_best.pth',
                       help='Path to trained model file')
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s'
    )
    
    # Load data warehouse
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(script_dir, '..', '..', 'eval-platform',
                           'src', 'main', 'resources', 'liquibase', 'data')
    data_dir = os.path.abspath(data_dir)
    
    logger.info("Loading data warehouse...")
    dw = DataWarehouse(data_dir)
    dw.load_all_data()
    
    # Run agent
    result = run_trained_agent(dw, args.base_url, args.api_key, args.model)
    
    if result:
        logger.info("✅ Execution complete!")
    else:
        logger.info("❌ Execution failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
