import logging
import os
import sys
from dotenv import load_dotenv
from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("transform_silver")

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
DATASET_ID = os.getenv("BQ_DATASET_NAME", "corridor_dw")

if not PROJECT_ID:
    logger.error("GCP_PROJECT_ID not set in environment or .env file.")
    sys.exit(1)


def build_silver_high_volume_corridors(client: bigquery.Client):
    table_id = f"{PROJECT_ID}.{DATASET_ID}.silver_high_volume_corridors"
    logger.info(f"Creating spatial corridor buffer table: {table_id}...")

    sql = f"""
    CREATE OR REPLACE TABLE `{table_id}` AS
    SELECT
      object_id,
      route_number,
      county_code,
      CASE
        WHEN county_code = '21' THEN 'Cumberland'
        WHEN county_code = '22' THEN 'Dauphin'
        WHEN county_code = '38' THEN 'Lebanon'
        ELSE CONCAT('County_', county_code)
      END AS county_name,
      segment_length_feet,
      cur_aadt,
      adtt_cur,
      truck_pct,
      ROUND(SAFE_DIVIDE(adtt_cur * segment_length_feet, 5280.0), 2) AS daily_truck_vmt,
      geom,
      ST_BUFFER(geom, 1609.34) AS buffer_1mile_geom
    FROM `{PROJECT_ID}.{DATASET_ID}.raw_penndot_traffic`
    WHERE cur_aadt IS NOT NULL;
    """
    job = client.query(sql)
    job.result()
    logger.info(f"Successfully populated {table_id}.")


def build_silver_amenities(client: bigquery.Client):
    table_id = f"{PROJECT_ID}.{DATASET_ID}.silver_amenities"
    logger.info(f"Creating categorized competitor amenities table: {table_id}...")

    sql = f"""
    CREATE OR REPLACE TABLE `{table_id}` AS
    SELECT
      osm_id,
      amenity,
      name,
      brand,
      CASE
        WHEN LOWER(COALESCE(brand, '')) LIKE '%pilot%'
          OR LOWER(COALESCE(brand, '')) LIKE '%flying j%'
          OR LOWER(COALESCE(brand, '')) LIKE '%love%'
          OR LOWER(COALESCE(brand, '')) LIKE '%travelcenters of america%'
          OR LOWER(COALESCE(brand, '')) LIKE '%ta express%'
          OR LOWER(COALESCE(brand, '')) LIKE '%sheetz%'
          OR LOWER(COALESCE(brand, '')) LIKE '%wawa%'
          OR LOWER(COALESCE(brand, '')) LIKE '%rutter%'
          OR LOWER(COALESCE(name, '')) LIKE '%pilot%'
          OR LOWER(COALESCE(name, '')) LIKE '%flying j%'
          OR LOWER(COALESCE(name, '')) LIKE '%love%'
          OR LOWER(COALESCE(name, '')) LIKE '%travelcenters of america%'
          OR LOWER(COALESCE(name, '')) LIKE '%sheetz%'
          OR LOWER(COALESCE(name, '')) LIKE '%wawa%'
          OR LOWER(COALESCE(name, '')) LIKE '%rutter%'
        THEN TRUE
        ELSE FALSE
      END AS is_major_chain,
      geom
    FROM `{PROJECT_ID}.{DATASET_ID}.raw_osm_amenities`;
    """
    job = client.query(sql)
    job.result()
    logger.info(f"Successfully populated {table_id}.")


