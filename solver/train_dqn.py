"""
Train DQN Agent using Offline Simulator
Runs multiple episodes of self-play to learn optimal kit management strategy
"""

import sys
import os
import time
import numpy as np
from offline_simulator import OfflineSimulator
from dqn_agent import DQNAgent


def train_dqn_agent(num_episodes=100, save_every=10, checkpoint_dir='checkpoints'):
    """
    Train DQN agent for specified number of episodes
    """
    # Create checkpoint directory
    os.makedirs(checkpoint_dir, exist_ok=True)
    os.makedirs('models', exist_ok=True)
    
    # Initialize
    print("Initializing training environment...")
    simulator = OfflineSimulator()
    agent = DQNAgent(simulator.airports)
    
    # Training history
    episode_costs = []
    episode_losses = []
    best_cost = float('inf')
    
    print("\n" + "=" * 80)
    print("STARTING DQN TRAINING")
    print("=" * 80)
    print(f"Episodes: {num_episodes}")
    print(f"Exploration: ε={agent.epsilon:.3f} → {agent.epsilon_min:.3f}")
    print(f"Learning rate: {agent.optimizer.param_groups[0]['lr']}")
    print(f"Batch size: {agent.batch_size}")
    print(f"Discount factor: γ={agent.gamma}")
    print("=" * 80)
    
    for episode in range(num_episodes):
        episode_start_time = time.time()
        
        # Reset environment
        api_response = simulator.reset()
        state = agent.encode_state(api_response)
        done = False
        episode_cost = 0
        episode_step = 0
        losses = []
        
        print(f"\n{'='*80}")
        print(f"EPISODE {episode + 1}/{num_episodes} | Epsilon: {agent.epsilon:.4f}")
        print(f"{'='*80}")
        
        # Play episode
        while not done:
            # Select action with action masking
            action = agent.select_action(state, training=True, api_response=api_response, simulator_state=simulator)
            
            # Convert to API format (pass simulator state for constraint checking)
            api_action = agent.action_space.action_to_api_request(action, api_response, simulator)
            
            # Execute action in simulator
            next_api_response, reward, done, info = simulator.step(api_action)
            next_state = agent.encode_state(next_api_response)
            
            # Store experience
            agent.store_experience(state, action, reward, next_state, done)
            
            # Train
            loss = agent.train_step()
            if loss is not None:
                losses.append(loss)
            
            # Update state
            state = next_state
            api_response = next_api_response
            episode_cost = info['total_cost']
            episode_step += 1
            
            # Print progress every 24 hours (1 day)
            if info['hour'] == 0:
                avg_recent_loss = np.mean(losses[-24:]) if losses else 0
                print(f"  Day {info['day']:2d}/30 | Cost: EUR {episode_cost:>15,.2f} | "
                      f"Penalties: {len(simulator.penalties):4d} | "
                      f"Loss: {avg_recent_loss:>10.2f}")
        
        # Episode complete
        episode_time = time.time() - episode_start_time
        episode_costs.append(episode_cost)
        avg_loss = np.mean(losses) if losses else 0
        episode_losses.append(avg_loss)
        
        # Track best model
        if episode_cost < best_cost:
            best_cost = episode_cost
            agent.save(f'models/dqn_agent_best.pth')
            print(f"\n  ⭐ NEW BEST! Cost: EUR {episode_cost:,.2f}")
        
        print(f"\n{'='*80}")
        print(f"EPISODE {episode + 1} COMPLETE")
        print(f"{'='*80}")
        print(f"  Final Cost:      EUR {episode_cost:>15,.2f}")
        print(f"  Best So Far:     EUR {min(episode_costs):>15,.2f}")
        print(f"  Avg Loss:        {avg_loss:>15,.2f}")
        print(f"  Episode Time:    {episode_time:>15.1f}s")
        print(f"  Total Penalties: {len(simulator.penalties):>15d}")
        print(f"  Memory Size:     {len(agent.memory):>15d}")
        print(f"{'='*80}")
        
        # Update target network
        if (episode + 1) % agent.target_update_freq == 0:
            agent.update_target_network()
            print(f"  >>> Target network updated <<<")
        
        # Decay exploration
        agent.decay_epsilon()
        
        # Update learning rate based on episode cost
        agent.update_learning_rate(episode_cost)
        
        # Save checkpoint
        if (episode + 1) % save_every == 0:
            agent.save(f'{checkpoint_dir}/dqn_agent_episode_{episode + 1}.pth')
        
        # Early stopping if performing very well
        if episode >= 20:
            recent_avg = np.mean(episode_costs[-5:])
            if recent_avg < 1e9:  # Less than 1 billion
                print(f"\n🎉 EARLY SUCCESS! Recent avg cost: EUR {recent_avg:,.2f}")
                print("Continuing training to refine further...")
    
    print("\n" + "=" * 80)
    print("TRAINING COMPLETE!")
    print("=" * 80)
    print(f"Best Episode Cost:     EUR {min(episode_costs):,.2f}")
    print(f"Final Episode Cost:    EUR {episode_costs[-1]:,.2f}")
    print(f"Improvement:           {(1 - min(episode_costs)/episode_costs[0])*100:.1f}%")
    print("=" * 80)
    
    # Save final model
    agent.save('models/dqn_agent_final.pth')
    
    # Save training history
    np.save('models/training_costs.npy', np.array(episode_costs))
    np.save('models/training_losses.npy', np.array(episode_losses))
    
    print("\nTraining data saved:")
    print("  - models/dqn_agent_final.pth")
    print("  - models/dqn_agent_best.pth")
    print("  - models/training_costs.npy")
    print("  - models/training_losses.npy")
    
    # Print cost trajectory
    print("\nCost Trajectory:")
    print(f"{'Episode':<10} {'Cost (EUR)':<20} {'Improvement':<15}")
    print("-" * 45)
    for i in [0, 9, 19, 29, 39, 49, 59, 69, 79, 89, 99]:
        if i < len(episode_costs):
            cost = episode_costs[i]
            improvement = (1 - cost/episode_costs[0])*100
            print(f"{i+1:<10} {cost:>18,.2f}  {improvement:>12.1f}%")
    
    return agent, episode_costs, episode_losses


