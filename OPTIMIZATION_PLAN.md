# Comprehensive Optimization Plan for Rotables Challenge
## Expert Logistics Engineer Solution Strategy

**Author:** Senior Software Engineer with 20 years in Warehouse & Logistics Optimization  
**Challenge:** Hub-Spoke Airline Kit Management - 30 days (720 hours) simulation  
**Objective:** Minimize total cost (operational + penalties)

---

## Executive Summary

After thorough analysis of the evaluation platform code (`SessionServiceImpl.java`, penalty factors, data models), I've identified the critical optimization vectors and developed a phased approach that balances implementation complexity with cost reduction potential.

**Key Findings from Code Analysis:**
- **162 airports** (1 HUB + 161 outstations)
- **7,287 flight instances** across 30 days (447 unique recurring flight routes)
- **4 aircraft types** with varying capacities and costs per kg/km
- **4 kit types** with different weights, costs, processing times, and lead times
- **13 penalty types** with severe cost multipliers (especially negative inventory: 5342x)

---

## Phase 1: Data Analysis & Baseline Infrastructure (Days 1-3)

### 1.1 Complete Data Ingestion & Parsing

**Objective:** Build comprehensive data models and calculate all static metrics upfront.

#### Implementation Steps:

```python
# Data structures to build
class DataWarehouse:
    """Central repository for all static game data"""
    
    def __init__(self):
        self.airports = {}           # code -> Airport object
        self.flights = {}            # flight_id -> Flight object
        self.flight_schedule = {}    # (day, hour) -> [Flight list]
        self.aircraft_types = {}     # type_code -> AircraftType
        self.route_analysis = {}     # (origin, dest) -> RouteMetrics
        
    def load_all_data(self):
        """Load and pre-process all CSV files"""
        self.load_airports()
        self.load_aircraft_types()
        self.load_flights()
        self.build_flight_index()
        self.calculate_route_metrics()
        self.analyze_network_structure()
```

**Critical Calculations:**

1. **Flight Network Analysis:**
   - For each airport pair (HUB ↔ Outstation): calculate roundtrip time
   - Processing time windows at each outstation
   - Minimum turnaround time for kit reuse
   - Daily/weekly flight frequency patterns

2. **Cost Matrices:**
   - Loading cost per kit class per airport
   - Processing cost per kit class per airport
   - Transport cost = `distance × weight × costPerKgPerKm`
   - Total operational cost per route per kit type

3. **Capacity Constraints:**
   - Stock capacity per airport per kit class
   - Aircraft capacity per type per kit class
   - Initial stock levels at all airports

### 1.2 Penalty Calculator Module

**Critical Finding:** Negative inventory penalty (5342x) is catastrophic - must avoid at all costs!

```python
class PenaltyCalculator:
    """Exact implementation matching SessionServiceImpl.java logic"""
    
    # Penalty factors from PenaltyFactors.java
    FLIGHT_OVERLOAD_PER_DISTANCE = 5.0
    UNFULFILLED_KIT_PER_DISTANCE = 0.003
    INCORRECT_FLIGHT_LOAD = 5000.0
    NEGATIVE_INVENTORY = 5342.0  # CRITICAL!
    OVER_CAPACITY_STOCK = 777.0
    END_GAME_REMAINING_STOCK = 0.0013
    END_GAME_PENDING_PROCESSING = 0.0013
    END_GAME_UNFULFILLED_FLIGHT = 1.5
    EARLY_END_GAME = 1000.0  # per hour
    
    def calculate_unfulfilled_penalty(self, passengers, loaded_kits, 
                                     kit_cost, distance):
        """Formula from line 480-507 in SessionServiceImpl.java"""
        unfulfilled = passengers - loaded_kits
        if unfulfilled > 0:
            return (self.UNFULFILLED_KIT_PER_DISTANCE * 
                    kit_cost * distance * unfulfilled)
        return 0.0
    
    def calculate_overload_penalty(self, loaded_kits, capacity, 
                                  kit_cost, distance):
        """Formula from line 519-565 in SessionServiceImpl.java"""
        overload = loaded_kits - capacity
        if overload > 0:
            return (self.FLIGHT_OVERLOAD_PER_DISTANCE * 
                    kit_cost * distance * overload)
        return 0.0
    
    def calculate_negative_inventory_penalty(self, negative_kits):
        """CRITICAL: From line 651 in SessionServiceImpl.java"""
        if negative_kits < 0:
            return self.NEGATIVE_INVENTORY * abs(negative_kits)
        return 0.0
```

### 1.3 State Tracking System

**Objective:** Maintain perfect synchronization with platform state across 720 hours.

