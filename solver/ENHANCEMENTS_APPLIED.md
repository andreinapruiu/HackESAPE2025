# DQN Enhancements Based on Game Rules

## Overview
Applied rule-based enhancements to DQN agent based on cost/penalty structure from `index.html`. Current status: infrastructure complete, training shows EUR 3.9T costs (still 390× baseline).

## ✅ Enhancements Applied

### 1. Constraint-Aware Action Space
**File:** `dqn_agent.py` - `ActionSpace` class

**Changes:**
- Increased purchase bins: `[0, 1000, 2000, 3000, 5000, 8000]` (6 options)
- Restricted loading policies: `[1.0, 1.05, 1.10]` (3 options, max 110% to avoid overload)
- Added purchase frequency: `[0, 1, 2]` (never, daily, twice daily)
- **Total actions:** 54 (was 20)

**Rule-Based Logic in `action_to_api_request`:**
```python
# Constraint 1: Don't exceed aircraft capacity (avoid PLANE_OVERLOAD)
if aircraft_capacity and kt_internal in aircraft_capacity:
    desired = min(desired, aircraft_capacity[kt_internal])

# Constraint 2: Don't exceed available inventory (avoid NEGATIVE_INVENTORY)
if origin in inventories and kt_internal in inventories[origin]:
    available = inventories[origin][kt_internal]
    desired = min(desired, max(0, available))

# Constraint 3: At least cover passengers (minimize UNFULFILLED_PASSENGERS)
desired = max(desired, passenger_count)
```

**Early Purchase Strategy:**
```python
# Critical: Always purchase on early days to avoid end-game shortages
if day <= 5 and hour == 0:
    should_purchase = True
    purchase_qty = max(purchase_qty, 3000)  # Minimum early purchase
```

**Kit Distribution:**
- Economy: 50% (most common)
- Business: 25%
- Premium Economy: 15%
- First: 10%

### 2. Enhanced State Encoding with Demand Forecasting
**File:** `dqn_agent.py` - `StateEncoder` class

**Dimension Increase:** 500 → 800

**New Features Added:**

**A. 3-Day Demand Forecast (84 dimensions)**
```python
def _forecast_demand(self, api_response, days_ahead=3):
    # Aggregate all scheduled flights' passenger counts
    # Per airport and kit type
    # Critical for avoiding END_OF_GAME_UNFULFILLED_FLIGHT_KITS
```

**B. Constraint Health Indicators (84 dimensions)**
```python
# Health: 1.0 if inventory > 3-day demand, else 0.0
health = 1.0 if current_inv > demand_forecast else 0.0
```
- Binary flag per airport and kit type
- Tells agent whether current inventory is sufficient

**C. Days Remaining (1 dimension)**
```python
days_remaining = 30 - day
state.append(days_remaining / 30.0)
```
- Urgency indicator: approaching end-game = more critical

**D. Penalty Type Breakdown (5 dimensions)**
```python
penalty_counts = {
    'NEGATIVE_INVENTORY': 0,
    'UNFULFILLED_PASSENGERS': 0,
    'PLANE_OVERLOAD': 0,
    'OVER_CAPACITY': 0,
    'END_OF_GAME_UNFULFILLED_FLIGHT_KITS': 0
}
```
- Agent can identify which constraints are being violated
- Enables targeted learning

**E. Global Inventory Health (1 dimension)**
```python
global_health = 1.0 if total_inventory > total_demand_3d else 0.0
```
- System-wide status indicator

### 3. Penalty-Weighted Reward Function
**File:** `offline_simulator.py` - `step()` method

**Base Reward:**
```python
reward = -round_cost  # Minimize cost = maximize reward
```

**Massive Penalties for Violations:**
```python
# Critical violations
if code == 'NEGATIVE_INVENTORY':
    reward -= 10000  # -10K per violation
elif code == 'INCORRECT_FLIGHT_LOAD':
    reward -= 10000

# High priority violations
elif code == 'UNFULFILLED_PASSENGERS':
    reward -= 5000
elif code == 'PLANE_OVERLOAD':
    reward -= 5000

# Catastrophic end-game violations
elif code == 'END_OF_GAME_UNFULFILLED_FLIGHT_KITS':
    reward -= 50000  # -50K (most expensive)

# Medium priority
elif code == 'OVER_CAPACITY':
    reward -= 1000
```

**Positive Reinforcement:**
```python
# Bonus for maintaining healthy state (no penalties)
if len(round_penalties) == 0:
    reward += 1000  # +1K bonus for clean hour

# Progressive bonus: better to avoid penalties early
if len(round_penalties) == 0 and self.day < 20:
    reward += 500  # Extra bonus for early prevention
```

**Rationale:**
- Penalties are 100-10,000× more expensive than operations (per `index.html`)
- Agent should prioritize constraint satisfaction over cost minimization
- Early prevention is better than late fixes

