# 🛫 ROTABLES CHALLENGE - COMPLETE GUIDE

## 📖 Table of Contents
1. [Challenge Overview](#challenge-overview)
2. [The Problem](#the-problem)
3. [Network Architecture](#network-architecture)
4. [Kit Types & Costs](#kit-types--costs)
5. [API Reference](#api-reference)
6. [Cost Formulas](#cost-formulas)
7. [Penalty System](#penalty-system)
8. [Game Mechanics](#game-mechanics)
9. [Data Files](#data-files)
10. [Strategy Guide](#strategy-guide)
11. [Getting Started](#getting-started)

---

## 🎯 Challenge Overview

**Goal:** Minimize total costs while managing passenger kits (rotables) across an airline hub-and-spoke network over 720 rounds (30 days × 24 hours).

### Key Statistics
- **160+ airports** in the network
- **447 flights** in the schedule
- **4 cabin classes** (First, Business, Premium Economy, Economy)
- **720 game rounds** (30 days × 24 hours)
- **1 central hub (HUB1)** + multiple outstation airports

---

## 🧩 The Problem

### What You Must Decide Each Round (Hour):

1. **How many kits to load on each flight** (per class)
2. **How many kits to purchase** for HUB1 replenishment (optional)
3. **How to balance costs** between operations and penalties

### What the Backend Calculates Automatically:

- Kit deliveries and arrivals at destinations
- All types of penalties
- Costs for movements and purchases
- Cumulative cost for entire session
- Airport stock updates
- Flight statuses (SCHEDULED, CHECKED_IN, LANDED)

---

## 🌐 Network Architecture

### Hub-and-Spoke Model

```
         Outstation A1
              ↑↓
         Outstation A2
              ↑↓
    HUB1 ←→ Central Hub ←→ Outstation A3
              ↑↓
         Outstation A4
              ↑↓
         Outstation A5
```

### HUB1 (Central Hub)
- **Only location** where you can purchase new kits
- Fastest processing times (1-6 hours)
- Lowest loading costs
- Massive storage capacity
- All aircraft are based here

### Outstations (Satellite Airports)
- **Limited support** - only turnaround operations
- **Much longer processing times** (4-45 hours) ⚠️
- Higher loading costs
- Limited storage capacity
- **Cannot purchase kits here**

### ⚠️ CRITICAL INSIGHT:
**Outstation processing times (4-45h) are MUCH LONGER than turnaround times (2-6h)**
→ Kits from outbound flight CANNOT be used for return flight!

---

## 📦 Kit Types & Costs

```
Class              Weight (kg)  Cost ($)  Lead Time (hours)
─────────────────────────────────────────────────────────────
FIRST_CLASS        5.0          200       48
BUSINESS           3.0          150       36
PREMIUM_ECONOMY    2.5          100       24
ECONOMY            1.5          50        12
```

### Important Notes:
- Lead time = time until purchased kits arrive at HUB1
- Kits are **identical** across all aircraft types
- Each class has **dedicated storage** on aircraft (no sharing)

---

## 🔌 API Reference

### Base URL
```
http://localhost:8080/api/v1
```

### Authentication
All endpoints require `API-KEY` header:
```
API-KEY: <your-uuid-from-teams.csv>
```

---

### 1. Start Session

**Endpoint:** `POST /session/start`

**Headers:**
```
API-KEY: <your-api-key>
```

**Response:**
```json
"550e8400-e29b-41d4-a716-446655440000"
```
(Returns session UUID as plain string)

**Notes:**
- Only one active session per API key
- Must end previous session before starting new one

---

### 2. Play Round

**Endpoint:** `POST /play/round`

**Headers:**
```
API-KEY: <your-api-key>
SESSION-ID: <session-uuid>
Content-Type: application/json
```

**Request Body:**
```json
{
  "day": 0,
  "hour": 0,
  "flightLoads": [
    {
      "flightId": "uuid-string",
      "loadedKits": {
        "first": 10,
        "business": 50,
        "premiumEconomy": 20,
        "economy": 150
      }
    }
  ],
  "kitPurchasingOrders": {
    "first": 100,
    "business": 200,
    "premiumEconomy": 150,
    "economy": 500
  }
}
```

**Response:**
```json
{
  "day": 0,
  "hour": 0,
  "flightUpdates": [
    {
      "eventType": "SCHEDULED",
      "flightNumber": "LH123",
      "flightId": "uuid",
      "originAirport": "HUB1",
      "destinationAirport": "A1",
      "departure": {"day": 0, "hour": 15},
      "arrival": {"day": 0, "hour": 20},
      "passengers": {
        "first": 2,
        "business": 10,
        "premiumEconomy": 20,
        "economy": 100
      },
      "aircraftType": "A320"
    }
  ],
  "penalties": [
    {
      "code": "NEGATIVE_INVENTORY",
      "flightId": null,
      "flightNumber": null,
      "issuedDay": 0,
      "issuedHour": 0,
      "penalty": 500.0,
      "reason": "Negative inventory for airport A1 kit type ECONOMY"
    }
  ],
  "totalCost": 12345.67
}
```

**Flight Event Types:**
- `SCHEDULED` (24h before) - Planned data
- `CHECKED_IN` (1h before) - Actual passengers & aircraft
- `LANDED` (at arrival) - Final confirmation

**Important Notes:**
- Must play rounds **sequentially** (0:0 → 0:1 → 0:2...)
- Can modify flight loads **multiple times** until takeoff
- Backend validates day/hour matches expected time

---

### 3. End Session

**Endpoint:** `POST /session/end`

**Headers:**
```
API-KEY: <your-api-key>
```

**Response:**
```json
{
  "day": 29,
  "hour": 23,
  "flightUpdates": null,
  "penalties": [...],
  "totalCost": 567890.12
}
```

**Notes:**
- Applies end-of-game penalties
- **Early stop** multiplies all end-game penalties by 1000!

---

## 💰 Cost Formulas

### 1. Kit Loading Cost
```
LoadingCost = Σ(kits × airport.loadingCost_per_class)
```

**Example:**
- Loading 100 Economy kits at HUB1 (cost: 0.5 per kit)
- Cost = 100 × 0.5 = **$50**

---

### 2. Kit Movement Cost (Transport)
```
MovementCost = actualDistance × aircraftType.costPerKgPerKm × Σ(kits × kitWeight)
```

**Example:**
- Flight: 3000 km
- Aircraft: 0.08 $/kg/km
- Kits: 100 Economy (1.5 kg each)
- Cost = 3000 × 0.08 × (100 × 1.5) = **$36,000**

---

### 3. Kit Processing Cost
```
ProcessingCost = Σ(kits × destinationAirport.processingCost_per_class)
```

**Applied when kits arrive at destination after processing time**

---

### 4. Kit Purchasing Cost
```
PurchaseCost = Σ(kits × kitCost)
```

**Example:**
- Buying 100 Economy kits (cost: $50 each)
- Cost = 100 × 50 = **$5,000**

---

## ⚠️ Penalty System

### Penalty Factors (Constants)
```
NEGATIVE_INVENTORY              = 5342.0   (MOST EXPENSIVE!)
INCORRECT_FLIGHT_LOAD           = 5000.0
OVER_CAPACITY_STOCK             = 777.0
FLIGHT_OVERLOAD_PER_DISTANCE    = 5.0
UNFULFILLED_KIT_PER_DISTANCE    = 0.003
END_OF_GAME_REMAINING_STOCK     = 0.0013
END_OF_GAME_PENDING_PROCESSING  = 0.0013
END_OF_GAME_UNFULFILLED_FLIGHTS = 1.5
EARLY_END_OF_GAME               = 1000.0   (MULTIPLIER!)
```

---

### In-Game Penalties

#### 1. Negative Inventory (💀 AVOID AT ALL COSTS!)
```
Penalty = 5342 × |negative_kits|
```

**Example:**
- Airport A1 has -10 Economy kits
- Penalty = 5342 × 10 = **$53,420**

**When it happens:**
- Airport stock goes below 0
- You tried to load more kits than available

---

#### 2. Overstock
```
Penalty = 777 × (kits_over_capacity)
```

**Example:**
- Capacity: 1000 kits, Current: 1050 kits
- Penalty = 777 × 50 = **$38,850**

---

#### 3. Flight Overload
```
Penalty = 5.0 × kitCost × actualDistance × excess_kits
```

**Example:**
- Loaded 150 Economy kits, capacity: 130
- Distance: 3000 km, Kit cost: $50
- Penalty = 5.0 × 50 × 3000 × 20 = **$15,000,000**

---

#### 4. Unfulfilled Passengers
```
Penalty = 0.003 × kitCost × actualDistance × passengers_without_kits
```

**Example:**
- 10 Economy passengers without kits
- Distance: 3000 km, Kit cost: $50
- Penalty = 0.003 × 50 × 3000 × 10 = **$4,500**

---

#### 5. Invalid Flight Reference
```
Penalty = 5000 per invalid flight
```

**When it happens:**
- Flight ID doesn't exist
- Flight already departed
- Wrong timing

---

### End-of-Game Penalties

#### 1. Remaining Stock
```
normalizedStock = availableKits
if (availableKits < 0):
    normalizedStock = |availableKits| × 5342
if (availableKits > capacity):
    normalizedStock = (availableKits - capacity) × 777

Penalty = 0.0013 × normalizedStock × kitCost × factor
```

---

#### 2. Pending Kit Processing
```
Penalty = 0.0013 × pending_kits × kitCost × factor
```

---

#### 3. Unfulfilled Flight Kits
```
Penalty = 1.5 × distance × factor × 
          Σ(passengers × kitCost × kitWeight per class)
```

---

#### 4. Early Stop Multiplier
```
missingHours = 720 - currentHour
if (missingHours < 24):
    missingHours = missingHours × 10

factor = 1000 × missingHours
```

**Example:**
- Stop at hour 700 (20 hours early)
- Factor = 1000 × 20 = **20,000**
- ALL end-game penalties × 20,000!

**⚠️ NEVER STOP EARLY!**

---

## 🎮 Game Mechanics

### Round Execution (8 Steps)

Each round (hour) executes in this order:

1. **Validate Session** - Check active session and correct timing
2. **Apply Kit Loads** - Create movements, deduct from origin stock
3. **Apply Purchases** - Process HUB1 orders with lead-time
4. **Process Movements** - Execute scheduled arrivals/departures
5. **Check Boundaries** - Apply negative/overstock penalties
6. **Create Landing Movements** - Schedule processing queue
7. **Advance Time** - Move to next hour
8. **Update Flight Status** - Update SCHEDULED→CHECKED_IN→LANDED

---

### Critical Timing Rules

#### Flight Information Timeline:
```
Hour -24: SCHEDULED event (planned data)
    ↓
Hour -1:  CHECKED_IN event (actual passengers & aircraft)
    ↓
Hour 0:   Flight departs
    ↓
Hour +X:  LANDED event (at destination)
```

#### Kit Processing Timeline:
```
Flight lands at A1
    ↓
Kits enter processing queue
    ↓
Wait: processing_time hours (4-45h at outstations!)
    ↓
Kits available in A1 stock
```

**Example:**
```
Hour 0:  Flight HUB1→A1 departs (100 Economy kits)
Hour 5:  Flight lands at A1
Hour 5:  Kits enter processing (processing time: 4h)
Hour 9:  Kits available in A1 stock
```

**⚠️ CRITICAL:**
If return flight is at Hour 7, those kits WON'T be ready!

---

### Stock Management Rules

1. **Stock updates** happen when kit movements are processed
2. **Movements are negative** when loading (deduct from stock)
3. **Movements are positive** when arriving/processing complete
4. **Penalties apply** if stock goes negative or over capacity
5. **Processing time** varies by airport and kit class

---

## 📊 Data Files

### Location
```
eval-platform/src/main/resources/liquibase/data/
```

### 1. airports_with_stocks.csv

**Columns:**
```
code                  - Airport code (HUB1, A1, A2, ...)
name                  - Airport name
first_processing_time - Hours to process First Class kits
business_processing_time
premium_economy_processing_time
economy_processing_time
first_processing_cost - Cost per kit
business_processing_cost
premium_economy_processing_cost
economy_processing_cost
first_loading_cost    - Cost per kit
business_loading_cost
premium_economy_loading_cost
economy_loading_cost
initial_fc_stock     - Starting inventory
initial_bc_stock
initial_pe_stock
initial_ec_stock
capacity_fc          - Maximum storage
capacity_bc
capacity_pe
capacity_ec
```

**Example - HUB1:**
```
Code: HUB1
Processing Time: FC=6h, BC=4h, PE=2h, EC=1h
Processing Cost:  FC=8.0, BC=6.0, PE=2.0, EC=1.0
Loading Cost:     FC=1.0, BC=0.75, PE=0.5, EC=0.5
Initial Stock:    FC=1659, BC=5184, PE=2668, EC=23651
Capacity:         FC=18109, BC=18109, PE=9818, EC=95075
```

**Example - Outstation ZHVK:**
```
Code: ZHVK
Processing Time: FC=45h, BC=28h, PE=12h, EC=4h  ⚠️ MUCH LONGER!
Processing Cost:  FC=6.67, BC=5.23, PE=3.55, EC=1.65
Loading Cost:     FC=3.3, BC=2.09, PE=2.01, EC=1.38
Initial Stock:    FC=158, BC=105, PE=135, EC=304
Capacity:         FC=445, BC=445, PE=290, EC=803
```

---

### 2. aircraft_types.csv

**Columns:**
```
type_code                       - Aircraft model code
first_class_seats              - Passenger capacity per class
business_seats
premium_economy_seats
economy_seats
cost_per_kg_per_km             - Fuel cost (for movement cost)
first_class_kits_capacity      - Kit capacity per class
business_kits_capacity
premium_economy_kits_capacity
economy_kits_capacity
```

**Example:**
```
Type: OJF294
Seats:        FC=13, BC=67, PE=31, EC=335
Cost/kg/km:   0.08
Kit Capacity: FC=18, BC=105, PE=44, EC=781
```

---

### 3. flight_plan.csv

**Columns:**
```
depart_code          - Origin airport
arrival_code         - Destination airport
scheduled_hour       - Departure hour (0-23)
scheduled_arrival_hour - Arrival hour
arrival_next_day     - 0 or 1 (crosses midnight?)
distance_km          - Flight distance
Mon, Tue, Wed, Thu, Fri, Sat, Sun - Operating days (0 or 1)
```

**Example:**
```
Route: HUB1 → ZHVK → HUB1
Depart: 15:00, Arrive: 20:00 (same day)
Return: 21:00, Arrive: 02:00 (next day)
Distance: 3664 km
Days: Monday only
```

---

### 4. teams.csv

**Columns:**
```
id        - Team UUID
color     - Display color
name      - Team name
api_key   - Your authentication key
```

**Example:**
```
Testing-1: 43b9ab90-b593-404c-a8d8-aaa074e181e1
Testing-2: 03d6a5d1-afba-41ca-9343-376de757550b
```

**Use any API key from this file for local testing!**

---

## 💡 Strategy Guide

### Basic Strategy (Starter Algorithm)

```python
for each flight in next 24 hours:
    # 1. Load exactly enough kits for passengers
    for each class:
        kits_to_load = passengers[class]
    
    # 2. Add buffer for safety (5-10%)
    kits_to_load = passengers[class] * 1.05
    
    # 3. Check if origin airport has enough stock
    if stock < kits_to_load:
        # Purchase at HUB1 if it's the origin
        # Or send kits on earlier flight if outstation
```

---

### Intermediate Strategy

**Key Optimizations:**

1. **Predictive Stocking**
   - Analyze flight schedule for next 48-72 hours
   - Pre-position kits at outstations before demand spikes
   
2. **Processing Time Management**
   - Account for processing delays at outstations
   - Send extra kits knowing return flight kits won't be ready
   
3. **Cost Minimization**
   - Balance: cheap transport of many kits vs. risk of stockouts
   - Consider: distance × fuel cost vs. penalty costs
   
4. **Capacity Planning**
   - Don't exceed aircraft kit capacity
   - Don't exceed airport storage capacity
   - Monitor daily intake/outtake limits

---

### Advanced Strategy

**Techniques:**

1. **Linear Programming (LP)**
   - Objective: Minimize total cost
   - Constraints: Capacity, stock levels, processing times
   - Variables: Kits per flight, purchase quantities

2. **Genetic Algorithms (GA)**
   - Evolve solutions over generations
   - Fitness function: Total cost (lower = better)
   - Crossover: Combine successful strategies

3. **Reinforcement Learning (RL)**
   - State: Current stocks, pending flights, hour
   - Actions: Kit loading decisions, purchases
   - Reward: Negative cost (minimize)
   
4. **Predictive Analytics**
   - Learn patterns: Busy routes, quiet periods
   - Adjust buffer sizes dynamically
   - Optimize restock timing

---

### Critical Insights

#### 1. **Processing Time Trap**
```
Outbound flight: 100 kits used
Processing time: 28 hours
Return flight: 6 hours later
Result: Those 100 kits NOT available!

Solution: Send extra kits proactively
```

#### 2. **Cost Hierarchy**
```
Negative inventory (5342) >>> Everything else

Priority 1: Never go negative
Priority 2: Avoid flight overload
Priority 3: Minimize movement costs
Priority 4: Minimize unfulfilled passengers
```

#### 3. **HUB1 Advantages**
```
✓ Only place to buy kits
✓ Fastest processing (1-6h)
✓ Cheapest loading costs
✓ Huge capacity
✓ All flights originate/return here

Strategy: Use HUB1 as buffer/warehouse
```

#### 4. **Outstation Challenges**
```
✗ Cannot buy kits
✗ Slow processing (4-45h)
✗ Higher costs
✗ Limited capacity

Strategy: Pre-emptive stocking
```

---

## 🚀 Getting Started

### Prerequisites

1. **Java 25** installed
2. **Maven** installed
3. **IntelliJ IDEA** (or any IDE)
4. **Python 3.8+** (for client algorithm)

---

### Setup Backend

1. **Clone and navigate:**
   ```bash
   cd eval-platform
   ```

2. **Run with local profile:**
   ```bash
   mvn spring-boot:run -Dspring.profiles.active=local
   ```

3. **Verify it's running:**
   - Open browser: http://localhost:8080/swagger-ui/index.html
   - You should see the API documentation

4. **Get your API key:**
   - Open: `src/main/resources/liquibase/data/teams.csv`
   - Copy any `api_key` value (e.g., Testing-1's key)

---

### Test with Bruno/Postman

1. **Start Session:**
   ```
   POST http://localhost:8080/api/v1/session/start
   Header: API-KEY: <your-key>
   ```

2. **Play Round:**
   ```
   POST http://localhost:8080/api/v1/play/round
   Headers:
     API-KEY: <your-key>
     SESSION-ID: <session-uuid>
     Content-Type: application/json
   Body: {"day": 0, "hour": 0, "flightLoads": [], "kitPurchasingOrders": {...}}
   ```

3. **End Session:**
   ```
   POST http://localhost:8080/api/v1/session/end
   Header: API-KEY: <your-key>
   ```

---

### Development Checklist

- [ ] ✅ Setup Environment (Java 25, Maven, IDE)
- [ ] ✅ Explore API (Swagger, test endpoints)
- [ ] ✅ Understand Data (read CSV files, network structure)
- [ ] 📝 Build Simple Prototype (load kits = passengers)
- [ ] 🧪 Test & Iterate (run sessions, analyze costs)
- [ ] 🚀 Optimize (LP, GA, RL algorithms)
- [ ] ⚠️ Handle Edge Cases (delays, capacity limits)
- [ ] 📊 Add Monitoring (logging, debugging)

---

## 📝 Useful Commands

### Backend Management

```bash
# Start backend
mvn spring-boot:run -Dspring.profiles.active=local

# Clean and rebuild
mvn clean install

# Check if running
curl http://localhost:8080/swagger-ui/index.html
```

### Data Exploration

```bash
# View airports
cat src/main/resources/liquibase/data/airports_with_stocks.csv | head -5

# View flights
cat src/main/resources/liquibase/data/flight_plan.csv | head -10

# View aircraft
cat src/main/resources/liquibase/data/aircraft_types.csv | head -5
```

---

## 🐛 Troubleshooting

### Issue: 401 Unauthorized
**Solution:** Check API-KEY header is correct UUID from teams.csv

### Issue: 400 Bad Request - Type mismatch
**Solution:** Add SESSION-ID header to Play Round request

### Issue: No data loaded (0 flights cached)
**Solution:** Run with `-Dspring.profiles.active=local` profile

### Issue: Parse error in Bruno
**Not actually an error!** Start Session returns plain UUID string, not JSON.

### Issue: Session already exists
**Solution:** End current session first, or use different API key

---

## 📚 Additional Resources

- **OpenAPI Spec:** http://localhost:8080/api-docs
- **Swagger UI:** http://localhost:8080/swagger-ui/index.html
- **Source Code:** eval-platform/src/main/java/com/sap/hackaton2025/
- **Penalty Factors:** PenaltyFactors.java
- **Kit Types:** KitType.java model

---

## 🏆 Scoring

**Stage 1 (50%):** Lowest total cost in automated ranking
**Stage 2 (50%):** Interview (solution quality, understanding, innovation)

**Final Score = Stage 1 Points + Stage 2 Points**

**Tiebreaker:**
1. Higher Stage 2 score
2. Lower Stage 1 total cost
3. Innovation & Creativity criteria
4. Jury decision

---

## ⚡ Quick Reference

### Most Important Numbers
```
Negative Inventory Penalty: 5342 (AVOID!)
Early Stop Multiplier: 1000 × hours_missing
Kit Costs: $50 (Economy) to $200 (First)
Kit Weights: 1.5kg (Economy) to 5kg (First)
Lead Times: 12h (Economy) to 48h (First)
Game Duration: 720 hours (30 days)
```

### API Workflow
```
1. POST /session/start → get session_id
2. Loop 720 times:
     POST /play/round with decisions
3. POST /session/end → get final score
```

### Decision Template
```json
{
  "day": <current_day>,
  "hour": <current_hour>,
  "flightLoads": [<kit loading decisions>],
  "kitPurchasingOrders": {<purchase orders for HUB1>}
}
```

---

**Good luck with your algorithm! 🚀**


