# Rotables Challenge Solver - API Integration Guide

## Running the Solver with Backend API

This guide explains how to use the solver with the backend evaluation platform.

## Quick Start

### 1. Install Dependencies

```powershell
pip install -r requirements.txt
```

Required packages:
- `requests` - HTTP client for API communication
- `python-dotenv` - Environment variable management

### 2. Configure API Access

Edit `.env` file with your API credentials:

```
API_KEY=43b9ab90-b593-404c-a8d8-aaa074e181e1
BASE_URL=http://127.0.0.1:8080/api/v1
```

### 3. Start Backend Server

In a separate terminal:

```powershell
cd ..\eval-platform
.\mvnw spring-boot:run
```

Wait for message: "Started EvalPlatformApplication"

### 4. Run Solver

```powershell
python run_solver.py
```

## Architecture

### Files Created

- **`api_client.py`** - HTTP client for `/session/start`, `/play/round`, `/session/end` endpoints
- **`naive_api_strategy.py`** - Strategy implementation that works with the API
- **`run_solver.py`** - Main entry point that orchestrates the session

### API Flow

```
1. POST /api/v1/session/start
   → Returns session ID

2. Loop 720 times (30 days × 24 hours):
   POST /api/v1/play/round
   - Headers: API-KEY, SESSION-ID
   - Body: {day, hour, flightLoads, kitPurchasingOrders}
   → Returns: {day, hour, flightUpdates, penalties, totalCost}

3. POST /api/v1/session/end
   → Returns final results
```

## Strategy Implementation

### Naive API Strategy

Located in `naive_api_strategy.py`

**Decision Logic:**
1. Check HUB inventory estimates
2. If below safety stock, purchase kits:
   - First: 500 safety / 300 reorder
   - Business: 1500 / 800
   - Premium Economy: 800 / 500
   - Economy: 8000 / 5000
3. For CHECKED_IN flights, load exact passenger counts

**Key Methods:**
- `get_decisions_for_round()` - Generate decisions for current hour
- `update_from_api_response()` - Process API response

## Expected Results

### Baseline Cost (Naive Strategy)

- **Target Range:** €800,000 - €1,200,000
- **Execution Time:** 5-10 minutes
- **Sessions:** 720 rounds

### Cost Breakdown

The final result will show:
- Total operational cost (loading + transport + processing)
- Total penalty cost (by type)
- Final total cost

## Logs

All activity is logged to:
- **Console:** INFO level progress
- **File:** `solver_session.log` - detailed debug info

View logs:
```powershell
Get-Content solver_session.log -Tail 50
```

## Troubleshooting

### Connection Refused
**Error:** `Failed to start session: Connection refused`

**Fix:** Backend not running. Start it:
```powershell
cd ..\eval-platform
.\mvnw spring-boot:run
```

### Invalid API Key
**Error:** `401 Unauthorized`

**Fix:** Check API key in `.env` file. Valid keys are in:
```
eval-platform/src/main/resources/liquibase/data/teams.csv
```

### Import Errors
**Error:** `ModuleNotFoundError: No module named 'src'`

**Fix:** Run from solver directory:
```powershell
cd solver
python run_solver.py
```

## Next Steps

### Phase 2: Improved Strategy

To beat the baseline, implement:
1. **Demand Forecasting:** Predict demand 48-72 hours ahead
2. **Smart Purchasing:** Buy ahead of demand peaks, not reactively
3. **Route Analysis:** Handle 145 critical routes with tight turnarounds
4. **Load Optimization:** Balance passenger fulfillment vs capacity penalties

Target: €400K-€600K (50% improvement)

### Files to Modify

1. Create `greedy_api_strategy.py`
2. Implement better decision logic in `get_decisions_for_round()`
3. Update `run_solver.py` to select strategy
4. Test and iterate

## Performance Monitoring

Track metrics during session:
- Flights processed
- Kits purchased
- Penalty events
- Cost progression

Example output:
```
Day  0 complete - Total: €28,450.23 (Day cost: €28,450.23)
Day  1 complete - Total: €56,891.45 (Day cost: €28,441.22)
...
Day 29 complete - Total: €845,123.67 (Day cost: €29,012.34)
```

## Bug Fix Summary

**Fixed:** Infinite loop in `naive_strategy.py`
- **Issue:** Loop condition `while current_hour < total_hours` checked hour (0-23) vs 720
- **Fix:** Changed to check total elapsed hours: `day * 24 + hour >= total_hours`

This fix ensures simulation stops at exactly 720 hours (30 days).
