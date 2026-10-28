import logging
import os
from pathlib import Path
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("transform_gold")

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
DATASET_ID = os.getenv("BQ_DATASET_NAME", "corridor_dw")

if not PROJECT_ID:
    raise ValueError("GCP_PROJECT_ID missing from environment or .env file.")

client = bigquery.Client(project=PROJECT_ID)


def build_gold_travel_plaza_candidates():
    """
    Filters high-scoring segments from the silver viability model, ranks
    opportunities within each county, and formats geometries for downstream BI/GIS layers.
    """
    table_id = f"{PROJECT_ID}.{DATASET_ID}.gold_travel_plaza_candidates"
    logger.info(f"Building Gold Mart table: {table_id}...")

    # Threshold: viability score >= 200 isolates high-volume commercial freight
    # corridors with low existing DC fast charging saturation.
    sql = f"""
    CREATE OR REPLACE TABLE `{table_id}` AS
    SELECT
      object_id,
      route_number,
      county_name,
      cur_aadt,
      adtt_cur,
      truck_pct,
      competitor_count_1mi,
      major_chain_count_1mi,
      ev_station_count_1mi,
      dc_fast_ports_1mi,
      avg_county_median_income,
      county_unemployment_rate,
      travel_plaza_viability_score,
      DENSE_RANK() OVER (
        PARTITION BY county_name
        ORDER BY travel_plaza_viability_score DESC
      ) AS county_priority_rank,
      ST_ASTEXT(geom) AS wkt_geometry,
      geom
    FROM `{PROJECT_ID}.{DATASET_ID}.silver_corridor_viability`
    WHERE travel_plaza_viability_score >= 200
    ORDER BY travel_plaza_viability_score DESC;
    """
    query_job = client.query(sql)
    query_job.result()
    logger.info(f"Successfully generated {table_id}.")


def export_gold_candidates_locally(output_path: Path):
    """
    Extracts the final gold candidates to a local CSV for direct import into
    visualization tools such as Kepler.gl, QGIS, or Looker Studio.
    """
    logger.info(f"Exporting gold tier results to local path: {output_path}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    query = f"""
    SELECT
      object_id,
      route_number,
      county_name,
      county_priority_rank,
      cur_aadt,
      adtt_cur,
      truck_pct,
      competitor_count_1mi,
      major_chain_count_1mi,
      ev_station_count_1mi,
      dc_fast_ports_1mi,
      avg_county_median_income,
      county_unemployment_rate,
      travel_plaza_viability_score,
      wkt_geometry
    FROM `{PROJECT_ID}.{DATASET_ID}.gold_travel_plaza_candidates`
    ORDER BY county_name, county_priority_rank;
    """
    df = client.query(query).to_dataframe()
    df.to_csv(output_path, index=False)
    logger.info(f"Successfully exported {len(df)} candidate corridors to {output_path}.")


def run():
    build_gold_travel_plaza_candidates()
    export_gold_candidates_locally(Path("data/processed/gold_travel_plaza_candidates.csv"))
    logger.info("Gold transformation and reporting export complete.")


if __name__ == "__main__":
    run()