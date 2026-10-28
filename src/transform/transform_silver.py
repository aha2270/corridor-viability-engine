import logging
import os
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("transform_silver")

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
DATASET_ID = os.getenv("BQ_DATASET_NAME", "corridor_dw")

if not PROJECT_ID:
    raise ValueError("GCP_PROJECT_ID missing from environment or .env file.")

client = bigquery.Client(project=PROJECT_ID)


def build_silver_corridors():
    """Filters commercial freight corridors and builds 1-mile spatial buffers."""
    table_id = f"{PROJECT_ID}.{DATASET_ID}.silver_high_volume_corridors"
    logger.info(f"Building {table_id}...")

    sql = f"""
    CREATE OR REPLACE TABLE `{table_id}` AS
    SELECT
      object_id,
      route_number,
      county_code,
      CASE county_code
        WHEN '21' THEN 'Cumberland'
        WHEN '22' THEN 'Dauphin'
        WHEN '38' THEN 'Lebanon'
        ELSE 'Other'
      END AS county_name,
      segment_length_feet,
      cur_aadt,
      adtt_cur,
      truck_pct,
      daily_truck_vmt,
      geom,
      ST_BUFFER(geom, 1609.34) AS buffer_1mile_geom
    FROM `{PROJECT_ID}.{DATASET_ID}.raw_penndot_traffic`
    WHERE geom IS NOT NULL
      AND (truck_pct >= 18 OR adtt_cur >= 1200);
    """
    client.query(sql).result()
    logger.info(f"Successfully created {table_id}.")


def build_silver_amenities():
    """Standardizes competitor brands and EV network classifications."""
    table_id = f"{PROJECT_ID}.{DATASET_ID}.silver_amenities"
    logger.info(f"Building {table_id}...")

    sql = f"""
    CREATE OR REPLACE TABLE `{table_id}` AS
    SELECT
      osm_id,
      COALESCE(name, brand, 'Unknown Station') AS facility_name,
      UPPER(COALESCE(brand, name, 'Independent')) AS brand_norm,
      CASE
        WHEN REGEXP_CONTAINS(LOWER(COALESCE(brand, name, '')), r'sheetz|wawa|rutter|pilot|flying j|love|travelcenters|ta ') THEN TRUE
        ELSE FALSE
      END AS is_major_chain,
      amenity,
      shop,
      hgv,
      geom
    FROM `{PROJECT_ID}.{DATASET_ID}.raw_osm_amenities`
    WHERE geom IS NOT NULL;
    """
    client.query(sql).result()
    logger.info(f"Successfully created {table_id}.")


def build_silver_corridor_viability():
    """
    Executes spatial intersection joins against corridor buffers and computes
    a standardized 0-100 Multi-Criteria Viability Index.
    """
    table_id = f"{PROJECT_ID}.{DATASET_ID}.silver_corridor_viability"
    logger.info(f"Building composite viability analytics table: {table_id}...")

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
    )
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
      ca.competitor_count_1mi,
      ca.major_chain_count_1mi,
      cev.ev_station_count_1mi,
      cev.dc_fast_ports_1mi,
      cd.avg_county_median_income,
      cd.county_unemployment_rate,
      
      -- Standardized 0-100 Viability Index
      ROUND(
        -- 1. Truck Volume component (Max 40 pts, saturated at 15,000 ADTT)
        LEAST(40.0, (SAFE_DIVIDE(c.adtt_cur, 15000.0) * 40.0)) +
        
        -- 2. Truck Percentage component (Max 25 pts, saturated at 50% truck share)
        LEAST(25.0, (SAFE_DIVIDE(c.truck_pct, 50.0) * 25.0)) +
        
        -- 3. EV Fast Charging Gap (Max 20 pts: 20 for zero ports, declining to 0 for 4+ ports)
        GREATEST(0.0, 20.0 - (cev.dc_fast_ports_1mi * 5.0)) +
        
        -- 4. Competitor Retail Gap (Max 15 pts: 15 for zero major chains, declining to 0 for 3+ chains)
        GREATEST(0.0, 15.0 - (ca.major_chain_count_1mi * 5.0)),
        2
      ) AS travel_plaza_viability_score,
      
      c.geom,
      c.buffer_1mile_geom
    FROM `{PROJECT_ID}.{DATASET_ID}.silver_high_volume_corridors` c
    LEFT JOIN corridor_amenities ca ON c.object_id = ca.object_id
    LEFT JOIN corridor_ev cev ON c.object_id = cev.object_id
    LEFT JOIN county_demographics cd
      ON (c.county_code = '21' AND cd.county_fips = '041')
      OR (c.county_code = '22' AND cd.county_fips = '043')
      OR (c.county_code = '38' AND cd.county_fips = '075');
    """
    client.query(sql).result()
    logger.info(f"Successfully created {table_id}.")


def run():
    build_silver_corridors()
    build_silver_amenities()
    build_silver_corridor_viability()
    logger.info("Silver transformation layer complete.")


if __name__ == "__main__":
    run()