```python
class GameState:
    """Complete game state tracker"""
    
    def __init__(self, data_warehouse):
        self.current_day = 0
        self.current_hour = 0
        self.total_cost = 0.0
        
        # Stock tracking per airport per kit type
        self.stock_levels = {}  # (airport_id, kit_type) -> quantity
        
        # In-flight kits (not yet at destination)
        self.in_flight_kits = []  # [(flight_id, arrival_day, arrival_hour, kits)]
        
        # Processing queue (kits being cleaned at outstations)
        self.processing_queue = []  # [(airport_id, completion_day, hour, kits)]
        
        # Purchasing orders (kits ordered but not delivered)
        self.purchase_orders = []  # [(delivery_day, delivery_hour, kits)]
        
        # Flight events for next hour
        self.next_scheduled_flights = []
        self.next_checked_in_flights = []
        self.next_landed_flights = []
        
    def initialize_from_csv(self, airports_data):
        """Set initial stock levels from airports_with_stocks.csv"""
        for airport in airports_data:
            self.stock_levels[(airport.id, 'FIRST')] = airport.initial_fc_stock
            self.stock_levels[(airport.id, 'BUSINESS')] = airport.initial_bc_stock
            self.stock_levels[(airport.id, 'PREMIUM_ECONOMY')] = airport.initial_pe_stock
            self.stock_levels[(airport.id, 'ECONOMY')] = airport.initial_ec_stock
    
    def get_effective_stock(self, airport_id, kit_type, lookahead_hours=24):
        """
        Calculate effective available stock considering:
        - Current physical stock
        - Kits in processing (will be available after processing time)
        - Kits in-flight returning to this airport
        - Pending purchase orders
        - Committed loads for upcoming flights
        """
        physical = self.stock_levels.get((airport_id, kit_type), 0)
        
        # Add kits completing processing within lookahead window
        processing = sum(
            kits for (aid, day, hour, kt, kits) in self.processing_queue
            if aid == airport_id and kt == kit_type and 
            (day * 24 + hour) <= (self.current_day * 24 + self.current_hour + lookahead_hours)
        )
        
        # Add kits arriving on returning flights
        returning = sum(
            kits for (fid, arr_day, arr_hour, kt, kits) in self.in_flight_kits
            if self.get_flight_destination(fid) == airport_id and kt == kit_type and
            (arr_day * 24 + arr_hour) <= (self.current_day * 24 + self.current_hour + lookahead_hours)
        )
        
        # Add purchase orders arriving within window
        purchases = sum(
            kits for (del_day, del_hour, kt, kits) in self.purchase_orders
            if kt == kit_type and 
            (del_day * 24 + del_hour) <= (self.current_day * 24 + self.current_hour + lookahead_hours)
        )
        
        return physical + processing + returning + purchases
```

---

## Phase 2: Baseline Algorithm - Rule-Based Heuristics (Days 4-7)

### 2.1 Naive v1.0 - Exact Match Strategy

**Goal:** Complete a full 720-hour session without crashes, establish baseline cost.

**Strategy:**
- Load exactly `actual_passengers` kits for each CHECKED_IN flight
- Purchase kits at HUB1 when stock < 1000 (for any class)
- No optimization, just survivability

**Expected Cost:** ~€500,000 - €1,000,000 (baseline)

```python
def naive_strategy_v1(game_state, hour_response):
    """Baseline: survive without optimizing"""
    
    decisions = {
        'flightLoads': [],
        'kitPurchasingOrders': {'first': 0, 'business': 0, 
                                'premiumEconomy': 0, 'economy': 0}
    }
    
    # Load CHECKED_IN flights (1 hour before departure)
    for flight in hour_response.flight_updates:
        if flight.eventType == 'CHECKED_IN':
            decisions['flightLoads'].append({
                'flightId': flight.flightId,
                'loadedKits': {
                    'first': flight.passengers.first,
                    'business': flight.passengers.business,
                    'premiumEconomy': flight.passengers.premiumEconomy,
                    'economy': flight.passengers.economy
                }
            })
    
    # Replenish HUB1 stock conservatively
    hub_stock = game_state.get_hub_stock()
    if hub_stock['first'] < 1000:
        decisions['kitPurchasingOrders']['first'] = 2000
    if hub_stock['business'] < 1000:
        decisions['kitPurchasingOrders']['business'] = 5000
    if hub_stock['premiumEconomy'] < 1000:
        decisions['kitPurchasingOrders']['premiumEconomy'] = 3000
    if hub_stock['economy'] < 1000:
        decisions['kitPurchasingOrders']['economy'] = 15000
    
    return decisions
```

### 2.2 Improved v1.5 - Safety Buffer Strategy

**Enhancements:**
- Load `actual_passengers + 5%` to handle variations
- Dynamic purchase triggers based on 7-day demand forecast
- Track returning kits to avoid over-purchasing

**Expected Improvement:** 15-20% cost reduction

```python
def improved_strategy_v1_5(game_state, hour_response):
    """Add safety margins and basic forecasting"""
    
    decisions = {'flightLoads': [], 'kitPurchasingOrders': {...}}
    
    # Calculate 7-day demand forecast
    forecast = calculate_demand_forecast(game_state, days=7)
    
    # Load flights with 5% buffer
    for flight in hour_response.flight_updates:
        if flight.eventType == 'CHECKED_IN':
            buffer_multiplier = 1.05
            decisions['flightLoads'].append({
                'flightId': flight.flightId,
                'loadedKits': {
                    'first': int(flight.passengers.first * buffer_multiplier),
                    'business': int(flight.passengers.business * buffer_multiplier),
                    'premiumEconomy': int(flight.passengers.premiumEconomy * buffer_multiplier),
                    'economy': int(flight.passengers.economy * buffer_multiplier)
                }
            })
    
    # Purchase based on effective stock vs forecast
    for kit_type in ['first', 'business', 'premiumEconomy', 'economy']:
        effective = game_state.get_effective_stock('HUB1', kit_type, 168)  # 7 days
        demand = forecast[kit_type]
        
        if effective < demand * 0.5:  # Below 50% of forecasted need
            purchase_amount = int((demand - effective) * 1.2)  # 20% buffer
            decisions['kitPurchasingOrders'][kit_type] = purchase_amount
    
    return decisions
```

---

