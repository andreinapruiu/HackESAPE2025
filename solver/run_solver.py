"""
Main Solver Script for Rotables Challenge
Runs strategy against backend API and establishes baseline cost
"""
import logging
import sys
import os
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, will use environment variables directly

from src.data_warehouse import DataWarehouse
from src.naive_api_strategy import run_naive_strategy_with_api

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('solver_session.log')
    ]
)

logger = logging.getLogger(__name__)


def main():
    """Main entry point for solver"""
    
    # Configuration from environment variables
    API_KEY = os.environ.get('API_KEY', '43b9ab90-b593-404c-a8d8-aaa074e181e1')
    BASE_URL = os.environ.get('BASE_URL', 'http://127.0.0.1:8080/api/v1')
    
    # Extract base URL without /api/v1 if present (our client adds it)
    if BASE_URL.endswith('/api/v1'):
        API_URL = BASE_URL[:-7]  # Remove /api/v1
    else:
        API_URL = BASE_URL
    
    logger.info("=" * 80)
    logger.info("ROTABLES CHALLENGE SOLVER")
    logger.info("=" * 80)
    logger.info(f"API URL: {API_URL}")
    logger.info(f"API KEY: {API_KEY[:8]}..." if len(API_KEY) > 8 else f"API KEY: {API_KEY}")
    logger.info("")
    
    # Step 1: Load data
    logger.info("Loading data warehouse...")
    data_warehouse = DataWarehouse()
    
    try:
        data_warehouse.load_all_data()
        logger.info("[OK] Data loaded successfully")
        logger.info(f"  - Airports: {len(data_warehouse.airports)}")
        logger.info(f"  - Aircraft types: {len(data_warehouse.aircraft_types)}")
        logger.info(f"  - Flight patterns: {len(data_warehouse.flight_schedule_patterns)}")
        logger.info("")
    except Exception as e:
        logger.error(f"[ERROR] Failed to load data: {e}")
        return 1
    
    # Step 2: Run naive baseline strategy
    try:
        logger.info("Starting naive baseline strategy session...")
        logger.info("This will take approximately 5-10 minutes...\n")
        
        final_result = run_naive_strategy_with_api(
            api_url=API_URL,
            api_key=API_KEY,
            data_warehouse=data_warehouse
        )
        
        # Display final results
        logger.info("\n" + "=" * 80)
        logger.info("FINAL RESULTS")
        logger.info("=" * 80)
        logger.info(f"Total Cost: €{final_result.get('totalCost', 0):,.2f}")
        
        penalties = final_result.get('penalties', [])
        if penalties:
            logger.info(f"\nFinal Penalties: {len(penalties)}")
            for penalty in penalties[:10]:  # Show first 10
                logger.info(f"  - {penalty.get('type')}: €{penalty.get('amount', 0):,.2f}")
        
        logger.info("=" * 80)
        logger.info("Session complete! Check solver_session.log for details.")
        
        return 0
        
    except KeyboardInterrupt:
        logger.warning("\n\nSession interrupted by user")
        return 130
        
    except Exception as e:
        logger.error(f"\n\nSession failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
