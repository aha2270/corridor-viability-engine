import os
import sys
import logging
from dotenv import load_dotenv
from google.cloud import storage

# Configure pipeline root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("corridor_viability_engine")

load_dotenv()
BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "corridor-bronze-landing-ah")

def purge_gcs_landing_zone(bucket_name: str, prefix: str = "bronze/") -> None:
    """
    Deletes all existing blobs under the designated GCS prefix to ensure 
    the pipeline executes against a completely clean landing zone.
    """
    logger.info(f"Connecting to GCS bucket: '{bucket_name}'...")
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blobs = list(client.list_blobs(bucket, prefix=prefix))

    if not blobs:
        logger.info(f"Landing prefix gs://{bucket_name}/{prefix} is already empty.")
        return

    logger.info(f"Found {len(blobs)} prior file(s) in gs://{bucket_name}/{prefix}. Purging...")
    with client.batch():
        for blob in blobs:
            blob.delete()
    logger.info("Landing zone purge complete. Working with a clean slate.")

def run_pipeline():
    logger.info("==================================================")
    logger.info("STARTING CORRIDOR VIABILITY ENGINE PIPELINE")
    logger.info("==================================================")

    # Stage 0: Enforce GCS Idempotency
    logger.info(">>> Stage 0: Clean Slate Initialization")
    purge_gcs_landing_zone(bucket_name=BUCKET_NAME, prefix="bronze/")

    # Import pipeline stages
    from src.extract import extract_penndot
    from src.extract import extract_census
    from src.extract import extract_overpass
    from src.extract import extract_nrel
    from src.load import load_bronze_to_bq
    from src.transform import transform_silver
    from src.transform import transform_gold
    from src.visualize import generate_interactive_map

    # Stage 1: Bronze Ingestion (APIs -> Raw/GCS)
    logger.info(">>> Stage 1: Bronze Ingestion (APIs -> Raw/GCS)")
    extract_penndot.run()
    extract_census.run()
    extract_overpass.run()
    extract_nrel.run()

    # Stage 2: BigQuery Staging (Bronze -> Raw Tables)
    logger.info(">>> Stage 2: BigQuery Staging (Bronze -> Raw Tables)")
    load_bronze_to_bq.run()

    # Stage 3: Silver Modeling & Spatial Buffers
    logger.info(">>> Stage 3: Silver Modeling & Spatial Buffers")
    transform_silver.run()

    # Stage 4: Gold Mart Aggregations & Scoring
    logger.info(">>> Stage 4: Gold Mart Aggregations & Scoring")
    transform_gold.run()

    # Stage 5: Analytical Map & Artifact Generation
    logger.info(">>> Stage 5: Analytical Map & Artifact Generation")
    if hasattr(generate_interactive_map, "run"):
        generate_interactive_map.run()
    elif hasattr(generate_interactive_map, "generate_map"):
        generate_interactive_map.generate_map()
    elif hasattr(generate_interactive_map, "main"):
        generate_interactive_map.main()
    else:
        raise AttributeError("No entrypoint (run, generate_map, or main) found in generate_interactive_map.py")

    logger.info("==================================================")
    logger.info("PIPELINE RUN COMPLETE - ALL ASSETS MATERIALIZED")
    logger.info("==================================================")

if __name__ == "__main__":
    run_pipeline()