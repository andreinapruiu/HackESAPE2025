# HackITAll 2025 - Rotables Challenge: Hub-Spoke Logistics Optimization

## 🎯 Project Overview

This is an **airline logistics optimization challenge** where teams must minimize operational costs by efficiently managing passenger kits (rotables) across a **hub-and-spoke network**. The system simulates 30 days (720 hours) of airline operations where you must:

- **Load kits** onto flights for each passenger class
- **Purchase new kits** to replenish stock at HUB1
- **Minimize total costs** (operational + penalties)
- **Avoid penalties** for unfulfilled passengers, negative stock, or overloaded flights

---

## 📐 System Architecture

### **Core Entities**

| Entity | Description |
|--------|-------------|
| **Airport** | Hub (HUB1) or outstation with storage capacity, processing costs/times, loading costs |
| **Flight** | Connection between HUB↔Outstation with scheduled/actual times, passengers, aircraft |
| **Kit Type** | 4 classes: FIRST (200€, 5kg, 48h lead), BUSINESS (150€, 3kg, 36h), PREMIUM_ECONOMY (100€, 2.5kg, 24h), ECONOMY (50€, 1.5kg, 12h) |
| **Aircraft Type** | Defines kit capacity and cost per kg per km for each class |
| **Evaluation Session** | Player's game session tracking current time, total cost, and state |

### **Key Concepts**

- **Hub-Spoke Network**: Central HUB1 connects to 160+ outstations. All flights are HUB↔Outstation or return.
- **Turn-Based Simulation**: Progresses hour-by-hour. Each round = 1 simulated hour.
- **Flight Events**: 
  - `SCHEDULED` (24h before departure) - planned data
  - `CHECKED_IN` (1h before departure) - actual passengers/aircraft confirmed
  - `LANDED` (on arrival) - kits used, processing begins
- **Kit Processing**: Used kits need processing time before becoming available again at destination airport.

---

## 🔄 Game Mechanics Flow

### **Each Round (Hour) Execution Steps:**

1. **Validate Session/Time** - Verify session is active and time matches
2. **Apply Flight Loads** - Create kit movements from your loading decisions (deduct from origin stock)
3. **Process Purchasing Orders** - Add new kits to HUB1 (delivery after lead time)
4. **Execute Kit Movements** - Apply all scheduled movements for current hour
5. **Check Stock Boundaries** - Apply penalties for negative/over-capacity stock
6. **Create Processing Movements** - Queue landed kits for processing (return to stock after processing time)
7. **Advance Time** - Move to next hour
8. **Prepare Flight Updates** - Return next round's flight events

---

## 🌐 API Endpoints

### **Base URL:** `http://127.0.0.1:8080/api/v1/`

### **Authentication:** All requests require header `API-KEY: <your-uuid>`

| Method | Endpoint | Description | Request | Response |
|--------|----------|-------------|---------|----------|
| **POST** | `/session/start` | Start new session | Headers only | `UUID` (session ID) |
| **POST** | `/session/end` | End active session | Headers only | `HourResponseDto` (final state) |
| **POST** | `/play/round` | Submit round actions | `HourRequestDto` | `HourResponseDto` |

### **POST /play/round - Main Gameplay Endpoint**

**Request: `HourRequestDto`**
```json
{
  "day": 0,
  "hour": 0,
  "flightLoads": [
    {
      "flightId": "uuid-of-flight",
      "loadedKits": {
        "first": 2,
        "business": 10,
        "premiumEconomy": 20,
        "economy": 100
      }
    }
  ],
  "kitPurchasingOrders": {
    "first": 10,
    "business": 50,
    "premiumEconomy": 100,
    "economy": 500
  }
}
```

**Response: `HourResponseDto`**
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
      "departure": { "day": 0, "hour": 2 },
      "arrival": { "day": 0, "hour": 4 },
      "passengers": { "first": 2, "business": 10, "premiumEconomy": 20, "economy": 100 },
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

---

## 💰 Cost Structure

### **Operational Costs**