## Phase 3: Advanced Optimization - Network Flow (Days 8-14)

### 3.1 Kit Flow Model

**Key Insight:** This is a **dynamic network flow problem** with time-varying supply/demand.

**Model Components:**

1. **Nodes:** 
   - Airports × Kit Types × Time Steps = 162 × 4 × 720 = ~466,560 nodes
   - (Reduced by considering only active time windows)

2. **Arcs:**
   - **Flight arcs:** Kit movement on flights (origin → destination)
   - **Processing arcs:** Used kits → Available kits (after processing time)
   - **Purchase arcs:** Money → Kits at HUB1 (after lead time)
   - **Storage arcs:** Stock carrying across time (t → t+1)

3. **Constraints:**
   - Stock capacity at each airport
   - Aircraft capacity on each flight
   - Non-negativity (cannot have negative stock!)
   - Flow conservation (kits in = kits out at each node)

```python
class NetworkFlowOptimizer:
    """
    Advanced optimization using minimum-cost network flow.
    Can be solved optimally with LP solvers (PuLP, OR-Tools).
    """
    
    def __init__(self, game_state, data_warehouse, horizon_hours=168):
        self.state = game_state
        self.data = data_warehouse
        self.horizon = horizon_hours  # Optimize over 7-day rolling window
        
    def build_optimization_model(self):
        """
        Build LP model for next 168 hours (7 days).
        Re-solve every 24 hours with updated state.
        """
        from pulp import LpProblem, LpMinimize, LpVariable, lpSum
        
        model = LpProblem("Kit_Flow_Optimization", LpMinimize)
        
        # Decision variables
        flight_loads = {}  # (flight_id, kit_type) -> quantity
        purchases = {}     # (day, hour, kit_type) -> quantity
        stock_levels = {}  # (airport_id, kit_type, day, hour) -> quantity
        
        # Initialize variables
        for t in range(self.horizon):
            day, hour = self._hour_to_day_hour(t)
            
            # Flight load variables
            flights = self.data.get_flights_at_hour(day, hour)
            for flight in flights:
                for kit_type in ['first', 'business', 'premiumEconomy', 'economy']:
                    var_name = f"load_{flight.id}_{kit_type}"
                    flight_loads[(flight.id, kit_type)] = LpVariable(
                        var_name, lowBound=0, upBound=self._get_aircraft_capacity(flight, kit_type)
                    )
            
            # Purchase variables (only at HUB1)
            for kit_type in ['first', 'business', 'premiumEconomy', 'economy']:
                var_name = f"purchase_{day}_{hour}_{kit_type}"
                purchases[(day, hour, kit_type)] = LpVariable(var_name, lowBound=0)
            
            # Stock level variables
            for airport_id in self.data.airports.keys():
                for kit_type in ['first', 'business', 'premiumEconomy', 'economy']:
                    var_name = f"stock_{airport_id}_{kit_type}_{day}_{hour}"
                    capacity = self._get_storage_capacity(airport_id, kit_type)
                    stock_levels[(airport_id, kit_type, day, hour)] = LpVariable(
                        var_name, lowBound=0, upBound=capacity
                    )
        
        # Objective function: Minimize total cost
        total_cost = 0
        
        # 1. Loading costs
        for (flight_id, kit_type), var in flight_loads.items():
            loading_cost = self._get_loading_cost(flight_id, kit_type)
            transport_cost = self._get_transport_cost(flight_id, kit_type)
            total_cost += var * (loading_cost + transport_cost)
        
        # 2. Purchase costs
        for (day, hour, kit_type), var in purchases.items():
            purchase_cost = self._get_kit_cost(kit_type)
            total_cost += var * purchase_cost
        
        # 3. Processing costs (applied when kits land)
        for (flight_id, kit_type), var in flight_loads.items():
            processing_cost = self._get_processing_cost(flight_id, kit_type)
            total_cost += var * processing_cost
        
        # 4. Penalty approximations (linearized where possible)
        # - Unfulfilled passengers: max(0, passengers - loaded_kits)
        # - Overload: max(0, loaded_kits - capacity) [already bounded]
        # - Negative stock: MUST AVOID with hard constraints
        
        model += total_cost
        
        # Constraints
        self._add_flow_conservation_constraints(model, flight_loads, purchases, stock_levels)
        self._add_passenger_fulfillment_constraints(model, flight_loads)
        self._add_capacity_constraints(model, flight_loads, stock_levels)
        
        return model, flight_loads, purchases
    
    def _add_flow_conservation_constraints(self, model, flight_loads, purchases, stock_levels):
        """
        For each (airport, kit_type, time):
        stock[t] = stock[t-1] 
                   - sum(loaded_on_departing_flights) 
                   + sum(arriving_from_returning_flights_after_processing)
                   + purchases_delivered[t]
        """
        for t in range(1, self.horizon):
            day, hour = self._hour_to_day_hour(t)
            prev_day, prev_hour = self._hour_to_day_hour(t - 1)
            
            for airport_id in self.data.airports.keys():
                for kit_type in ['first', 'business', 'premiumEconomy', 'economy']:
                    
                    # Current stock
                    current = stock_levels[(airport_id, kit_type, day, hour)]
                    previous = stock_levels[(airport_id, kit_type, prev_day, prev_hour)]
                    
                    # Departing flights (kits leaving)
                    departures = self._get_departing_flights(airport_id, day, hour)
                    outflow = lpSum([flight_loads[(f.id, kit_type)] for f in departures])
                    
                    # Arriving flights (kits returning after processing)
                    arrivals = self._get_arriving_flights_completing_processing(airport_id, kit_type, day, hour)
                    inflow = lpSum([flight_loads[(f.id, kit_type)] for f in arrivals])
                    
                    # Purchases arriving (only at HUB1)
                    if airport_id == 'HUB1':
                        purchase_inflow = self._get_purchases_arriving(kit_type, day, hour, purchases)
                    else:
                        purchase_inflow = 0
                    
                    # Flow conservation
                    model += current == previous - outflow + inflow + purchase_inflow
    
    def _add_passenger_fulfillment_constraints(self, model, flight_loads):
        """
        Soft constraint: loaded_kits >= passengers
        Implemented via penalty in objective (already included)
        OR hard constraint: loaded_kits >= passengers * 0.98 (allow 2% shortfall)
        """
        for (flight_id, kit_type), var in flight_loads.items():
            passengers = self._get_passenger_count(flight_id, kit_type)
            model += var >= passengers * 0.98  # Hard lower bound
    
    def solve_and_extract_decisions(self, model, flight_loads, purchases):
        """Solve LP and extract decisions for next 24 hours"""
        from pulp import PULP_CBC_CMD
        
        # Solve (CBC is free, CPLEX/Gurobi are faster)
        status = model.solve(PULP_CBC_CMD(msg=0, timeLimit=60))
        
        if status != 1:
            return None  # Failed to solve, fallback to heuristic
        
        # Extract decisions for next 24 hours only
        next_24h_flights = self._get_flights_in_range(0, 24)
        
        decisions = {
            'flightLoads': [
                {
                    'flightId': f.id,
                    'loadedKits': {
                        'first': int(flight_loads[(f.id, 'first')].varValue),
                        'business': int(flight_loads[(f.id, 'business')].varValue),
                        'premiumEconomy': int(flight_loads[(f.id, 'premiumEconomy')].varValue),
                        'economy': int(flight_loads[(f.id, 'economy')].varValue)
                    }
                }
                for f in next_24h_flights if f.eventType == 'CHECKED_IN'
            ],
            'kitPurchasingOrders': {
                'first': int(sum(purchases[(d, h, 'first')].varValue 
                               for d, h in self._next_24_hours())),
                'business': int(sum(purchases[(d, h, 'business')].varValue 
                                  for d, h in self._next_24_hours())),
                'premiumEconomy': int(sum(purchases[(d, h, 'premiumEconomy')].varValue 
                                        for d, h in self._next_24_hours())),
                'economy': int(sum(purchases[(d, h, 'economy')].varValue 
                                 for d, h in self._next_24_hours()))
            }
        }
        
        return decisions
```

