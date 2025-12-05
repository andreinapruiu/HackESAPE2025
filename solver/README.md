# Simple Solver for Rotables Challenge

This is a basic starting point solver that implements a naive algorithm to solve the Rotables Challenge.

## Algorithm

The solver implements a simple strategy:
- **Flight Loading**: Loads exactly the number of kits equal to passengers for each flight (when CHECKED_IN event occurs)
- **Kit Purchasing**: Purchases a fixed amount of kits every 12 hours to maintain stock

This is a baseline implementation that should complete a full session without major crashes, but is not optimized for cost.

## Requirements

- Python 3.8+
- `requests` library
- `python-dotenv` library

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the `solver` directory (or copy from `.env.example`) to configure the API connection:

```bash
# Copy the example file
cp .env.example .env

# Then edit .env with your settings
```

The `.env` file should contain:
```
API_KEY=your-api-key-here
BASE_URL=http://127.0.0.1:8080/api/v1
```

You can get API keys from `eval-platform/src/main/resources/liquibase/data/teams.csv` for testing.

## Usage

### Basic Usage

```bash
python simple_solver.py
```

This will use the default API key (Testing-1) and connect to `http://127.0.0.1:8080/api/v1`.

### Custom API Key

```bash
python simple_solver.py --api-key "your-api-key-here"
```

### Custom API URL

```bash
python simple_solver.py --base-url "http://your-server:8080/api/v1"
```

## How It Works

1. **Start Session**: Connects to the evaluation platform and starts a new session
2. **Play Rounds**: For each hour (0-719):
   - Receives flight updates from the previous round
   - Calculates which flights need kits loaded (CHECKED_IN events)
   - Loads exactly the number of kits equal to passengers
   - Purchases kits periodically to maintain stock
   - Submits decisions to the API
3. **End Session**: Ends the session and displays final results

## Next Steps

To improve this solver, consider:

1. **Track Inventory**: Monitor stock levels at HUB1 and outstations
2. **Demand Forecasting**: Analyze flight schedules to predict future demand
3. **Return Kit Tracking**: Account for kits returning from flights
4. **Processing Time Awareness**: Consider kit processing times
5. **Cost Optimization**: Balance transport costs vs. penalties
6. **Advanced Algorithms**: Implement LP, GA, or RL approaches

See the main README.md for detailed algorithm development plans.

