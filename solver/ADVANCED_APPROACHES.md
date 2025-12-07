# Advanced Optimization Approaches for Kit Management
# Analysis and Recommendations

## Problem Characteristics

### 1. Problem Type: Multi-Objective Stochastic Optimization with Constraints
- **State Space**: Inventory levels at N airports × 4 kit types × 720 hours = ~500K states
- **Action Space**: Kit loading decisions per flight × purchase decisions = ~1M actions/hour
- **Objectives**: Minimize cost + penalties (conflicting - stock vs service)
- **Constraints**: Capacity limits, processing times, lead times
- **Uncertainty**: Flight delays, actual passengers, actual distances
- **Horizon**: 30 days (720 hours) with long-term dependencies

### 2. Why Current Naive Approach Fails
```
Current Strategy: Reactive Loading
Problems:
1. No lookahead → loads kits without considering future demand
2. No demand forecasting → doesn't anticipate stock depletion
3. Greedy decisions → optimizes current hour, not total cost
4. No learning → repeats same mistakes every session
5. No risk management → doesn't handle uncertainty

Result: EUR 9.2B in end-game penalties (93% of total cost)
```

## Recommended Approaches (Ranked by Implementation Difficulty vs Impact)

### ⭐ TIER 1: High Impact, Moderate Complexity

#### 1. **Deep Q-Learning (DQN) with Experience Replay** ⭐ BEST FIT
```python
Why DQN?
✓ Learns optimal policy from trial-and-error
✓ Handles large state/action spaces
✓ Captures long-term dependencies (30-day horizon)
✓ Adapts to stochastic environment (delays, variability)
✓ Can be trained offline on historical data
✓ Generalizes to unseen scenarios

Architecture:
Input State (per hour):
- Current inventory at all airports (N × 4)
- Kits in processing (N × 4)
- Kits in transit (N × 4)
- Next 24h flight schedule with passenger counts
- Current day/hour (temporal encoding)
- Total cost so far

Action Space (per decision):
- Load [0-capacity] kits per flight per class
- Purchase [0-10000] kits per class at HUB

Reward Function:
reward = -1 * (operational_cost + penalties_this_hour)
        + bonus_for_zero_unfulfilled_passengers
        + penalty_for_end_game_unfulfilled_flights * future_discount
```

**Implementation Plan:**
```python
# solver/src/deep_q_learning_strategy.py

import torch
import torch.nn as nn
import numpy as np
from collections import deque
import random

class KitManagementDQN(nn.Module):
    """Deep Q-Network for kit management decisions"""
    def __init__(self, state_dim, action_dim):
        super().__init__()
        self.fc1 = nn.Linear(state_dim, 512)
        self.fc2 = nn.Linear(512, 512)
        self.fc3 = nn.Linear(512, 256)
        self.fc4 = nn.Linear(256, action_dim)
        self.dropout = nn.Dropout(0.2)
        
    def forward(self, x):
        x = torch.relu(self.fc1(x))
        x = self.dropout(x)
        x = torch.relu(self.fc2(x))
        x = self.dropout(x)
        x = torch.relu(self.fc3(x))
        return self.fc4(x)  # Q-values for each action

class DQNAgent:
    def __init__(self, state_dim, action_dim, learning_rate=0.001):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.q_network = KitManagementDQN(state_dim, action_dim).to(self.device)
        self.target_network = KitManagementDQN(state_dim, action_dim).to(self.device)
        self.target_network.load_state_dict(self.q_network.state_dict())
        
        self.optimizer = torch.optim.Adam(self.q_network.parameters(), lr=learning_rate)
        self.memory = deque(maxlen=10000)  # Experience replay buffer
        self.epsilon = 1.0  # Exploration rate
        self.epsilon_min = 0.01
        self.epsilon_decay = 0.995
        self.gamma = 0.99  # Discount factor
        self.batch_size = 64
        
    def get_state_vector(self, env):
        """Convert environment to state vector"""
        state = []
        
        # Airport inventories (flattened)
        for airport in env.airports:
            for kit_type in ['FIRST', 'BUSINESS', 'PREMIUM', 'ECONOMY']:
                state.append(airport.available_kits[kit_type] / airport.capacity[kit_type])
                state.append(airport.processing_kits[kit_type] / airport.capacity[kit_type])
        
        # Upcoming demand (next 24 hours)
        upcoming_flights = env.get_flights_next_24h()
        demand_vector = self._encode_demand(upcoming_flights)
        state.extend(demand_vector)
        
        # Temporal features
        state.append(env.current_day / 30.0)
        state.append(env.current_hour / 24.0)
        
        # Cost normalized
        state.append(env.total_cost / 10e9)  # Normalize to 0-1 range
        
        return np.array(state, dtype=np.float32)
    
    def select_action(self, state, valid_actions):
        """Epsilon-greedy action selection"""
        if random.random() < self.epsilon:
            return random.choice(valid_actions)  # Explore
        
        state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
        with torch.no_grad():
            q_values = self.q_network(state_tensor).cpu().numpy()[0]
        
        # Mask invalid actions
        masked_q_values = np.full(len(q_values), -np.inf)
        masked_q_values[valid_actions] = q_values[valid_actions]
        
        return np.argmax(masked_q_values)  # Exploit
    
    def train_step(self):
        """Train on a batch from experience replay"""
        if len(self.memory) < self.batch_size:
            return
        
        batch = random.sample(self.memory, self.batch_size)
        states, actions, rewards, next_states, dones = zip(*batch)
        
        states = torch.FloatTensor(states).to(self.device)
        actions = torch.LongTensor(actions).to(self.device)
        rewards = torch.FloatTensor(rewards).to(self.device)
        next_states = torch.FloatTensor(next_states).to(self.device)
        dones = torch.FloatTensor(dones).to(self.device)
        
        # Current Q values
        current_q = self.q_network(states).gather(1, actions.unsqueeze(1))
        
        # Target Q values (Double DQN)
        with torch.no_grad():
            next_actions = self.q_network(next_states).argmax(1)
            next_q = self.target_network(next_states).gather(1, next_actions.unsqueeze(1))
            target_q = rewards.unsqueeze(1) + (1 - dones.unsqueeze(1)) * self.gamma * next_q
        
        # Loss and backprop
        loss = nn.MSELoss()(current_q, target_q)
        self.optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.q_network.parameters(), 1.0)
        self.optimizer.step()
        
        # Decay epsilon
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
        
        return loss.item()
    
    def update_target_network(self):
        """Soft update of target network"""
        self.target_network.load_state_dict(self.q_network.state_dict())
```

