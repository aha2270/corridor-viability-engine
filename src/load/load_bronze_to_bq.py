import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("load_bronze_to_bq")

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
DATASET_ID = os.getenv("BQ_DATASET_NAME", "corridor_dw")

if not PROJECT_ID:
    raise ValueError("GCP_PROJECT_ID missing from environment or .env file.")


def get_bigquery_client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT_ID)


def ensure_dataset_exists(client: bigquery.Client, dataset_id: str) -> None:
    dataset_ref = bigquery.DatasetReference(PROJECT_ID, dataset_id)
    dataset = bigquery.Dataset(dataset_ref)
    dataset.location = "US"
    dataset = client.create_dataset(dataset, exists_ok=True)
    logger.info(f"Verified BigQuery dataset: {dataset.project}.{dataset.dataset_id}")


def load_penndot_traffic(client: bigquery.Client, geojson_path: Path) -> None:
    table_id = f"{PROJECT_ID}.{DATASET_ID}.raw_penndot_traffic"
    logger.info(f"Loading PennDOT traffic data from {geojson_path} into {table_id}...")

    with open(geojson_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows_to_insert = []
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        geom = feat.get("geometry")

        row = {
            "object_id": props.get("OBJECTID"),
            "route_number": str(props.get("ST_RT_NO")),
            "county_code": str(props.get("CTY_CODE")),
            "segment_length_feet": props.get("SEG_LNGTH_FEET"),
            "cur_aadt": props.get("CUR_AADT"),
            "adtt_cur": props.get("ADTT_CUR"),
            "truck_pct": props.get("TRK_PCT"),
            "daily_truck_vmt": props.get("DLY_TRK_VMT"),
            "geometry_wkt": json.dumps(geom) if geom else None,
        }
        rows_to_insert.append(row)

    # Staging table approach enables reliable ST_GEOGFROMGEOJSON conversion in SQL
    staging_table_id = f"{table_id}_staging"

    schema = [
        bigquery.SchemaField("object_id", "INTEGER"),
        bigquery.SchemaField("route_number", "STRING"),
        bigquery.SchemaField("county_code", "STRING"),
        bigquery.SchemaField("segment_length_feet", "FLOAT"),
        bigquery.SchemaField("cur_aadt", "INTEGER"),
        bigquery.SchemaField("adtt_cur", "INTEGER"),
        bigquery.SchemaField("truck_pct", "INTEGER"),
        bigquery.SchemaField("daily_truck_vmt", "INTEGER"),
        bigquery.SchemaField("geometry_wkt", "STRING"),
    ]

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )

    load_job = client.load_table_from_json(rows_to_insert, staging_table_id, job_config=job_config)
    load_job.result()

    merge_sql = f"""
    CREATE OR REPLACE TABLE `{table_id}` AS
    SELECT
      object_id,
      route_number,
      county_code,
      segment_length_feet,
      cur_aadt,
      adtt_cur,
      truck_pct,
      daily_truck_vmt,
      SAFE.ST_GEOGFROMGEOJSON(geometry_wkt) AS geom
    FROM `{staging_table_id}`;
    DROP TABLE `{staging_table_id}`;
    """
    client.query(merge_sql).result()
    logger.info(f"PennDOT table successfully built: {len(rows_to_insert)} records loaded.")


def load_census_demographics(client: bigquery.Client, json_path: Path) -> None:
    table_id = f"{PROJECT_ID}.{DATASET_ID}.raw_census_demographics"
    logger.info(f"Loading Census demographics from {json_path} into {table_id}...")

    with open(json_path, "r", encoding="utf-8") as f:
        rows = json.load(f)

    schema = [
        bigquery.SchemaField("geoid", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("tract_name", "STRING"),
        bigquery.SchemaField("state_fips", "STRING"),
        bigquery.SchemaField("county_fips", "STRING"),
        bigquery.SchemaField("tract_code", "STRING"),
        bigquery.SchemaField("total_population", "INTEGER"),
        bigquery.SchemaField("median_household_income", "INTEGER"),
        bigquery.SchemaField("civilian_labor_force", "INTEGER"),
        bigquery.SchemaField("unemployed_population", "INTEGER"),
    ]

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )

    load_job = client.load_table_from_json(rows, table_id, job_config=job_config)
    load_job.result()
    logger.info(f"Census table successfully built: {len(rows)} records loaded.")


