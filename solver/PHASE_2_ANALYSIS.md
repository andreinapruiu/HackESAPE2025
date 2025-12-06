# Phase 2: Challenge Analysis & Implementation Plan

## Problem Discovery

### Test Results
- **Zero Loading (0 kits on all flights):** €9,965,482,969.44
  - All PASSENGER_WITHOUT_KIT penalties
  - No capacity violations
  
- **Full Loading (exact passenger demand):** €282,287,744,386.08
  - Massive INVENTORY_EXCEEDS_CAPACITY penalties
  - Kits accumulate at airports beyond capacity

### Cost Breakdown
| Scenario | Cost | Primary Penalty |
|----------|------|-----------------|
| No Loading | €9.96B | PASSENGER_WITHOUT_KIT |
| Full Loading | €282.29B | INVENTORY_EXCEEDS_CAPACITY |
| **Delta** | **€272.33B** | **Capacity violations cost 27x more!** |

## Backend Mechanics (from eval-platform analysis)

### Automatic Kit Movement Flow
```java
// SessionServiceImpl.java - updateStocks() method
1. Process all KitMovements for the hour
2. Update inventory at each airport:
   - Subtract kits loaded on departing flights
   - Add kits arriving on landed flights (after processing)
   - Add purchased kits (after lead time)
3. Check constraints:
   if (inventory.getAvailableKits() < 0) {
       penalty = NEGATIVE_INVENTORY * abs(availableKits)
   }
   if (inventory.getAvailableKits() > capacity) {
       penalty = OVER_CAPACITY_STOCK * (availableKits - capacity)
   }
```

### Key Backend Behaviors
- **Backend is authoritative** - tracks ALL inventory at ALL airports
- **No real-time query API** - we can't ask "what's the current inventory?"
- **Automatic return flights** - backend moves kits back from outstations
- **Processing delays** - kits at outstations need processing time before available
- **Capacity checks AFTER movements** - penalties applied after all movements processed

### Penalty Factors (from PenaltyFactors.java)
```java
NEGATIVE_INVENTORY = 777.0          // Per kit below zero
OVER_CAPACITY_STOCK = 777.0         // Per kit above capacity
PASSENGER_WITHOUT_KIT = 1365.0      // Per passenger without kit
OVERLOAD = 5.0                      // Per kg over aircraft capacity
```

## Why Simple Approaches Failed

### Attempt 1: Full Loading
```python
# Load exact passenger counts
loaded_kits = {
    "first": passengers.get('first', 0),
    "business": passengers.get('business', 0),
    # ...
}
```
**Result:** €282B - Kits accumulate at outstations, exceeding capacity

### Attempt 2: Return Flight Tracking
```python
# Track when kits will return to HUB
self.returning_kits[kit_type].append((return_arrival, quantity))
```
**Result:** Still €282B - Backend handles returns automatically, our tracking was redundant

### Attempt 3: Capacity-Aware Loading
```python
# Check destination capacity before loading
available_space = capacity - current_inventory
loaded_kits = min(desired, available_space)
```
**Result:** Failed - no way to know current_inventory without backend API

## The Core Optimization Problem

**Objective:** Minimize `Total Cost = Passenger Penalties + Capacity Penalties`

**Constraints:**
1. Can't query backend for real-time inventory
2. Must decide loading at CHECK_IN event (1 hour before departure)
3. Backend automatically processes all movements
4. 162 airports, 7,287 flights, 720 hours to optimize

**Trade-off:**
```
More Loading → Serve passengers (good) → Risk capacity violations (bad)
Less Loading → Avoid capacity issues (good) → Passengers without kits (bad)
```

**Penalty Economics:**
- PASSENGER_WITHOUT_KIT: €1,365 per passenger
- OVER_CAPACITY: €777 per kit over limit
- Loading 1 kit serves 1 passenger: €1,365 benefit
- If that kit causes capacity violation: €777 penalty
- **Net benefit: €588 per kit** (as long as capacity not exceeded)

**Critical Insight:** It's profitable to load kits UNLESS it causes capacity violations. Need to predict when destinations are near capacity.

## Network Characteristics (from CSV data)

### Hub (HUB1)
- Initial Stock: FC=1,659, BC=5,184, PE=2,668, EC=23,651
- Capacity: FC=18,109, BC=18,109, PE=9,818, EC=95,075
- **High capacity** - unlikely to hit limits

### Outstations (161 airports)
- Example ZHVK: Stock FC=158, BC=105, PE=135, EC=304
- Capacity: FC=445, BC=445, PE=290, EC=803
- **Low capacity** - easy to exceed
- Processing times: 4-48 hours (varies by airport and kit type)

### Flight Patterns
- Hub-and-spoke topology: HUB1 ↔ Outstations
- Each route has outbound (e.g., AB1000) and return (e.g., AB1001) flights
- Flights operate on schedules (some daily, some less frequent)
- Flight duration + processing time = total turnaround