**Expected Improvement:** 30-40% cost reduction vs baseline

---

## Phase 4: Intelligent Heuristics - Domain-Specific Rules (Days 15-18)

### 4.1 Processing Time Optimization

**Critical Insight:** Processing times vary significantly between airports (4-47 hours for First Class).

**Strategy:**
- Calculate **minimum turnaround time** for each outstation
- If turnaround < processing_time: send extra kits to avoid stockouts
- Prioritize fast-processing airports for high-frequency routes

```python
def calculate_turnaround_times(data_warehouse):
    """
    For each outstation, calculate time between:
    1. Landing at outstation (kits used)
    2. Departure of return flight (kits needed back at HUB)
    """
    turnaround_map = {}
    
    for airport_code in data_warehouse.outstations:
        # Find all HUB -> Outstation flights
        outbound_flights = data_warehouse.get_flights('HUB1', airport_code)
        # Find all Outstation -> HUB flights
        return_flights = data_warehouse.get_flights(airport_code, 'HUB1')
        
        min_turnaround = float('inf')
        
        for out_flight in outbound_flights:
            for ret_flight in return_flights:
                # Time from landing outbound to departing return
                arrival_hour = out_flight.arrival_day * 24 + out_flight.arrival_hour
                departure_hour = ret_flight.departure_day * 24 + ret_flight.departure_hour
                
                if departure_hour > arrival_hour:
                    turnaround = departure_hour - arrival_hour
                    min_turnaround = min(min_turnaround, turnaround)
        
        turnaround_map[airport_code] = min_turnaround
        
        # Check if kits can be processed in time
        airport = data_warehouse.airports[airport_code]
        processing_times = {
            'first': airport.first_processing_time,
            'business': airport.business_processing_time,
            'premiumEconomy': airport.premium_economy_processing_time,
            'economy': airport.economy_processing_time
        }
        
        for kit_type, proc_time in processing_times.items():
            if proc_time > min_turnaround:
                # CRITICAL: Kits won't be ready! Need to pre-position extras
                deficit_hours = proc_time - min_turnaround
                print(f"WARNING: {airport_code} {kit_type} has {deficit_hours}h deficit!")
    
    return turnaround_map
```

### 4.2 Route Prioritization

**Insight:** Not all routes are equal in cost/penalty sensitivity.

**Priority Metrics:**
1. **High-penalty routes:** Long distance + high passenger count
2. **Tight turnaround routes:** Processing time > turnaround time
3. **High-frequency routes:** Daily flights (highest demand)