### 4. Neural Network Architecture Update
**File:** `dqn_agent.py` - `DQNAgent.__init__`

**Changes:**
```python
def __init__(self, airports, state_dim=800, learning_rate=0.001):
    # Was: state_dim=500
    # Now: state_dim=800 (to accommodate enhanced state)
```

**Network remains:** 800 → 512 → 512 → 256 → 54 actions

---

## 📊 Results After Enhancements

### Test Training (3 Episodes)
```
Episode 1: EUR 3,903,870,536,208.46  (323,087 penalties)
Episode 2: EUR 3,952,135,638,705.30  (316,172 penalties)
Episode 3: EUR 3,884,677,931,218.98  (312,475 penalties)
```

**Observations:**
- Costs: EUR 3.9 trillion (still 390× baseline EUR 10B)
- Penalties: ~320K per episode (444 per hour avg)
- Loss: ~25 quadrillion (very high, indicates unstable learning)
- **Improvement:** 0.5% over 3 episodes (minimal)

**Status:** ⚠️ Constraints still being violated massively

---

## 🔍 Root Cause Analysis

### Why Enhancements Haven't Solved the Problem Yet

**1. Exploration vs. Exploitation Trade-Off**
- Epsilon starts at 1.0 (100% random exploration)
- Random actions ignore constraint logic in `action_to_api_request`
- Need: More episodes to decay epsilon (currently only 3 episodes)

**2. Action Selection Bypasses Constraint Checking**
```python
# Current flow:
action = agent.select_action(state, training=True)  # Random with ε=1.0
api_action = agent.action_space.action_to_api_request(action, api_response, simulator)
```

**Issue:** Even with constraint-aware `action_to_api_request`, the action selection doesn't **filter out invalid actions** before choosing.

**3. State Complexity**
- 800-dimensional state is very rich
- Neural network needs more training data to learn patterns
- 3 episodes = 2,160 samples (very small)
- Typical DQN needs 10K-100K samples

**4. Reward Signal Delay**
- Penalties applied at end-of-game (day 30)
- Agent doesn't see consequence of poor purchasing until much later
- Credit assignment problem: which action caused the penalty?

---

## 🚀 Recommended Next Steps

### Priority 1: Increase Training Episodes
**Action:** Run 50-100 episodes to allow epsilon decay and learning

**Expected Result:**
- Epsilon decays: 1.0 → 0.01 over 100 episodes
- Agent transitions from exploration to exploitation
- Neural network accumulates 72,000 training samples
- Q-values converge to better estimates

**Command:**
```bash
python train_dqn.py --episodes 100 --save-every 10
```

**Time:** ~20-25 minutes (14s per episode)

### Priority 2: Add Action Masking
**Concept:** Filter invalid actions before selection

**Implementation:**
```python
def get_valid_actions(self, api_response):
    """Return list of action IDs that satisfy constraints"""
    valid_actions = []
    
    for action_id, action in enumerate(self.actions):
        # Check if action would violate constraints
        is_valid = True
        
        # Check 1: Would loading exceed aircraft capacity?
        for flight in api_response['flightUpdates']:
            # ... check logic ...
            
        # Check 2: Would loading exceed available inventory?
        # ... check logic ...
        
        if is_valid:
            valid_actions.append(action_id)
    
    return valid_actions

# In DQNAgent.select_action():
valid_actions = self.action_space.get_valid_actions(api_response)
if training and random.random() < self.epsilon:
    action_id = random.choice(valid_actions)  # Only valid actions
```

**Benefit:** Eliminates invalid exploration, accelerates learning

### Priority 3: Hierarchical Action Space
**Concept:** Separate purchase and loading decisions

**Structure:**
```python
# Step 1: Purchase decision (simplified)
purchase_actions = [
    'none',           # Don't buy
    'conservative',   # Buy 1K per type
    'moderate',       # Buy 3K per type
    'aggressive'      # Buy 5K per type
]

# Step 2: Loading decision (per flight)
loading_actions = [
    'exact',          # 100% of passengers
    'buffer_5',       # 105% of passengers
    'buffer_10'       # 110% of passengers
]
```

**Benefit:** Reduces action space complexity, improves learning speed

### Priority 4: Curriculum Learning
**Concept:** Train on progressively harder scenarios

**Stages:**
1. **Stage 1 (Days 1-10):** Simple scenario, fewer flights
2. **Stage 2 (Days 1-20):** Medium complexity
3. **Stage 3 (Days 1-30):** Full 30-day challenge

**Implementation:**
```python
# Start with 10-day episodes
for episode in range(20):
    simulator.max_days = 10
    # ... train ...

# Increase to 20 days
for episode in range(20, 50):
    simulator.max_days = 20
    # ... train ...

# Full 30 days
for episode in range(50, 100):
    simulator.max_days = 30
    # ... train ...
```

