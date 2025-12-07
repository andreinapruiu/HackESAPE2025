"""
Train DQN Agent using Real Backend API
Runs episodes against live evaluation platform to learn optimal kit management strategy
"""

import sys
import os
import time
import logging
import numpy as np
import torch
from typing import Dict, List, Tuple

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api_client import APIClient
from src.data_warehouse import DataWarehouse
from dqn_agent import DQNAgent


logger = logging.getLogger(__name__)


class DQNAPITrainer:
    """Trains DQN agent using real backend API"""
    
    def __init__(self, data_warehouse: DataWarehouse, base_url: str, api_key: str, resume_from: str = None):
        """
        Initialize trainer with data warehouse and API connection
        
        Args:
            data_warehouse: Loaded DataWarehouse with airports, aircraft types, etc.
            base_url: Backend API base URL (e.g., "http://localhost:8080")
            api_key: API authentication key
            resume_from: Path to checkpoint to resume training from (optional)
        """
        self.dw = data_warehouse
        self.base_url = base_url
        self.api_key = api_key
        
        # Initialize DQN agent with airport data
        logger.info("Initializing DQN agent...")
        self.agent = self._initialize_agent()
        
        # Load checkpoint if resuming
        if resume_from and os.path.exists(resume_from):
            logger.info(f"Resuming training from: {resume_from}")
            self.agent.load(resume_from)
            logger.info(f"Resumed with epsilon={self.agent.epsilon:.4f}, memory size={len(self.agent.memory)}")
        
        # Training statistics
        self.episode_costs = []
        self.episode_losses = []
        self.best_cost = float('inf')
    
    def _initialize_agent(self) -> DQNAgent:
        """Initialize DQN agent with proper airport structure"""
        # Convert DataWarehouse airports to format expected by DQNAgent
        airports_dict = {}
        for code, airport in self.dw.airports.items():
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
        
        return DQNAgent(airports_dict)
    
    def train_episode(self, episode_num: int) -> Tuple[float, float, int]:
        """
        Train for one complete episode (30 days) using real API
        
        Args:
            episode_num: Current episode number (for logging)
        
        Returns:
            Tuple of (final_cost, avg_loss, total_penalties)
        """
        logger.info(f"\n{'='*80}")
        logger.info(f"EPISODE {episode_num} - Epsilon: {self.agent.epsilon:.4f}")
        logger.info(f"{'='*80}")
        
        # Create new API client for this episode
        api_client = APIClient(self.base_url, self.api_key)
        
        try:
            # Start new session
            session_id = api_client.start_session()
            logger.info(f"Session started: {session_id}")
            
            # Initialize episode state
            episode_losses = []
            total_penalties = 0
            
            # Get initial state from first empty round
            api_response = self._get_initial_state(api_client)
            state = self.agent.encode_state(api_response)
            
            # Play through 30 days (720 hours), starting from hour 1 (hour 0 already played)
            for day in range(30):
                day_start_cost = None
                start_hour = 1 if day == 0 else 0
                
                for hour in range(start_hour, 24):
                    if day_start_cost is None:
                        day_start_cost = api_response.get('totalCost', 0)
                    
                    # Select action using DQN policy
                    action_dict = self.agent.select_action(
                        state, 
                        training=True, 
                        api_response=api_response
                    )
                    action_id = action_dict['action_id']
                    
                    # Convert action to API format
                    flight_loads, kit_purchases = self._action_to_api_format(
                        action_dict, api_response
                    )
                    
                    # Execute action via API
                    next_api_response = api_client.play_round(
                        day, hour, flight_loads, kit_purchases
                    )
                    
                    # Calculate reward
                    reward, done = self._calculate_reward(
                        api_response, next_api_response, day, hour
                    )
                    
                    # Encode next state
                    next_state = self.agent.encode_state(next_api_response)
                    
                    # Store experience
                    self.agent.store_experience(state, action_dict, reward, next_state, done)
                    
                    # Train neural network
                    loss = self.agent.train_step()
                    if loss is not None:
                        episode_losses.append(loss)
                    
                    # Update state
                    state = next_state
                    api_response = next_api_response
                    
                    # Track penalties
                    penalties = next_api_response.get('penalties', [])
                    total_penalties += len(penalties)
                
                # Log day completion
                day_end_cost = api_response.get('totalCost', 0)
                day_cost = day_end_cost - day_start_cost
                avg_recent_loss = np.mean(episode_losses[-24:]) if len(episode_losses) >= 24 else 0
                
                logger.info(
                    f"Day {day:2d}/29 | Cost: EUR {day_end_cost:>15,.2f} | "
                    f"Day Cost: EUR {day_cost:>12,.2f} | "
                    f"Penalties: {total_penalties:4d} | "
                    f"Loss: {avg_recent_loss:>10.2f}"
                )
            
            # End session and get final results
            final_result = self._safe_end_session(api_client, api_response)
            final_cost = final_result.get('totalCost', 0)
            avg_loss = np.mean(episode_losses) if episode_losses else 0
            
            return final_cost, avg_loss, total_penalties
            
        except Exception as e:
            logger.error(f"Episode failed: {e}", exc_info=True)
            # Try to end session cleanly
            try:
                api_client.end_session()
            except:
                pass
            raise
        finally:
            api_client.close()
    
    def _get_initial_state(self, api_client: APIClient) -> Dict:
        """
        Get initial state from API by submitting empty first round
        """
        # First round - submit empty decision to get initial state
        response = api_client.play_round(0, 0, [], {
            'first': 0,
            'business': 0,
            'premiumEconomy': 0,
            'economy': 0
        })
        return response
    
    def _action_to_api_format(self, action_dict: Dict, api_response: Dict) -> Tuple[List[Dict], Dict[str, int]]:
        """
        Convert DQN action to API request format
        
        Args:
            action_dict: Action dictionary from DQN with parameters
            api_response: Current API response with flight updates
        
        Returns:
            Tuple of (flight_loads, kit_purchases) in API format
        """
        # Action dict already has parameters
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
            # Apply 50% reduction factor (proven optimal)
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
                
                # Map to internal key for capacity check
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
    
    def _calculate_reward(self, prev_response: Dict, curr_response: Dict, 
                         day: int, hour: int) -> Tuple[float, bool]:
        """
        Calculate reward for this timestep
        
        Reward design:
        - Negative cost increase (minimize cost)
        - Penalty for violations
        - Bonus for completing without penalties
        
        Args:
            prev_response: Previous API response
            curr_response: Current API response
            day: Current day
            hour: Current hour
        
        Returns:
            Tuple of (reward, done)
        """
        prev_cost = prev_response.get('totalCost', 0)
        curr_cost = curr_response.get('totalCost', 0)
        cost_increase = curr_cost - prev_cost
        
        # Base reward: negative cost increase (scaled)
        reward = -cost_increase / 1e6  # Scale to manageable range
        
        # Penalty for constraint violations
        penalties = curr_response.get('penalties', [])
        penalty_cost = sum(p.get('cost', 0) for p in penalties)
        reward -= penalty_cost / 1e6
        
        # Small bonus for no penalties
        if len(penalties) == 0:
            reward += 0.01
        
        # Check if episode is done
        done = (day == 29 and hour == 23)
        
        # Large bonus for completing episode with low cost
        if done:
            final_cost = curr_cost
            if final_cost < 1e10:  # Less than 10B
                reward += 100.0
            elif final_cost < 5e10:  # Less than 50B
                reward += 50.0
            elif final_cost < 1e11:  # Less than 100B
                reward += 10.0
        
        return reward, done
    
    def _safe_end_session(self, api_client: APIClient, last_response: Dict) -> Dict:
        """Safely end session, handling auto-completion"""
        try:
            return api_client.end_session()
        except Exception as e:
            if '404' in str(e):
                logger.info("Session already ended (auto-completed)")
                return last_response
            else:
                raise
    
    def train(self, num_episodes: int = 100, save_every: int = 10):
        """
        Train DQN agent for multiple episodes
        
        Args:
            num_episodes: Number of episodes to train
            save_every: Save checkpoint every N episodes
        """
        logger.info(f"\n{'='*80}")
        logger.info("STARTING DQN TRAINING WITH REAL API")
        logger.info(f"{'='*80}")
        logger.info(f"Episodes: {num_episodes}")
        logger.info(f"API: {self.base_url}")
        logger.info(f"Exploration: ε={self.agent.epsilon:.3f} → {self.agent.epsilon_min:.3f}")
        logger.info(f"Learning rate: {self.agent.optimizer.param_groups[0]['lr']}")
        logger.info(f"{'='*80}\n")
        
        for episode in range(1, num_episodes + 1):
            episode_start_time = time.time()
            
            try:
                # Train one episode
                final_cost, avg_loss, total_penalties = self.train_episode(episode)
                
                # Record statistics
                self.episode_costs.append(final_cost)
                self.episode_losses.append(avg_loss)
                episode_time = time.time() - episode_start_time
                
                # Check for new best
                if final_cost < self.best_cost:
                    self.best_cost = final_cost
                    self.agent.save('models/dqn_agent_best.pth')
                    logger.info(f"\n⭐ NEW BEST! Cost: EUR {final_cost:,.2f}")
                
                # Episode summary
                logger.info(f"\n{'='*80}")
                logger.info(f"EPISODE {episode} COMPLETE")
                logger.info(f"{'='*80}")
                logger.info(f"  Final Cost:      EUR {final_cost:>15,.2f}")
                logger.info(f"  Best So Far:     EUR {self.best_cost:>15,.2f}")
                logger.info(f"  Avg Loss:        {avg_loss:>15.2f}")
                logger.info(f"  Episode Time:    {episode_time:>15.1f}s")
                logger.info(f"  Total Penalties: {total_penalties:>15d}")
                logger.info(f"  Memory Size:     {len(self.agent.memory):>15d}")
                logger.info(f"{'='*80}\n")
                
                # Update target network periodically
                if episode % self.agent.target_update_freq == 0:
                    self.agent.update_target_network()
                    logger.info(">>> Target network updated <<<\n")
                
                # Decay exploration
                self.agent.decay_epsilon()
                
                # Update learning rate
                self.agent.update_learning_rate(final_cost)
                
                # Save checkpoint
                if episode % save_every == 0:
                    self.agent.save(f'checkpoints/dqn_agent_episode_{episode}.pth')
                    logger.info(f"Checkpoint saved: episode_{episode}.pth\n")
                
            except Exception as e:
                logger.error(f"Episode {episode} failed: {e}", exc_info=True)
                logger.info("Continuing to next episode...\n")
                continue
        
        # Training complete
        logger.info(f"\n{'='*80}")
        logger.info("TRAINING COMPLETE!")
        logger.info(f"{'='*80}")
        if self.episode_costs:
            logger.info(f"Best Episode Cost:     EUR {min(self.episode_costs):,.2f}")
            logger.info(f"Final Episode Cost:    EUR {self.episode_costs[-1]:,.2f}")
            improvement = (1 - min(self.episode_costs)/self.episode_costs[0])*100
            logger.info(f"Improvement:           {improvement:.1f}%")
        else:
            logger.info("No episodes completed successfully")
        logger.info(f"{'='*80}\n")
        
        # Save final model and training data
        self.agent.save('models/dqn_agent_final.pth')
        np.save('models/training_costs.npy', np.array(self.episode_costs))
        np.save('models/training_losses.npy', np.array(self.episode_losses))
        
        logger.info("Training data saved:")
        logger.info("  - models/dqn_agent_final.pth")
        logger.info("  - models/dqn_agent_best.pth")
        logger.info("  - models/training_costs.npy")
        logger.info("  - models/training_losses.npy\n")


def main():
    """Main training script"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Train DQN agent with real API')
    parser.add_argument('api_key', type=str, help='API authentication key')
    parser.add_argument('base_url', type=str, help='Backend API base URL')
    parser.add_argument('--episodes', type=int, default=100, help='Number of episodes')
    parser.add_argument('--save-every', type=int, default=10, help='Save checkpoint every N episodes')
    parser.add_argument('--resume', type=str, default=None, 
                       help='Path to checkpoint to resume training from (e.g., models/dqn_agent_best.pth)')
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
    
    # Create directories
    os.makedirs('models', exist_ok=True)
    os.makedirs('checkpoints', exist_ok=True)
    
    # Initialize trainer
    trainer = DQNAPITrainer(dw, args.base_url, args.api_key, resume_from=args.resume)
    
    # Train
    trainer.train(num_episodes=args.episodes, save_every=args.save_every)
    
    logger.info("\n✅ Training complete! Use dqn_solver.py to run the trained agent.")


if __name__ == "__main__":
    main()