1. **Kit Loading Cost**: `airport.loadingCost` per kit per class
2. **Kit Movement Cost**: `kitQuantity × distance × aircraftType.costPerKgPerKm × kitType.weight`
3. **Kit Processing Cost**: `airport.processingCost × kitQuantity` (applied when used kits are cleaned)
4. **Kit Purchasing Cost**: `kitType.cost × quantity` (base purchase price)

### **Penalties (from `PenaltyFactors.java`)**

| Penalty Type | Factor | Formula |
|--------------|--------|---------|
| **Flight Overload** | 5.0 | `factor × kitCost × distance × overloadedKits` |
| **Unfulfilled Passengers** | 0.003 | `factor × kitCost × distance × unfulfilledPassengers` |
| **Incorrect Flight Load** | 5000 | Fixed penalty per invalid submission |
| **Negative Inventory** | 5342 | `factor × abs(negativeKits)` |
| **Over Capacity Stock** | 777 | `factor × excessKits` |
| **End-Game Remaining Stock** | 0.0013 | `factor × remainingKits × kitCost` |
| **End-Game Pending Processing** | 0.0013 | `factor × pendingKits × kitCost` |
| **End-Game Unfulfilled Flights** | 1.5 | `factor × flightDistance × totalKitValue` |
| **Early End of Game** | 1000 × missingHours | Penalty for stopping before 720 hours |

---

## 🧠 Algorithm Development Plan

### **Phase 1: Basic Working Solution (Baseline)**

**Goal:** Create a simple algorithm that completes a full session without major penalties.

#### **v1.0 - Naive Exact Match**
- **Strategy**: Load exactly the number of kits equal to passengers for each flight
- **Purchase Strategy**: Buy kits whenever HUB1 stock drops below 50% capacity
- **Why**: Establishes baseline, ensures no unfulfilled passengers
- **Expected Issues**: High costs, doesn't account for returning kits, ignores processing time

#### **v1.1 - Add Safety Buffer**
- **Improvement**: Load `passengers + 5%` extra kits per flight
- **Purchase Trigger**: Buy when stock < 30% capacity
- **Why**: Handles minor variations, prevents stockouts
- **New Issues**: Higher transport costs, excess stock penalties

### **Phase 2: Optimize Kit Flow (Intermediate)**

#### **v2.0 - Account for Return Kits**
- **Track**: Monitor kits in-flight and in-processing queues
- **Calculate**: `effective_stock = current_stock + processing_kits + returning_kits`
- **Purchase Logic**: Only buy when `effective_stock < demand_forecast_7days`
- **Expected Gain**: 20-30% cost reduction from fewer purchases

#### **v2.1 - Processing Time Awareness**
- **Track Flight Pairs**: Monitor HUB→OUT and OUT→HUB flight schedules
- **Calculate Turnaround**: Ensure sufficient gap between flights for kit processing
- **Preposition Kits**: Send extra kits to outstations with tight turnarounds
- **Expected Gain**: 10-15% fewer penalties from stock availability

#### **v2.2 - Demand Forecasting**
- **Analyze Patterns**: Parse flight schedule to predict 24h/72h demand per airport per class
- **Purchase Optimization**: Buy in bulk considering lead times (12-48h)
- **Stock Target**: `min_stock = max(processing_time_demand, safety_buffer)`
- **Expected Gain**: 15-20% reduction in purchasing costs

### **Phase 3: Advanced Optimization (Advanced)**

#### **v3.0 - Cost-Aware Loading**
- **Flight Prioritization**: Load based on `cost_per_kit = loading_cost + (distance × weight × cost_per_kg_km)`
- **Optimization**: For outstations with multiple flights, choose cheaper flights for restocking
- **Dynamic Buffer**: Adjust safety margins based on `penalty_risk vs transport_cost` trade-off
- **Expected Gain**: 10-15% from smarter flight selection

#### **v3.1 - Multi-Airport Balancing**
- **Network View**: Consider all outstations holistically
- **Rebalancing**: Use flights strategically to move kits between locations (via HUB)
- **Priority System**: Focus on high-traffic, high-penalty-risk airports
- **Expected Gain**: 5-10% from network efficiency