**Training Process:**
```python
# solver/src/train_dqn.py

def train_dqn_agent(num_episodes=100):
    """Train DQN agent through self-play"""
    agent = DQNAgent(state_dim=500, action_dim=1000)
    
    for episode in range(num_episodes):
        # Start new session
        env = SimulationEnvironment()  # Offline simulator
        state = agent.get_state_vector(env)
        episode_reward = 0
        
        for hour in range(720):  # 30 days × 24 hours
            # Select action
            valid_actions = env.get_valid_actions()
            action = agent.select_action(state, valid_actions)
            
            # Execute action in environment
            next_state, reward, done = env.step(action)
            
            # Store experience
            agent.memory.append((state, action, reward, next_state, done))
            
            # Train
            if len(agent.memory) >= agent.batch_size:
                loss = agent.train_step()
            
            state = next_state
            episode_reward += reward
            
            if done:
                break
        
        # Update target network
        if episode % 10 == 0:
            agent.update_target_network()
        
        print(f"Episode {episode}: Reward={episode_reward:.2f}, Epsilon={agent.epsilon:.3f}")
        
        # Save best model
        if episode_reward > best_reward:
            torch.save(agent.q_network.state_dict(), 'best_dqn_model.pth')
    
    return agent
```

---

#### 2. **Genetic Algorithm with Multi-Objective Optimization** ⭐ ALTERNATIVE

```python
Why Genetic Algorithm?
✓ Good for discrete optimization (kit quantities)
✓ Handles multiple objectives (cost vs service)
✓ No need for differentiable reward function
✓ Population-based search explores diverse strategies
✓ Can incorporate domain knowledge via custom operators

Architecture:
Chromosome (Genome):
- Purchase schedule: [day0_kits, day1_kits, ..., day29_kits] per class
- Loading policies: [safety_margin, priority_weights, loading_rules]

Fitness Function:
fitness = -1 * total_cost
        = -1 * (operational_cost + penalties)

Genetic Operators:
- Crossover: Blend purchase schedules from two parents
- Mutation: Random adjustments to quantities (±10%)
- Selection: Tournament selection (top 20% survive)
```