def plot_training_results(episode_costs, episode_losses):
    """Visualize training progress"""
    try:
        import matplotlib.pyplot as plt
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 5))
        
        # Cost progression
        ax1.plot(episode_costs, linewidth=2, color='blue')
        ax1.axhline(y=1e9, color='red', linestyle='--', label='Target: EUR 1B')
        ax1.set_xlabel('Episode')
        ax1.set_ylabel('Total Cost (EUR)')
        ax1.set_title('DQN Training: Cost per Episode')
        ax1.grid(True, alpha=0.3)
        ax1.legend()
        ax1.set_yscale('log')
        
        # Loss progression
        ax2.plot(episode_losses, linewidth=2, color='orange')
        ax2.set_xlabel('Episode')
        ax2.set_ylabel('Average Loss')
        ax2.set_title('DQN Training: Loss per Episode')
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig('models/training_results.png', dpi=300)
        print("\n📊 Training plots saved to models/training_results.png")
    except ImportError:
        print("\n📊 matplotlib not installed - skipping plots")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Train DQN agent for kit management')
    parser.add_argument('--episodes', type=int, default=100, help='Number of episodes')
    parser.add_argument('--save-every', type=int, default=10, help='Save checkpoint every N episodes')
    args = parser.parse_args()
    
    # Train agent
    agent, costs, losses = train_dqn_agent(
        num_episodes=args.episodes,
        save_every=args.save_every
    )
    
    # Plot results
    plot_training_results(costs, losses)
    
    print("\n✅ Training complete! Use dqn_solver.py to run the trained agent on live API.")