#### **v3.2 - Predictive Delays Handling**
- **Pattern Recognition**: Detect flights with historical delays (if data available)
- **Proactive Loading**: Load extra kits on delay-prone routes
- **Buffer Allocation**: Maintain emergency stock at high-variance outstations
- **Expected Gain**: 5-10% penalty avoidance

### **Phase 4: Machine Learning / Advanced Algorithms (Expert)**

#### **v4.0 - Linear Programming (LP)**
- **Model**: Formulate as LP problem
  - **Variables**: Kit loads per flight, purchase quantities per hour
  - **Objective**: Minimize total cost
  - **Constraints**: Stock capacity, aircraft capacity, non-negativity, flow balance
- **Solver**: Use library (OR-Tools, PuLP, Gurobi)
- **Horizon**: Optimize over rolling 24h window
- **Expected Gain**: 10-20% from mathematical optimum within constraints

#### **v4.1 - Genetic Algorithm (GA)**
- **Genome**: Vector of flight loads + purchase decisions for 24h
- **Fitness**: Total cost (run simulation)
- **Operators**: Mutation (±X kits), crossover (split/merge strategies)
- **Evolution**: Run 100-500 generations per round
- **Expected Gain**: 15-25% if well-tuned, handles non-linear penalties better

#### **v4.2 - Reinforcement Learning (RL)**
- **State**: Current stocks, processing queue, next 24h flights
- **Action**: Load quantities + purchase amounts
- **Reward**: -total_cost (penalties + operations)
- **Training**: Simulate thousands of sessions offline
- **Agent**: DQN or PPO
- **Expected Gain**: 20-30% if properly trained, adapts to patterns

#### **v4.3 - Hybrid Approach**
- **Combine**: LP for deterministic core + RL for uncertainty handling
- **Monte Carlo**: Simulate flight delays/variations, optimize expected cost
- **Ensemble**: Run multiple algorithms, choose best decision by majority vote
- **Expected Gain**: 5-10% additional from robustness

### **Phase 5: Fine-Tuning & Edge Cases (Final)**

#### **v5.0 - End-Game Strategy**
- **Last 24 Hours**: Minimize remaining stock penalties
- **Load Management**: Push excess kits onto final flights
- **Purchase Stop**: Avoid buying in last 72h unless critical
- **Expected Gain**: 5-10% end-game penalty reduction

#### **v5.1 - Edge Case Handling**
- **Zero Passenger Flights**: Use for repositioning
- **High-Capacity Aircraft**: Opportunistic bulk transport
- **Processing Queue Overflow**: Prioritize high-value kits
- **Expected Gain**: 2-5% robustness

#### **v5.2 - Parameter Tuning**
- **A/B Testing**: Run multiple sessions with parameter variations
- **Grid Search**: Optimize safety buffers, purchase triggers, forecast windows
- **Cross-Validation**: Test on different week patterns
- **Expected Gain**: 3-7% fine-tuning gains

---

## 🚀 Implementation Roadmap

### **Week 1: Foundation**
- Day 1-2: Setup environment, understand API, read all data files
- Day 3-4: Implement v1.0 (Naive solution) + session manager
- Day 5: Test full session, verify no crashes, document issues
- Day 6-7: Implement v1.1 (Safety buffer) + basic logging

### **Week 2: Optimization Core**
- Day 8-10: Implement v2.0 (Return kits tracking)
- Day 11-13: Implement v2.1 (Processing awareness)
- Day 14: Implement v2.2 (Demand forecasting)

### **Week 3: Advanced Algorithms**
- Day 15-17: Choose one: v4.0 (LP), v4.1 (GA), or v4.2 (RL)
- Day 18-20: Implement chosen algorithm
- Day 21: Test and compare with v2.2 baseline

### **Week 4: Polish & Competition**
- Day 22-24: Implement v3.0-v3.2 enhancements
- Day 25-26: Edge cases + end-game strategy
- Day 27-28: Parameter tuning + multiple test runs
- Day 29: Final testing, code cleanup, documentation
- Day 30: Competition day - deploy best version

---

## 📊 Key Data Files