def build_silver_corridor_viability(client: bigquery.Client):
    table_id = f"{PROJECT_ID}.{DATASET_ID}.silver_corridor_viability"
    logger.info(f"Computing dual-archetype MCDA scores for {table_id}...")

    sql = f"""
    CREATE OR REPLACE TABLE `{table_id}` AS
    WITH corridor_amenities AS (
      SELECT
        c.object_id,
        COUNT(DISTINCT a.osm_id) AS competitor_count_1mi,
        COUNT(DISTINCT CASE WHEN a.is_major_chain THEN a.osm_id END) AS major_chain_count_1mi
      FROM `{PROJECT_ID}.{DATASET_ID}.silver_high_volume_corridors` c
      LEFT JOIN `{PROJECT_ID}.{DATASET_ID}.silver_amenities` a
        ON ST_INTERSECTS(c.buffer_1mile_geom, a.geom)
      GROUP BY c.object_id
    ),
    corridor_ev AS (
      SELECT
        c.object_id,
        COUNT(DISTINCT ev.station_id) AS ev_station_count_1mi,
        COALESCE(SUM(ev.dc_fast_ports), 0) AS dc_fast_ports_1mi
      FROM `{PROJECT_ID}.{DATASET_ID}.silver_high_volume_corridors` c
      LEFT JOIN `{PROJECT_ID}.{DATASET_ID}.raw_nrel_ev_stations` ev
        ON ST_INTERSECTS(c.buffer_1mile_geom, ev.geom)
      GROUP BY c.object_id
    ),
    county_demographics AS (
      SELECT
        county_fips,
        ROUND(AVG(median_household_income), 2) AS avg_county_median_income,
        ROUND(SAFE_DIVIDE(SUM(unemployed_population), SUM(civilian_labor_force)) * 100, 2) AS county_unemployment_rate
      FROM `{PROJECT_ID}.{DATASET_ID}.raw_census_demographics`
      WHERE median_household_income IS NOT NULL
      GROUP BY county_fips
    ),
    scored_corridors AS (
      SELECT
        c.object_id,
        c.route_number,
        c.county_code,
        c.county_name,
        c.segment_length_feet,
        c.cur_aadt,
        c.adtt_cur,
        c.truck_pct,
        c.daily_truck_vmt,
        COALESCE(ca.competitor_count_1mi, 0) AS competitor_count_1mi,
        COALESCE(ca.major_chain_count_1mi, 0) AS major_chain_count_1mi,
        COALESCE(cev.ev_station_count_1mi, 0) AS ev_station_count_1mi,
        COALESCE(cev.dc_fast_ports_1mi, 0) AS dc_fast_ports_1mi,
        COALESCE(cd.avg_county_median_income, 65000.0) AS avg_county_median_income,
        COALESCE(cd.county_unemployment_rate, 4.0) AS county_unemployment_rate,

        -- 1. Commercial Travel Plaza Score (0.0 to 100.0, Freight-Focused)
        ROUND(
          LEAST(35.0, (SAFE_DIVIDE(c.adtt_cur, 14000.0) * 35.0)) +
          LEAST(20.0, (SAFE_DIVIDE(c.truck_pct, 40.0) * 20.0)) +
          GREATEST(0.0, 15.0 - (COALESCE(cev.dc_fast_ports_1mi, 0) * 5.0)) +
          GREATEST(0.0, 15.0 - (COALESCE(ca.major_chain_count_1mi, 0) * 5.0)) +
          LEAST(15.0, (SAFE_DIVIDE(COALESCE(cd.county_unemployment_rate, 4.0), 6.0) * 15.0)),
          2
        ) AS travel_plaza_viability_score,

        -- 2. Commuter Convenience Market Score (0.0 to 100.0, Passenger & Socioeconomic-Focused)
        ROUND(
          LEAST(35.0, (SAFE_DIVIDE(c.cur_aadt, 45000.0) * 35.0)) +
          LEAST(25.0, (SAFE_DIVIDE(COALESCE(cd.avg_county_median_income, 65000.0), 85000.0) * 25.0)) +
          LEAST(15.0, (SAFE_DIVIDE(COALESCE(cd.county_unemployment_rate, 4.0), 6.0) * 15.0)) +
          GREATEST(0.0, 15.0 - (COALESCE(ca.competitor_count_1mi, 0) * 2.5)) +
          GREATEST(0.0, 10.0 - (COALESCE(cev.dc_fast_ports_1mi, 0) * 3.0)),
          2
        ) AS commuter_market_viability_score,

        c.geom,
        c.buffer_1mile_geom
      FROM `{PROJECT_ID}.{DATASET_ID}.silver_high_volume_corridors` c
      LEFT JOIN corridor_amenities ca ON c.object_id = ca.object_id
      LEFT JOIN corridor_ev cev ON c.object_id = cev.object_id
      LEFT JOIN county_demographics cd
        ON (c.county_code = '21' AND cd.county_fips = '041')
        OR (c.county_code = '22' AND cd.county_fips = '043')
        OR (c.county_code = '38' AND cd.county_fips = '075')
    )
    SELECT
      *,
      CASE
        WHEN travel_plaza_viability_score >= commuter_market_viability_score AND truck_pct >= 18.0
          THEN 'Commercial Travel Plaza'
        WHEN commuter_market_viability_score > travel_plaza_viability_score AND cur_aadt >= 20000
          THEN 'Commuter Convenience Market'
        ELSE 'Secondary Commercial Corridor'
      END AS optimal_store_archetype
    FROM scored_corridors;
    """
    job = client.query(sql)
    job.result()
    logger.info(f"Successfully populated {table_id} with dual-archetype MCDA scores.")


def run():
    client = bigquery.Client(project=PROJECT_ID)
    build_silver_high_volume_corridors(client)
    build_silver_amenities(client)
    build_silver_corridor_viability(client)


if __name__ == "__main__":
    run()