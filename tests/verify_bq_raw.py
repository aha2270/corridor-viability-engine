import os
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
DATASET_ID = os.getenv("BQ_DATASET_NAME", "corridor_dw")

client = bigquery.Client(project=PROJECT_ID)

tables = [
    "raw_penndot_traffic",
    "raw_census_demographics",
    "raw_osm_amenities",
    "raw_nrel_ev_stations",
]

print(f"Checking tables in {PROJECT_ID}.{DATASET_ID}:")
print("-" * 65)

for table in tables:
    table_ref = f"{PROJECT_ID}.{DATASET_ID}.{table}"
    try:
        t = client.get_table(table_ref)
        count_query = f"SELECT COUNT(1) AS cnt FROM `{table_ref}`"
        count_res = list(client.query(count_query).result())[0].cnt
        print(f"Table: {table:<25} | Rows: {count_res:<7} | Columns: {len(t.schema)}")
    except Exception as e:
        print(f"Table: {table:<25} | Error: {e}")

print("-" * 65)

# Verify Spatial Geometries
spatial_check_sql = f"""
SELECT
  (SELECT COUNT(1) FROM `{PROJECT_ID}.{DATASET_ID}.raw_penndot_traffic` WHERE geom IS NOT NULL) AS penndot_geoms,
  (SELECT COUNT(1) FROM `{PROJECT_ID}.{DATASET_ID}.raw_osm_amenities` WHERE geom IS NOT NULL) AS osm_geoms,
  (SELECT COUNT(1) FROM `{PROJECT_ID}.{DATASET_ID}.raw_nrel_ev_stations` WHERE geom IS NOT NULL) AS nrel_geoms
"""
row = list(client.query(spatial_check_sql).result())[0]
print(f"Valid Geometries -> PennDOT Lines: {row.penndot_geoms} | OSM Points: {row.osm_geoms} | NREL Points: {row.nrel_geoms}")