| File | Path | Content |
|------|------|---------|
| Airports | `eval-platform/src/main/resources/liquibase/data/airports_with_stocks.csv` | 160+ airports with capacity, costs, initial stocks |
| Flight Schedule | `eval-platform/src/main/resources/liquibase/data/flight_plan.csv` | 447 scheduled flights (recurring) |
| Aircraft Types | `eval-platform/src/main/resources/liquibase/data/aircraft_types.csv` | 5-6 aircraft with capacities and costs |
| Teams | `eval-platform/src/main/resources/liquibase/data/teams.csv` | API keys for testing |

---

## 🔧 Local Development

### **Requirements**
- Java 25
- Maven 3.x
- Git

### **Run Backend**
```bash
cd eval-platform
mvn spring-boot:run -Dspring-boot.run.profiles=local
```

### **Access API Documentation**
- Swagger UI: http://127.0.0.1:8080/swagger-ui/index.html
- OpenAPI Spec: http://127.0.0.1:8080/api-docs

### **Get API Key**
- For local testing: Use keys from `teams.csv`
- For competition: You'll receive a unique key

---

## 📈 Success Metrics

### **Stage 1: Automated Ranking (50% weight)**
- **Metric**: Total Cost = Operational + Penalties + End-Game
- **Ranking**: Lower cost = better rank
- **Top 8** advance to Stage 2

### **Stage 2: Jury Interviews (50% weight)**
- Technical Quality (25p)
- Problem Understanding (25p)
- Innovation (20p)
- UX (15p)
- Presentation (15p)

### **Final Score = Stage1_Points × 0.5 + Stage2_Score × 0.5**

---

## 🎓 Development Tips

1. **Start Simple**: Get v1.0 working perfectly before adding complexity
2. **Log Everything**: Track decisions, costs, penalties per round for analysis
3. **Test Incrementally**: Run mini-sessions (24-72 hours) during development
4. **Version Control**: Commit after each working phase
5. **Study Penalties**: Understanding penalty formulas helps prioritize optimizations
6. **Monitor Bottlenecks**: Profile your code - algorithm should complete in < 1 second per round
7. **Validate Locally**: Check flight IDs, positive values, UUID formats before submitting
8. **Think Turn-Based**: Don't try to solve 720 hours at once - optimize per round with lookahead

---

## 📞 Important Links

- **Challenge Description**: `html/index.html` (full detailed specs)
- **Backend Code**: `eval-platform/src/main/java/com/sap/hackaton2025/`
- **Penalty Logic**: `service/impl/SessionServiceImpl.java` + `service/impl/PenaltyFactors.java`
- **Cost Calculation**: Lines 455-466 in `SessionServiceImpl.java`

---

## 🏆 Competition Strategy

**Phase 1-2 is MANDATORY** - You need a working solution that doesn't crash.

**Phase 3 is RECOMMENDED** - Significant competitive advantage.

**Phase 4 is OPTIONAL** - Only if you have time and expertise. v3.2 can win the competition.

**Phase 5 is POLISH** - Difference between top 3 places.

**Focus on**: Understanding the system deeply > Complex algorithms. A well-tuned v3.x beats a buggy v4.x.

---

## 📝 Quick Reference

### **Critical Numbers**
- Total Hours: 720 (30 days × 24h)
- Airports: 160+
- Flights: 447
- Classes: 4 (First, Business, Premium Economy, Economy)
- Kit Lead Times: 48h, 36h, 24h, 12h

### **Decision Points Each Round**
1. Which flights to load?
2. How many kits per class per flight?
3. How many kits to purchase (if any)?

### **Watch Out For**
- Negative stock at outstations (5342 × kits penalty!)
- Unfulfilled passengers (0.003 × cost × distance × passengers)
- Processing time - kits aren't immediately available
- Lead time - purchases take 12-48h to arrive
- End-game penalties - minimize remaining stock in last hours

---

## 🎯 Final Notes

This is a **complex optimization problem** with multiple competing objectives:
- Minimize transport costs (don't overload flights)
- Avoid passenger penalties (ensure kits available)
- Minimize inventory costs (don't overbuy)
- Handle uncertainty (delays, actual vs planned data)

**The key to winning**: Balance these objectives with a smart, adaptive strategy that learns from simulation data.

Good luck! 🚀