## Phase 2 Implementation Strategy

### Step 1: Local Inventory Estimation System
Build a **shadow tracking system** that mirrors backend state:

```python
class AirportInventoryTracker:
    """Track estimated inventory at each airport"""
    
    def __init__(self):
        self.inventory = {}  # {airport_id: {KitType: quantity}}
        self.in_transit = []  # [(arrival_hour, airport_id, kit_type, quantity)]
        self.processing = []  # [(ready_hour, airport_id, kit_type, quantity)]
    
    def simulate_flight_load(self, flight, loaded_kits):
        """Remove kits from origin, schedule arrival at destination"""
        # Origin: immediate reduction
        origin_id = flight.origin_airport_id
        for kit_type, qty in loaded_kits.items():
            self.inventory[origin_id][kit_type] -= qty
        
        # Destination: schedule arrival after flight + processing
        dest_id = flight.destination_airport_id
        arrival_hour = flight.actual_arrival_hour_absolute
        dest_airport = self.airports[dest_id]
        
        for kit_type, qty in loaded_kits.items():
            processing_time = dest_airport.get_processing_time(kit_type)
            ready_hour = arrival_hour + processing_time
            self.processing.append((ready_hour, dest_id, kit_type, qty))
    
    def update_for_hour(self, current_hour):
        """Process arrivals and completions for this hour"""
        # Move in-transit to processing
        # Move completed processing to inventory
        # Clean up old entries
```

### Step 2: Capacity-Aware Loading Decision
```python
def decide_loading(self, flight, passengers):
    """Decide how many kits to load based on estimated capacity"""
    
    dest_id = flight.destination_airport_id
    dest_airport = self.airports[dest_id]
    
    loaded_kits = {}
    for kit_type in KitType:
        desired = passengers.get(kit_type_to_api_field[kit_type], 0)
        
        # Estimate destination inventory after this flight
        current = self.inventory_tracker.get_inventory(dest_id, kit_type)
        capacity = dest_airport.get_capacity(kit_type)
        
        # Calculate safety margin (e.g., 80% of capacity)
        safe_capacity = capacity * 0.8
        available_space = max(0, safe_capacity - current)
        
        # Load min of desired and available space
        actual_load = min(desired, available_space)
        loaded_kits[kit_type] = actual_load
        
        if actual_load < desired:
            # Accept some PASSENGER_WITHOUT_KIT penalties
            # to avoid larger CAPACITY_EXCEEDED penalties
            logger.info(f"Reduced loading: {desired}→{actual_load} to avoid capacity")
    
    return loaded_kits
```

### Step 3: Validation & Iteration
1. **Test reduced loading:** Should reduce capacity penalties significantly
2. **Tune safety margin:** Find optimal capacity threshold (80%? 90%?)
3. **Handle edge cases:** First flights, low-frequency routes, processing backlogs
4. **Measure improvement:** Target cost < €50B (5x better than full loading)

## Expected Outcomes

### Optimistic Target
- Serve ~70-80% of passengers (€3-4B in passenger penalties)
- Avoid most capacity violations (€5-10B in capacity penalties)
- **Total Cost: €8-14B** (20x improvement from €282B)

### Realistic Target
- Serve ~60-70% of passengers (€4-5B in passenger penalties)
- Reduce capacity violations by 80% (€50B in capacity penalties)
- **Total Cost: €54-55B** (5x improvement)

### Conservative Target
- Better than zero loading (€9.96B)
- Better than full loading (€282B)
- **Total Cost: €20-50B** (5-14x improvement)

## Implementation Checklist

- [ ] Create `AirportInventoryTracker` class in new module
- [ ] Initialize with airport capacities and initial stocks
- [ ] Implement `simulate_flight_load()` for movement tracking
- [ ] Implement `update_for_hour()` for time progression
- [ ] Integrate tracker into `NaiveAPIStrategy`
- [ ] Modify `_generate_flight_loads()` to use capacity-aware logic
- [ ] Add logging for capacity decisions
- [ ] Test with full run (720 hours)
- [ ] Analyze results and tune parameters
- [ ] Document findings and iterate

## Next Steps

1. **Implement Phase 2.2:** Local Inventory Estimation
2. **Implement Phase 2.3:** Smart Loading Strategy
3. **Test and Validate:** Run full simulation
4. **Iterate:** Tune parameters based on results
5. **Phase 3:** Add demand forecasting and smart purchasing

## References

- Backend Code: `eval-platform/src/main/java/com/sap/hackaton2025/service/impl/SessionServiceImpl.java`
- Challenge Docs: `html/index.html`
- Data Files: `eval-platform/src/main/resources/liquibase/data/*.csv`
- Current Strategy: `solver/src/naive_api_strategy.py`