```python
def prioritize_routes(data_warehouse):
    """Rank routes by optimization importance"""
    
    route_scores = []
    
    for route_key in data_warehouse.route_analysis.keys():
        origin, dest = route_key
        metrics = data_warehouse.route_analysis[route_key]
        
        # Score components
        distance_factor = metrics.avg_distance / 1000  # Normalize
        frequency_factor = metrics.flights_per_week
        passenger_volume = metrics.avg_total_passengers
        penalty_risk = distance_factor * passenger_volume * frequency_factor
        
        # Processing risk
        if metrics.min_turnaround < metrics.max_processing_time:
            processing_risk = 2.0  # High risk
        else:
            processing_risk = 1.0
        
        total_score = penalty_risk * processing_risk
        
        route_scores.append((route_key, total_score, metrics))
    
    # Sort by score descending
    route_scores.sort(key=lambda x: x[1], reverse=True)
    
    return route_scores
```

### 4.3 Dynamic Safety Stock Calculation

**Per-Airport, Per-Kit Type Safety Stock:**

```python
def calculate_safety_stock(airport_code, kit_type, data_warehouse, game_state):
    """
    Safety stock = f(demand_variability, lead_time, processing_time, penalty_cost)
    """
    
    # Get historical demand stats (from flight data)
    demand_mean, demand_std = get_demand_statistics(airport_code, kit_type, data_warehouse)
    
    # Lead time to replenish from HUB
    if airport_code == 'HUB1':
        lead_time = KIT_LEAD_TIMES[kit_type]
    else:
        # Time for HUB to send kits to outstation
        avg_flight_time = get_avg_flight_time('HUB1', airport_code)
        lead_time = avg_flight_time
    
    # Processing time (kits unavailable)
    airport = data_warehouse.airports[airport_code]
    processing_time = airport.get_processing_time(kit_type)
    
    # Service level (higher for high-penalty scenarios)
    penalty_factor = get_penalty_factor(airport_code, kit_type, data_warehouse)
    if penalty_factor > 10000:  # High penalty routes
        service_level_z = 2.33  # 99% service level
    else:
        service_level_z = 1.65  # 95% service level
    
    # Safety stock formula: z * σ * sqrt(lead_time)
    safety_stock = service_level_z * demand_std * math.sqrt(lead_time + processing_time)
    
    return int(safety_stock)
```

---

## Phase 5: Machine Learning Enhancement (Days 19-23)

### 5.1 Demand Forecasting with Time Series

**Model:** ARIMA or Prophet for passenger demand prediction

```python
from prophet import Prophet
import pandas as pd

class DemandForecaster:
    """ML-based demand forecasting per route per kit class"""
    
    def __init__(self, flight_data):
        self.models = {}  # (route, kit_type) -> Prophet model
        self._train_models(flight_data)
    
    def _train_models(self, flight_data):
        """Train separate model for each route-kit combination"""
        
        # Group flights by route
        for route_key in flight_data.get_unique_routes():
            origin, dest = route_key
            route_flights = flight_data.get_flights_for_route(origin, dest)
            
            for kit_type in ['first', 'business', 'premiumEconomy', 'economy']:
                # Prepare time series data
                ts_data = pd.DataFrame({
                    'ds': [f.departure_datetime for f in route_flights],
                    'y': [f.get_passenger_count(kit_type) for f in route_flights]
                })
                
                # Train Prophet model
                model = Prophet(
                    daily_seasonality=True,
                    weekly_seasonality=True,
                    yearly_seasonality=False  # Only 30 days data
                )
                model.fit(ts_data)
                
                self.models[(route_key, kit_type)] = model
    
    def forecast(self, route_key, kit_type, horizon_hours=168):
        """Predict demand for next 7 days"""
        
        model = self.models.get((route_key, kit_type))
        if not model:
            return None
        
        # Create future dataframe
        future = model.make_future_dataframe(periods=horizon_hours, freq='H')
        forecast = model.predict(future)
        
        # Extract predictions with confidence intervals
        predictions = forecast[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].tail(horizon_hours)
        
        return predictions
```

### 5.2 Reinforcement Learning for Real-Time Decisions

**Model:** Deep Q-Network (DQN) or Proximal Policy Optimization (PPO)

**State Space:**
- Current stock levels (162 airports × 4 kit types = 648 dimensions)
- In-flight kits (dynamic, ~100-200 dimensions)
- Processing queue (dynamic, ~100-200 dimensions)
- Next 24h flight schedule (features extracted)
- Current time (day, hour)
- Total cost so far

**Action Space:**
- For each CHECKED_IN flight: discrete bins [0%, 90%, 95%, 100%, 105%, 110%] of passengers
- Purchase decisions: discrete bins [0, 100, 500, 1000, 2000, 5000] per kit type

**Reward:**
- Negative of cost incurred in this hour (operational + penalties)