def load_osm_amenities(client: bigquery.Client, geojson_path: Path) -> None:
    table_id = f"{PROJECT_ID}.{DATASET_ID}.raw_osm_amenities"
    logger.info(f"Loading OSM amenities from {geojson_path} into {table_id}...")

    with open(geojson_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows_to_insert = []
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        coords = feat.get("geometry", {}).get("coordinates", [])

        if len(coords) == 2:
            lon, lat = coords
            rows_to_insert.append({
                "osm_id": props.get("osm_id"),
                "name": props.get("name"),
                "brand": props.get("brand"),
                "operator": props.get("operator"),
                "amenity": props.get("amenity"),
                "shop": props.get("shop"),
                "hgv": props.get("hgv"),
                "longitude": float(lon),
                "latitude": float(lat),
            })

    staging_table_id = f"{table_id}_staging"

    schema = [
        bigquery.SchemaField("osm_id", "INTEGER"),
        bigquery.SchemaField("name", "STRING"),
        bigquery.SchemaField("brand", "STRING"),
        bigquery.SchemaField("operator", "STRING"),
        bigquery.SchemaField("amenity", "STRING"),
        bigquery.SchemaField("shop", "STRING"),
        bigquery.SchemaField("hgv", "STRING"),
        bigquery.SchemaField("longitude", "FLOAT"),
        bigquery.SchemaField("latitude", "FLOAT"),
    ]

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )

    load_job = client.load_table_from_json(rows_to_insert, staging_table_id, job_config=job_config)
    load_job.result()

    merge_sql = f"""
    CREATE OR REPLACE TABLE `{table_id}` AS
    SELECT
      osm_id,
      name,
      brand,
      operator,
      amenity,
      shop,
      hgv,
      longitude,
      latitude,
      ST_GEOGPOINT(longitude, latitude) AS geom
    FROM `{staging_table_id}`;
    DROP TABLE `{staging_table_id}`;
    """
    client.query(merge_sql).result()
    logger.info(f"OSM table successfully built: {len(rows_to_insert)} records loaded.")


def load_nrel_ev_stations(client: bigquery.Client, geojson_path: Path) -> None:
    table_id = f"{PROJECT_ID}.{DATASET_ID}.raw_nrel_ev_stations"
    logger.info(f"Loading NREL/NLR EV stations from {geojson_path} into {table_id}...")

    with open(geojson_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows_to_insert = []
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        coords = feat.get("geometry", {}).get("coordinates", [])

        if len(coords) == 2:
            lon, lat = coords
            rows_to_insert.append({
                "station_id": props.get("station_id"),
                "station_name": props.get("station_name"),
                "street_address": props.get("street_address"),
                "city": props.get("city"),
                "state": props.get("state"),
                "zip": props.get("zip"),
                "ev_network": props.get("ev_network"),
                "ev_pricing": props.get("ev_pricing"),
                "level2_ports": props.get("level2_ports", 0),
                "dc_fast_ports": props.get("dc_fast_ports", 0),
                "facility_type": props.get("facility_type"),
                "longitude": float(lon),
                "latitude": float(lat),
            })

    staging_table_id = f"{table_id}_staging"

    schema = [
        bigquery.SchemaField("station_id", "INTEGER"),
        bigquery.SchemaField("station_name", "STRING"),
        bigquery.SchemaField("street_address", "STRING"),
        bigquery.SchemaField("city", "STRING"),
        bigquery.SchemaField("state", "STRING"),
        bigquery.SchemaField("zip", "STRING"),
        bigquery.SchemaField("ev_network", "STRING"),
        bigquery.SchemaField("ev_pricing", "STRING"),
        bigquery.SchemaField("level2_ports", "INTEGER"),
        bigquery.SchemaField("dc_fast_ports", "INTEGER"),
        bigquery.SchemaField("facility_type", "STRING"),
        bigquery.SchemaField("longitude", "FLOAT"),
        bigquery.SchemaField("latitude", "FLOAT"),
    ]

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )

    load_job = client.load_table_from_json(rows_to_insert, staging_table_id, job_config=job_config)
    load_job.result()

    merge_sql = f"""
    CREATE OR REPLACE TABLE `{table_id}` AS
    SELECT
      station_id,
      station_name,
      street_address,
      city,
      state,
      zip,
      ev_network,
      ev_pricing,
      level2_ports,
      dc_fast_ports,
      facility_type,
      longitude,
      latitude,
      ST_GEOGPOINT(longitude, latitude) AS geom
    FROM `{staging_table_id}`;
    DROP TABLE `{staging_table_id}`;
    """
    client.query(merge_sql).result()
    logger.info(f"NREL table successfully built: {len(rows_to_insert)} records loaded.")


def run():
    client = get_bigquery_client()
    ensure_dataset_exists(client, DATASET_ID)

    raw_dir = Path("data/raw")
    load_penndot_traffic(client, raw_dir / "penndot_traffic.geojson")
    load_census_demographics(client, raw_dir / "census_tracts_demographics.json")
    load_osm_amenities(client, raw_dir / "osm_competitor_amenities.geojson")
    load_nrel_ev_stations(client, raw_dir / "nrel_ev_stations.geojson")

    logger.info("All four raw datasets successfully loaded into BigQuery.")


if __name__ == "__main__":
    run()