**Benefit:** Agent learns basic constraint satisfaction first, then scales up

### Priority 5: Baseline Heuristic Pre-Training
**Concept:** Initialize Q-network with good heuristic policy

**Heuristic Policy:**
```python
def heuristic_policy(api_response):
    """Simple rule-based policy"""
    day = api_response['day']
    hour = api_response['hour']
    inventories = api_response['inventories']
    demand_3d = forecast_demand(api_response, days=3)
    
    # Purchase logic
    if hour == 0:  # Once per day
        for airport in key_airports:
            for kit_type in kit_types:
                shortage = demand_3d[airport][kit_type] - inventories[airport][kit_type]
                if shortage > 0:
                    purchase(airport, kit_type, shortage * 1.2)  # 120% buffer
    
    # Loading logic
    for flight in api_response['flightUpdates']:
        if flight['eventType'] == 'SCHEDULED':
            for kit_type in kit_types:
                passengers = flight['passengers'][kit_type]
                load(flight, kit_type, passengers)  # Exact match
    
    return action
```

**Pre-Training:**
```python
# Collect heuristic experiences
for episode in range(10):
    while not done:
        action = heuristic_policy(api_response)
        next_state, reward, done, info = simulator.step(action)
        agent.store_experience(state, action, reward, next_state, done)

# Train Q-network on heuristic data
for _ in range(1000):
    agent.train_step()

# Now start DQN training with initialized network
```

**Benefit:** Warm start with reasonable Q-value estimates

---

## 📈 Expected Training Trajectory (100 Episodes)

Based on enhancements + increased training:

| Episodes | Cost (EUR) | Penalties | Status |
|----------|------------|-----------|--------|
| 1-10 | 1-5 trillion | 300K+ | Random exploration |
| 11-30 | 100B - 1T | 100K-200K | Learning constraints |
| 31-50 | 50B - 200B | 50K-100K | Reducing violations |
| 51-80 | 20B - 100B | 10K-50K | Refinement |
| 81-100 | 10B - 50B | 5K-20K | Convergence |

**Target:** Best model <EUR 50B (5× baseline, 20× improvement from current)

**Realistic Expectation:**
- Current DQN approach may reach EUR 20-50B with 100 episodes
- To reach <EUR 5B (target), may need:
  - Action masking (Priority 2)
  - Hierarchical actions (Priority 3)
  - Curriculum learning (Priority 4)
  - Or switch to more sophisticated algorithm (PPO, A3C, etc.)

---

## 🔧 Code Modifications Summary

| File | Lines Changed | Description |
|------|---------------|-------------|
| `dqn_agent.py` | ~150 | ActionSpace + StateEncoder enhancements |
| `offline_simulator.py` | ~30 | Reward shaping with penalty weights |
| `train_dqn.py` | 1 | Pass simulator to action_to_api_request |

**Total:** ~180 lines modified/added

---

## 🎯 Immediate Action Plan

**Step 1: Full Training Run**
```bash
cd d:\SAP_HackITall\HackESAPE2025\solver
python train_dqn.py --episodes 100 --save-every 10
```
**Time:** ~20-25 minutes
**Expected:** EUR 10-50B best cost (10-50× improvement)

**Step 2: Analyze Results**
- Check training_costs.npy for cost trajectory
- Identify which penalties persist (from logs)
- Determine if convergence is occurring

**Step 3: Implement Priority 2 (Action Masking)**
- If costs still >EUR 50B after 100 episodes
- Add constraint filtering before action selection
- Retrain for 50 more episodes

**Step 4: Deploy Best Model**
- Create `dqn_solver.py` for live API
- Test on backend
- Submit solution

---

## 📝 Key Insights from index.html Rules

### Cost Structure (Reminder)
- **Operational Costs:** EUR 0.50-8.00 per kit
- **Penalty Multipliers:**
  - Negative inventory: **5000×**
  - Unfulfilled passengers: **5× distance × kitCost**
  - Plane overload: **10× distance × fuelCost**
  - End-game unfulfilled: **10× distance × passengers × kitCost × weight**

### Strategy (from index.html)
> "Evitați penalitățile cu orice preț - sunt mult mai scumpe decât costurile operaționale!"
> 
> *Translation: "Avoid penalties at all costs - they are much more expensive than operational costs!"*

**This is the core principle:** Constraint satisfaction >> Cost minimization

---

## ✅ Next Command to Run

```bash
python train_dqn.py --episodes 100 --save-every 10
```

This will train the enhanced DQN with:
- 54 constraint-aware actions
- 800-dimensional state with demand forecasting
- Penalty-weighted rewards (-50K for end-game penalties)
- Progressive epsilon decay (1.0 → 0.01)

**Expected time:** ~20-25 minutes
**Expected result:** EUR 10-50B (10-50× better than current EUR 3.9T)