```python
import torch
import torch.nn as nn
from stable_baselines3 import PPO

class KitManagementEnv(gym.Env):
    """Custom Gym environment for RL training"""
    
    def __init__(self, data_warehouse):
        super().__init__()
        self.data = data_warehouse
        
        # State: 648 (stocks) + 200 (in-flight) + 200 (processing) + 50 (flights) + 10 (time/cost)
        self.observation_space = gym.spaces.Box(
            low=-np.inf, high=np.inf, shape=(1108,), dtype=np.float32
        )
        
        # Action: 6 load levels per flight (avg 10 flights/hour) + 4 purchase bins = ~64 actions
        self.action_space = gym.spaces.MultiDiscrete([6] * 40 + [6] * 4)
        
        self.reset()
    
    def reset(self):
        """Start new episode from hour 0"""
        self.state = GameState(self.data)
        self.state.initialize_from_csv(self.data.airports)
        return self._get_observation()
    
    def step(self, action):
        """Execute action, advance 1 hour, return next state and reward"""
        
        # Decode action into flight loads and purchases
        decisions = self._decode_action(action)
        
        # Call platform API (or simulator)
        response = self._call_platform_api(decisions)
        
        # Calculate reward (negative cost)
        hourly_cost = response.totalCost - self.state.total_cost
        reward = -hourly_cost
        
        # Update state
        self.state.update_from_response(response)
        
        # Check if done
        done = (self.state.current_day * 24 + self.state.current_hour >= 720)
        
        return self._get_observation(), reward, done, {}
    
    def _get_observation(self):
        """Extract state features as numpy array"""
        obs = np.concatenate([
            self._encode_stocks(),
            self._encode_in_flight(),
            self._encode_processing(),
            self._encode_upcoming_flights(),
            self._encode_time_and_cost()
        ])
        return obs

# Training
env = KitManagementEnv(data_warehouse)
model = PPO('MlpPolicy', env, verbose=1, learning_rate=3e-4, n_steps=2048)
model.learn(total_timesteps=1_000_000)  # Train for 1M hours (1388 episodes)
model.save("kit_management_ppo")
```

**Expected Improvement with RL:** 15-25% over LP-based approach (handles non-linearities better)

---

## Phase 6: Hybrid Meta-Strategy (Days 24-26)

### 6.1 Ensemble Decision Making

**Concept:** Run multiple algorithms in parallel, combine outputs intelligently.

```python
class EnsembleOptimizer:
    """Combine multiple strategies for robust decisions"""
    
    def __init__(self, data_warehouse, game_state):
        self.lp_optimizer = NetworkFlowOptimizer(data_warehouse, game_state)
        self.heuristic_optimizer = HeuristicOptimizer(data_warehouse, game_state)
        self.rl_agent = load_trained_rl_model("kit_management_ppo")
        
    def decide(self, hour_response):
        """Generate decisions from all models and combine"""
        
        # Get decisions from each model
        lp_decisions = self.lp_optimizer.solve_and_extract_decisions()
        heuristic_decisions = self.heuristic_optimizer.generate_decisions()
        rl_decisions = self.rl_agent.predict(self._get_observation())
        
        # Voting or weighted average
        final_decisions = self._combine_decisions(
            [lp_decisions, heuristic_decisions, rl_decisions],
            weights=[0.5, 0.2, 0.3]  # Trust LP most, RL as refinement
        )
        
        return final_decisions
    
    def _combine_decisions(self, decisions_list, weights):
        """Weighted averaging of continuous decisions"""
        
        combined = {'flightLoads': [], 'kitPurchasingOrders': {...}}
        
        # For each flight, average the load recommendations
        all_flight_ids = set()
        for dec in decisions_list:
            all_flight_ids.update([fl['flightId'] for fl in dec['flightLoads']])
        
        for flight_id in all_flight_ids:
            weighted_loads = {kt: 0 for kt in ['first', 'business', 'premiumEconomy', 'economy']}
            
            for i, dec in enumerate(decisions_list):
                flight_load = next((fl for fl in dec['flightLoads'] if fl['flightId'] == flight_id), None)
                if flight_load:
                    for kt in weighted_loads.keys():
                        weighted_loads[kt] += weights[i] * flight_load['loadedKits'][kt]
            
            combined['flightLoads'].append({
                'flightId': flight_id,
                'loadedKits': {kt: int(v) for kt, v in weighted_loads.items()}
            })
        
        # Similar for purchases
        for kt in ['first', 'business', 'premiumEconomy', 'economy']:
            combined['kitPurchasingOrders'][kt] = int(sum(
                weights[i] * dec['kitPurchasingOrders'][kt]
                for i, dec in enumerate(decisions_list)
            ))
        
        return combined
```

---

## Phase 7: End-Game Strategy (Days 27-28)

### 7.1 Terminal State Optimization

**Objective:** Minimize end-game penalties in final 72 hours.

**End-Game Penalties (from code analysis):**
1. **Remaining stock:** 0.0013 × remaining_kits × kit_cost
2. **Pending processing:** 0.0013 × pending_kits × kit_cost
3. **Unfulfilled flights:** 1.5 × distance × total_kit_value

**Strategy:**

```python
def end_game_strategy(game_state, hours_remaining):
    """Special logic for final 72 hours"""
    
    if hours_remaining > 72:
        return None  # Use normal strategy
    
    decisions = {'flightLoads': [], 'kitPurchasingOrders': {...}}
    
    # STOP PURCHASING after hour 648 (lead times won't be met)
    if hours_remaining <= 72:
        decisions['kitPurchasingOrders'] = {'first': 0, 'business': 0, 
                                             'premiumEconomy': 0, 'economy': 0}
    
    # AGGRESSIVE STOCK DEPLETION
    # Load flights with maximum kits to clear inventory
    for flight in game_state.next_checked_in_flights:
        origin_stock = game_state.get_stock(flight.origin_airport)
        
        # Load up to aircraft capacity (even if exceeds passengers)
        aircraft_cap = get_aircraft_capacity(flight.aircraft_type)
        
        for kit_type in ['first', 'business', 'premiumEconomy', 'economy']:
            # Prioritize: passenger needs > stock depletion > capacity limit
            passengers = flight.passengers[kit_type]
            available = origin_stock[kit_type]
            capacity = aircraft_cap[kit_type]
            
            # Load maximum possible
            load_amount = min(available, capacity, passengers + available // 2)
            
            decisions['flightLoads'].append({
                'flightId': flight.id,
                'loadedKits': {kit_type: load_amount}
            })
    
    # EXPEDITE PROCESSING
    # Accept that some kits in processing won't complete - minimize quantity
    # (No action needed - just don't send more kits to slow-processing airports)
    
    return decisions
```