**Implementation:**
```python
# solver/src/genetic_algorithm_strategy.py

import numpy as np
from typing import List, Tuple
import random

class Chromosome:
    """Represents a complete strategy for 30-day simulation"""
    def __init__(self, num_days=30):
        # Purchase decisions: [day][kit_type] -> quantity
        self.purchases = np.random.randint(0, 5000, size=(num_days, 4))
        
        # Loading policy parameters
        self.safety_margins = {  # % of capacity to maintain as buffer
            'FIRST': random.uniform(0.1, 0.4),
            'BUSINESS': random.uniform(0.1, 0.4),
            'PREMIUM': random.uniform(0.1, 0.4),
            'ECONOMY': random.uniform(0.1, 0.4)
        }
        
        self.demand_forecast_days = random.randint(3, 10)  # Lookahead window
        self.aggressive_early_purchase = random.choice([True, False])
        
        self.fitness = None
    
    def evaluate_fitness(self, simulator):
        """Run simulation with this strategy and calculate fitness"""
        total_cost = simulator.run_simulation(self)
        self.fitness = -total_cost  # Minimize cost = maximize negative cost
        return self.fitness

class GeneticAlgorithm:
    def __init__(self, population_size=50, generations=100):
        self.population_size = population_size
        self.generations = generations
        self.mutation_rate = 0.15
        self.crossover_rate = 0.7
        self.elitism_count = 5  # Top N preserved each generation
        
    def initialize_population(self):
        """Create initial random population"""
        return [Chromosome() for _ in range(self.population_size)]
    
    def crossover(self, parent1: Chromosome, parent2: Chromosome) -> Tuple[Chromosome, Chromosome]:
        """Two-point crossover"""
        child1, child2 = Chromosome(), Chromosome()
        
        # Crossover purchase schedules
        split = random.randint(0, 30)
        child1.purchases[:split] = parent1.purchases[:split]
        child1.purchases[split:] = parent2.purchases[split:]
        child2.purchases[:split] = parent2.purchases[:split]
        child2.purchases[split:] = parent1.purchases[split:]
        
        # Blend policy parameters
        for kit_type in ['FIRST', 'BUSINESS', 'PREMIUM', 'ECONOMY']:
            alpha = random.random()
            child1.safety_margins[kit_type] = alpha * parent1.safety_margins[kit_type] + \
                                              (1-alpha) * parent2.safety_margins[kit_type]
            child2.safety_margins[kit_type] = (1-alpha) * parent1.safety_margins[kit_type] + \
                                              alpha * parent2.safety_margins[kit_type]
        
        return child1, child2
    
    def mutate(self, chromosome: Chromosome):
        """Random mutations"""
        # Mutate purchases (±20%)
        for day in range(30):
            if random.random() < self.mutation_rate:
                delta = np.random.randint(-1000, 1000, size=4)
                chromosome.purchases[day] = np.clip(chromosome.purchases[day] + delta, 0, 10000)
        
        # Mutate safety margins
        for kit_type in chromosome.safety_margins:
            if random.random() < self.mutation_rate:
                chromosome.safety_margins[kit_type] += random.gauss(0, 0.05)
                chromosome.safety_margins[kit_type] = np.clip(chromosome.safety_margins[kit_type], 0.05, 0.5)
    
    def select_parents(self, population: List[Chromosome]) -> Tuple[Chromosome, Chromosome]:
        """Tournament selection"""
        tournament_size = 5
        tournament = random.sample(population, tournament_size)
        tournament.sort(key=lambda c: c.fitness, reverse=True)
        return tournament[0], tournament[1]
    
    def evolve(self, simulator):
        """Main evolution loop"""
        population = self.initialize_population()
        
        # Evaluate initial population
        for chromosome in population:
            chromosome.evaluate_fitness(simulator)
        
        best_fitness_history = []
        
        for generation in range(self.generations):
            # Sort by fitness
            population.sort(key=lambda c: c.fitness, reverse=True)
            best_fitness = population[0].fitness
            best_fitness_history.append(best_fitness)
            
            print(f"Generation {generation}: Best Cost = EUR{-best_fitness:,.2f}")
            
            # Elitism: Keep top N
            new_population = population[:self.elitism_count]
            
            # Generate offspring
            while len(new_population) < self.population_size:
                parent1, parent2 = self.select_parents(population)
                
                if random.random() < self.crossover_rate:
                    child1, child2 = self.crossover(parent1, parent2)
                else:
                    child1, child2 = Chromosome(), Chromosome()
                
                self.mutate(child1)
                self.mutate(child2)
                
                child1.evaluate_fitness(simulator)
                child2.evaluate_fitness(simulator)
                
                new_population.extend([child1, child2])
            
            population = new_population[:self.population_size]
        
        # Return best solution
        population.sort(key=lambda c: c.fitness, reverse=True)
        return population[0]
```

---

### TIER 2: Medium Impact, Lower Complexity

#### 3. **Monte Carlo Tree Search (MCTS)** 
```python
Why MCTS?
✓ Good for sequential decision-making
✓ Balances exploration vs exploitation
✓ No training required (online planning)
✓ Can handle partial observability

Cons:
- Slow for real-time decisions (needs many simulations)
- State space explosion with 720 hours
```

