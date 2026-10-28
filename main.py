import logging
import sys
import time

from src.extract import extract_census, extract_nrel, extract_overpass, extract_penndot
from src.load import load_bronze_to_bq
from src.transform import transform_gold, transform_silver
from src.visualize import generate_interactive_map

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("corridor_viability_engine")


def run_pipeline():
    start_time = time.time()
    logger.info("==================================================")
    logger.info("STARTING CORRIDOR VIABILITY ENGINE PIPELINE")
    logger.info("==================================================")

    logger.info(">>> Stage 1: Bronze Ingestion (APIs -> Raw/GCS)")
    extract_penndot.run()
    extract_census.run()
    extract_overpass.run()
    extract_nrel.run()

    logger.info(">>> Stage 2: BigQuery Staging (Bronze -> Raw Tables)")
    load_bronze_to_bq.run()

    logger.info(">>> Stage 3: Silver Modeling & Spatial Buffers")
    transform_silver.run()

    logger.info(">>> Stage 4: Gold Mart Aggregations & Scoring")
    transform_gold.run()

    logger.info(">>> Stage 5: Analytical Map & Artifact Generation")
    generate_interactive_map.run()

    elapsed = round(time.time() - start_time, 2)
    logger.info("==================================================")
    logger.info(f"PIPELINE COMPLETE - Run duration: {elapsed}s")
    logger.info("==================================================")


if __name__ == "__main__":
    try:
        run_pipeline()
    except Exception as e:
        logger.error(f"Fatal pipeline error: {e}", exc_info=True)
        sys.exit(1)