### 7.2 Final Hour Calculations

**At hour 719 (last decision):**
- Ensure all flights in hour 720 are loaded
- Accept any remaining penalties as sunk cost
- Log final cost breakdown for analysis

---

## Phase 8: Performance Tuning & Testing (Days 29-30)

### 8.1 Parameter Optimization

**Key Parameters to Tune:**
- Safety stock multipliers per airport class
- Lookahead horizon for LP solver (72h vs 168h trade-off)
- Service level thresholds (95% vs 99%)
- Purchase trigger points
- End-game transition hour (72h vs 48h vs 96h)

**Method:** Grid search with simulation

```python
def parameter_grid_search():
    """Test combinations of parameters via simulation"""
    
    parameter_grid = {
        'safety_stock_multiplier': [1.0, 1.2, 1.5, 2.0],
        'lp_horizon_hours': [72, 120, 168],
        'service_level_z': [1.65, 1.96, 2.33],
        'end_game_start_hour': [48, 72, 96],
        'purchase_trigger_ratio': [0.3, 0.4, 0.5]
    }
    
    results = []
    
    for params in itertools.product(*parameter_grid.values()):
        config = dict(zip(parameter_grid.keys(), params))
        
        # Run full simulation with these parameters
        total_cost = run_full_simulation(config)
        
        results.append((config, total_cost))
    
    # Find best configuration
    best_config, best_cost = min(results, key=lambda x: x[1])
    
    return best_config, best_cost
```

### 8.2 Stress Testing

**Test Scenarios:**
1. **Worst-case delays:** All actual distances = 110% of scheduled
2. **High demand:** All actual passengers = 110% of planned
3. **Low demand:** All actual passengers = 80% of planned
4. **Equipment changes:** Frequent aircraft type swaps
5. **Network disruptions:** Simulate missing flights

### 8.3 Performance Profiling

**Critical:** Algorithm must complete in < 1 second per hour (720 seconds total for full game).

```python
import cProfile
import pstats

def profile_algorithm():
    """Measure performance bottlenecks"""
    
    profiler = cProfile.Profile()
    profiler.enable()
    
    # Run full simulation
    optimizer = HybridOptimizer(data_warehouse)
    total_cost = run_full_simulation(optimizer)
    
    profiler.disable()
    
    # Print stats
    stats = pstats.Stats(profiler)
    stats.sort_stats('cumulative')
    stats.print_stats(20)  # Top 20 functions
    
    return total_cost
```

**Expected Bottlenecks:**
- LP solver (can take 30-60s per solve) → Reduce horizon or use warm starts
- Data structure lookups → Use hash maps, pre-compute indices
- Penalty calculations → Vectorize with NumPy

---

## Expected Cost Progression by Phase

| Phase | Strategy | Expected Total Cost | % Improvement |
|-------|----------|---------------------|---------------|
| Naive v1.0 | Exact match, basic replenishment | €800,000 - €1,200,000 | Baseline |
| Improved v1.5 | Safety buffers, demand forecast | €600,000 - €800,000 | 25-33% |
| Network Flow v3.0 | LP optimization (168h horizon) | €350,000 - €500,000 | 40-56% |
| + Heuristics v3.5 | Processing optimization, route priority | €280,000 - €400,000 | 50-65% |
| + ML Enhancement v4.0 | Demand forecasting, RL agent | €220,000 - €320,000 | 60-73% |
| + Ensemble v4.5 | Hybrid meta-strategy | €180,000 - €250,000 | 70-78% |
| + End-Game v5.0 | Terminal optimization | €150,000 - €220,000 | 73-81% |

**Target for Top 3:** Under €200,000 total cost

---

## Critical Success Factors

### 1. **Avoid Negative Stock at ALL Costs**
- Penalty factor: 5342x (catastrophic!)
- Always maintain positive stock or accept unfulfilled passenger penalty (0.003x, much smaller)

### 2. **Processing Time Management**
- Pre-calculate all airport processing times
- Send extra kits to slow-processing airports
- Monitor processing queue continuously

### 3. **Lead Time Awareness**
- First Class: 48h lead time
- Business: 36h lead time
- Premium Economy: 24h lead time
- Economy: 12h lead time
- Purchase early enough to meet demand peaks

### 4. **Aircraft Capacity Constraints**
- Never exceed aircraft kit capacity (5x distance penalty!)
- Check capacity before loading decisions
- Use smaller aircraft for low-demand routes

### 5. **End-Game Transition**
- Stop purchasing 72h before end
- Aggressively deplete stock
- Prioritize completing processing queues

---

## Implementation Checklist

### Week 1: Foundation
- [ ] Parse all CSV data files
- [ ] Build data structures (airports, flights, aircraft)
- [ ] Implement game state tracker
- [ ] Create penalty calculator (exact match to platform)
- [ ] Develop API client with error handling
- [ ] Test with naive v1.0 strategy (complete full session)

### Week 2: Optimization Core
- [ ] Implement demand forecasting
- [ ] Build network flow LP model
- [ ] Develop processing time optimizer
- [ ] Create route prioritization system
- [ ] Test with improved strategies v2.x-v3.x

