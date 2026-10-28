import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from google.cloud import bigquery
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("transform_gold")

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
DATASET_ID = os.getenv("BQ_DATASET_NAME", "corridor_dw")

if not PROJECT_ID:
    logger.error("GCP_PROJECT_ID not set in environment or .env file.")
    sys.exit(1)


def build_gold_candidates(client: bigquery.Client):
    table_id = f"{PROJECT_ID}.{DATASET_ID}.gold_travel_plaza_candidates"
    logger.info(f"Creating gold analytical mart table: {table_id}...")

    sql = f"""
    CREATE OR REPLACE TABLE `{table_id}` AS
    SELECT
      object_id,
      route_number,
      county_name,
      segment_length_feet,
      cur_aadt,
      adtt_cur,
      truck_pct,
      daily_truck_vmt,
      competitor_count_1mi,
      major_chain_count_1mi,
      ev_station_count_1mi,
      dc_fast_ports_1mi,
      avg_county_median_income,
      county_unemployment_rate,
      travel_plaza_viability_score,
      commuter_market_viability_score,
      optimal_store_archetype,

      -- Priority rank for Commercial Travel Plaza view
      ROW_NUMBER() OVER (
        PARTITION BY county_name
        ORDER BY travel_plaza_viability_score DESC, object_id ASC
      ) AS travel_plaza_priority_rank,

      -- Priority rank for Commuter Convenience Market view
      ROW_NUMBER() OVER (
        PARTITION BY county_name
        ORDER BY commuter_market_viability_score DESC, object_id ASC
      ) AS commuter_market_priority_rank,

      ST_ASTEXT(geom) AS wkt_geometry,
      geom
    FROM `{PROJECT_ID}.{DATASET_ID}.silver_corridor_viability`
    WHERE travel_plaza_viability_score >= 60.0
       OR commuter_market_viability_score >= 60.0
    ORDER BY county_name, travel_plaza_viability_score DESC;
    """
    job = client.query(sql)
    job.result()
    logger.info(f"Successfully populated {table_id}.")


def export_gold_to_csv(client: bigquery.Client):
    output_dir = Path("data/processed")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "gold_travel_plaza_candidates.csv"

    logger.info(f"Exporting gold table to {output_file}...")

    sql = f"""
    SELECT
      object_id,
      route_number,
      county_name,
      travel_plaza_priority_rank,
      commuter_market_priority_rank,
      optimal_store_archetype,
      travel_plaza_viability_score,
      commuter_market_viability_score,
      cur_aadt,
      adtt_cur,
      truck_pct,
      segment_length_feet,
      competitor_count_1mi,
      major_chain_count_1mi,
      ev_station_count_1mi,
      dc_fast_ports_1mi,
      avg_county_median_income,
      county_unemployment_rate,
      wkt_geometry
    FROM `{PROJECT_ID}.{DATASET_ID}.gold_travel_plaza_candidates`
    ORDER BY county_name, travel_plaza_priority_rank ASC;
    """

    df = client.query(sql).to_dataframe()
    df.to_csv(output_file, index=False)
    logger.info(f"Export complete. Saved {len(df)} candidate segments to CSV.")


def run():
    client = bigquery.Client(project=PROJECT_ID)
    build_gold_candidates(client)
    export_gold_to_csv(client)


if __name__ == "__main__":
    run()