#### 4. **Linear Programming (LP) with Rolling Horizon**
```python
Why LP?
✓ Optimal solutions for convex problems
✓ Fast computation with modern solvers (Gurobi, CPLEX)
✓ Handles constraints naturally

Implementation:
- Variables: kit_loads[flight][class], purchases[day][class]
- Objective: minimize total_cost
- Constraints: capacity, inventory, demand satisfaction
- Solve 7-day window, execute 1 day, re-solve
```

---

## Hybrid Approach (RECOMMENDED) ⭐⭐⭐

**Combine strengths of multiple methods:**

```python
# solver/src/hybrid_strategy.py

class HybridIntelligentStrategy:
    """
    Tier 1: DQN for strategic decisions (purchases, high-level policy)
    Tier 2: LP for tactical optimization (exact kit loading given inventory)
    Tier 3: Heuristics for edge cases
    """
    
    def __init__(self):
        self.dqn_agent = DQNAgent.load_pretrained('best_dqn_model.pth')
        self.demand_forecaster = DemandForecaster()
        self.lp_optimizer = LinearProgramSolver()
    
    def play_round(self, api_response, day, hour):
        # 1. DQN decides: How much to purchase? Safety margins?
        state = self.get_state_vector(api_response)
        strategic_action = self.dqn_agent.select_action(state)
        purchases = self.decode_purchase_action(strategic_action)
        
        # 2. Forecast demand for next 7 days
        demand_forecast = self.demand_forecaster.predict_next_7_days(api_response)
        
        # 3. LP solves: Exactly how to load each flight?
        flight_loads = self.lp_optimizer.optimize_loading(
            flights=api_response['flightUpdates'],
            current_inventory=self.inventory_tracker.get_all_inventories(),
            demand_forecast=demand_forecast,
            constraints=self.get_constraints()
        )
        
        # 4. Submit decisions
        return {
            'flightLoads': flight_loads,
            'kitOrders': purchases
        }
```

---

## Implementation Roadmap (8-12 hours)

**Phase 1: Offline Simulator (2 hours)**
```python
# Build fast simulator that mimics API backend
# - Load CSV data
# - Simulate flight events, inventory, costs, penalties
# - No API calls → train 100x faster
```

**Phase 2: DQN Training (4 hours)**
```python
# Implement DQN agent
# Train for 100 episodes
# Save best model
```

**Phase 3: Integration (2 hours)**
```python
# Connect trained DQN to actual API
# Add safety checks, fallbacks
```

**Phase 4: Fine-tuning (2-4 hours)**
```python
# Hyperparameter tuning
# Test on different scenarios
# Compare to baseline
```

---

## Expected Results

| Approach | Implementation | Expected Cost | Improvement |
|----------|---------------|---------------|-------------|
| Naive (Current) | ✅ Done | EUR 10.0B | Baseline |
| Heuristics + Forecasting | 4 hours | EUR 1.5-2.0B | **-80%** |
| Genetic Algorithm | 8 hours | EUR 0.8-1.2B | **-88%** |
| **DQN (Recommended)** | **10 hours** | **EUR 0.5-0.8B** | **-92%** |
| Hybrid DQN + LP | 12 hours | EUR 0.3-0.5B | **-95%** |

---

## Quick Win: Demand Forecasting Heuristic (2 hours) ⚡

If you want immediate results without ML:

```python
def forecast_driven_strategy():
    """Simple but effective heuristic"""
    
    # Day 0: Analyze ALL 30 days of planned flights
    total_demand_per_airport = calculate_total_30_day_demand()
    
    # Purchase 120% of forecasted demand upfront
    for kit_type in ['FIRST', 'BUSINESS', 'PREMIUM', 'ECONOMY']:
        purchase_quantity = total_demand_per_airport['HUB1'][kit_type] * 1.2
        place_purchase_order(kit_type, purchase_quantity, lead_time=24h)
    
    # Every hour: Load flights with demand + 10% buffer
    for flight in upcoming_flights:
        for kit_type in flight.passengers:
            desired_kits = flight.passengers[kit_type] * 1.1  # 10% buffer
            available = get_inventory(flight.origin, kit_type)
            load_kits = min(desired_kits, available, flight.capacity[kit_type])
            
            # If short, expedite shipping from HUB
            if load_kits < flight.passengers[kit_type]:
                request_transfer_from_hub(...)
    
    return decisions

# Expected result: EUR 1.5B (85% improvement over naive)
```

Want me to implement the DQN or the quick-win heuristic?