### Week 3: Advanced Features
- [ ] Train ML forecasting models
- [ ] Implement RL agent (or skip if time-constrained)
- [ ] Build ensemble decision framework
- [ ] Develop end-game strategy
- [ ] Parameter tuning via grid search

### Week 4: Testing & Competition
- [ ] Stress test all scenarios
- [ ] Profile and optimize performance
- [ ] Run 10+ full simulations to validate
- [ ] Prepare presentation materials
- [ ] Competition day: deploy best configuration

---

## Risk Mitigation

### Technical Risks
1. **LP Solver Too Slow:** Use smaller horizons (72h) or heuristics as fallback
2. **API Failures:** Implement retry logic and local state recovery
3. **Memory Issues:** Stream data processing, limit horizon windows
4. **Bugs in Complex Logic:** Extensive unit tests, simulation vs platform validation

### Algorithmic Risks
1. **Local Optima:** Use ensemble approach to avoid single-strategy bias
2. **Overfitting to Training Data:** Cross-validate on different week patterns
3. **Edge Cases:** Handle zero-passenger flights, last-minute aircraft swaps
4. **Penalty Explosions:** Hard constraints to prevent negative stock

---

## Competition Day Strategy

### Pre-Competition (1 hour before)
1. Validate all data files are current versions
2. Test API connectivity and authentication
3. Run quick simulation (100 hours) to verify code works
4. Prepare fallback strategies (simple heuristic if LP fails)

### During Competition
1. Monitor session progress every 100 hours
2. Log all decisions and responses for debugging
3. Watch for unexpected penalties (indicates bug)
4. If total cost > €500,000 after 360 hours: restart with fallback strategy

### Post-Run Analysis
1. Parse all penalties by type and magnitude
2. Identify worst decisions (top 10 costly hours)
3. Calculate operational cost vs penalty ratio
4. Prepare insights for jury presentation

---

## Appendix: Key Formulas from Code Analysis

### Operational Costs (from SessionServiceImpl.java lines 455-466)

```java
// Loading + Transport Cost per Kit
kitMovement.setCost(
    update.loadedKits().first() * (
        flight.getOriginAirport().getFirstLoadingCost() + 
        flight.getActualDistance() * 
        flight.getActualAircraftType().getCostPerKgPerKm() * 
        KitType.A_FIRST_CLASS.weightKg()
    ) + 
    // ... similar for business, premium economy, economy
);

// Processing Cost (applied when kits land at destination)
processingCost = airport.getProcessingCost(kitType) * quantity;

// Purchase Cost
purchaseCost = kitType.cost() * quantity;
```

### Penalty Costs (from SessionServiceImpl.java)

```java
// Unfulfilled Passengers (lines 480-507)
penalty = UNFULFILLED_KIT_FACTOR_PER_DISTANCE * kitTypeCost * 
          flightDistance * unfulfilledPassengers;
// where UNFULFILLED_KIT_FACTOR_PER_DISTANCE = 0.003

// Flight Overload (lines 519-565)
penalty = FLIGHT_OVERLOAD_FACTOR_PER_DISTANCE * kitTypeCost * 
          flightDistance * overloadedKits;
// where FLIGHT_OVERLOAD_FACTOR_PER_DISTANCE = 5.0

// Negative Inventory (line 651)
normalizedStock = abs(negativeKits) * NEGATIVE_INVENTORY;
penalty = END_OF_GAME_REMAINING_STOCK * normalizedStock * kitTypeCost;
// where NEGATIVE_INVENTORY = 5342.0 (HUGE!)

// Over Capacity Stock (line 654)
normalizedStock = (availableKits - capacity) * OVER_CAPACITY_STOCK;
penalty = END_OF_GAME_REMAINING_STOCK * normalizedStock * kitTypeCost;
// where OVER_CAPACITY_STOCK = 777.0

// End of Game Remaining Stock (line 658)
penalty = END_OF_GAME_REMAINING_STOCK * normalizedStock * kitTypeCost * factor;
// where END_OF_GAME_REMAINING_STOCK = 0.0013

// End of Game Pending Processing (line 671)
penalty = END_OF_GAME_PENDING_KIT_PROCESSING * remainingQuantity * 
          kitTypeCost * factor;
// where END_OF_GAME_PENDING_KIT_PROCESSING = 0.0013

// End of Game Unfulfilled Flights (line 683)
penalty = END_OF_GAME_UNFULFILLED_FLIGHT_KITS * flightDistance * 
          totalKitValue * factor;
// where END_OF_GAME_UNFULFILLED_FLIGHT_KITS = 1.5

// Early End of Game (line 635)
penalty = EARLY_END_OF_GAME * missingHours;
// where EARLY_END_OF_GAME = 1000.0
```

---

## Conclusion

This comprehensive plan provides a structured path from baseline survival to optimal performance in the Rotables Challenge. The key to success is:

1. **Solid Foundation:** Perfect state tracking and penalty calculation
2. **Incremental Development:** Working solution first, optimize later
3. **Domain Knowledge:** Leverage logistics principles (safety stock, lead times, network flow)
4. **Advanced Techniques:** LP optimization for near-optimal decisions
5. **Risk Management:** Avoid catastrophic penalties (negative stock!)
6. **End-Game Focus:** Special handling for terminal state

**Estimated Total Development Time:** 25-30 days  
**Expected Final Cost:** €150,000 - €220,000  
**Competitive Positioning:** Top 3 finish

Good luck! 🚀
