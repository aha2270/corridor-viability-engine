# Corridor Viability Engine — Data Dictionary & Schema Specification

This document defines the schema contracts, source provenance, transformations, and mathematical formulations across the Medallion Architecture (Bronze $\rightarrow$ Silver $\rightarrow$ Gold) for the Pennsylvania Interstate Corridor Viability pipeline.

---

## 1. Architecture Overview

```text
[ External APIs ]
  │  ├── PennDOT RMS (Traffic & Geometry)
  │  ├── U.S. Census Bureau (ACS 5-Year Demographics)
  │  ├── OpenStreetMap Overpass (Competitor Amenities)
  │  └── NREL AFDC (Alternative Fuel Stations)
  ▼
[ Bronze Layer: Google Cloud Storage (GCS) ]
  │  └── Raw JSON / GeoJSON immutable snapshot objects
  ▼
[ Staging / Raw Layer: Google BigQuery ]
  │  ├── raw_penndot_traffic
  │  ├── raw_census_demographics
  │  ├── raw_osm_amenities
  │  └── raw_nrel_ev_stations
  ▼
[ Silver Layer: Feature Engineering & Geospatial Joins ]
  │  ├── silver_high_volume_corridors (1-mile spatial buffer)
  │  ├── silver_amenities (Competitive classification)
  │  └── silver_corridor_viability (0–100 MCDA scoring)
  ▼
[ Gold Layer: Analytical Mart & Delivery ]
  │  ├── gold_travel_plaza_candidates (Ranked priority mart)
  │  ├── data/processed/gold_travel_plaza_candidates.csv
  │  └── docs/corridor_viability_map.html (Interactive Folium map)
```

---

## 2. Bronze Tier (Storage & Staging)

### Storage Destination
* **Engine:** Google Cloud Storage (GCS) & Local Landing Cache
* **Bucket Path:** `gs://corridor-viability-engine-data/bronze/`
* **Format:** Unaltered JSON / GeoJSON snapshots partitioned by date/run

| Data Entity | Source System | Raw Landing Path | Ingestion Script | Format |
| :--- | :--- | :--- | :--- | :--- |
| **PennDOT Traffic** | PennDOT RMS Open Data (ArcGIS REST) | `bronze/penndot/penndot_traffic_*.geojson` | `extract_penndot.py` | GeoJSON |
| **Census Demographics** | U.S. Census Bureau (ACS 5-Yr) | `bronze/census/census_demographics_*.json` | `extract_census.py` | JSON |
| **Competitor Amenities**| OpenStreetMap (Overpass QL API) | `bronze/overpass/osm_amenities_*.geojson` | `extract_overpass.py` | GeoJSON |
| **EV Fast Chargers** | NREL AFDC API | `bronze/nrel/nrel_ev_stations_*.json` | `extract_nrel.py` | JSON |

---

## 3. BigQuery Staging / Raw Tier

### 3.1 Table: `raw_penndot_traffic`
Stores linear roadway centerlines, functional classifications, and annual traffic volume observations.

| Column Name | BigQuery Type | Nullable | Source Field | Description |
| :--- | :--- | :--- | :--- | :--- |
| `object_id` | `INT64` | No | `OBJECTID` | Unique PennDOT roadway segment identifier (Primary Key) |
| `route_number` | `STRING` | No | `TRAF_RT_NO` | Designated state/interstate route number (e.g., '0081') |
| `county_code` | `STRING` | No | `CTY_CODE` | PennDOT county jurisdiction code ('21', '22', '38') |
| `jurisdiction` | `STRING` | Yes | `JUR` | Roadway maintenance jurisdiction code |
| `segment_length_feet` | `FLOAT64` | Yes | `SHAPE.LEN` | Length of roadway segment in survey feet |
| `cur_aadt` | `INT64` | Yes | `CUR_AADT` | Current Annual Average Daily Traffic (all vehicles) |
| `adtt_cur` | `INT64` | Yes | `ADTT_CUR` | Current Average Daily Truck Traffic (heavy freight) |
| `truck_pct` | `FLOAT64` | Yes | `TRK_PCT` | Commercial truck percentage share of total volume |
| `wkt_geometry` | `STRING` | No | `geometry` | WKT `LINESTRING` geometry in EPSG:4326 (WGS84) |
| `geom` | `GEOGRAPHY` | No | *computed* | Native BigQuery GEOGRAPHY LINESTRING |

---

### 3.2 Table: `raw_census_demographics`
Socioeconomic indicators aggregated at the census tract level.

| Column Name | BigQuery Type | Nullable | Source Field | Description |
| :--- | :--- | :--- | :--- | :--- |
| `tract_id` | `STRING` | No | `GEOID` | Full 11-digit Census Tract identifier (Primary Key) |
| `county_fips` | `STRING` | No | `county` | 3-digit state county FIPS code ('041', '043', '075') |
| `tract_fips` | `STRING` | No | `tract` | 6-digit census tract designation |
| `median_household_income`| `INT64` | Yes | `B19013_001E` | ACS estimated median household income (USD) |
| `total_population` | `INT64` | Yes | `B01003_001E` | Total tract resident population |
| `civilian_labor_force` | `INT64` | Yes | `B23025_003E` | Total eligible civilian labor force |
| `unemployed_population` | `INT64` | Yes | `B23025_005E` | Total unemployed civilian individuals |

---

### 3.3 Table: `raw_osm_amenities`
Points of interest capturing commercial competition within the spatial corridor.

| Column Name | BigQuery Type | Nullable | Source Field | Description |
| :--- | :--- | :--- | :--- | :--- |
| `osm_id` | `STRING` | No | `id` | Unique OpenStreetMap node/way identifier |
| `amenity_type` | `STRING` | No | `amenity` | Primary OSM tag classification (`fuel`, `fast_food`) |
| `brand_name` | `STRING` | Yes | `brand` / `name`| Commercial operator name (e.g., Pilot, Sheetz, Love's) |
| `latitude` | `FLOAT64` | No | `lat` | Latitude coordinate in WGS84 |
| `longitude` | `FLOAT64` | No | `lon` | Longitude coordinate in WGS84 |
| `geom` | `GEOGRAPHY` | No | *computed* | Native BigQuery GEOGRAPHY POINT |

---

### 3.4 Table: `raw_nrel_ev_stations`
Alternative fueling infrastructure documenting existing fast-charging access.

| Column Name | BigQuery Type | Nullable | Source Field | Description |
| :--- | :--- | :--- | :--- | :--- |
| `station_id` | `INT64` | No | `id` | Unique AFDC station identifier |
| `station_name` | `STRING` | Yes | `station_name` | Public business name or operating host |
| `ev_network` | `STRING` | Yes | `ev_network` | Charging network (e.g., Tesla, Electrify America) |
| `dc_fast_ports` | `INT64` | No | `ev_dc_fast_num`| Total Level 3 DC Fast Charging ports available |
| `latitude` | `FLOAT64` | No | `latitude` | Latitude coordinate in WGS84 |
| `longitude` | `FLOAT64` | No | `longitude` | Longitude coordinate in WGS84 |
| `geom` | `GEOGRAPHY` | No | *computed* | Native BigQuery GEOGRAPHY POINT |

---

## 4. Silver Tier (Feature Engineering & Scoring)

### 4.1 Table: `silver_high_volume_corridors`
Interstate corridor segments isolated for commercial relevance and enriched with dynamic 1-mile spatial envelopes.

* **Filter Applied:** `route_number = '0081' AND cur_aadt >= 20000`
* **Buffer Generation:** `ST_BUFFER(geom, 1609.34)` (1 statute mile geodesic expansion)

| Column Name | BigQuery Type | Transformation / Derivation |
| :--- | :--- | :--- |
| `object_id` | `INT64` | Direct pass-through from `raw_penndot_traffic` |
| `route_number` | `STRING` | Roadway corridor identifier |
| `county_code` | `STRING` | PennDOT 2-digit jurisdictional code |
| `county_name` | `STRING` | Decoded county name via regional mapping |
| `segment_length_feet` | `FLOAT64` | Physical segment length in feet |
| `cur_aadt` | `INT64` | Average daily traffic (all vehicles) |
| `adtt_cur` | `INT64` | Daily freight volume (heavy trucks) |
| `truck_pct` | `FLOAT64` | Commercial freight share percentage |
| `daily_truck_vmt` | `FLOAT64` | `(adtt_cur * segment_length_feet) / 5280.0` |
| `geom` | `GEOGRAPHY` | LineString geometry of the highway segment |
| `buffer_1mile_geom` | `GEOGRAPHY` | 1-mile surrounding polygon footprint used for spatial joins |

---

### 4.2 Table: `silver_corridor_viability`
The primary feature-engineered analytics table combining demographic aggregations, spatial intersection joins, and the standardized MCDA scoring engine.

#### Multi-Criteria Decision Analysis (MCDA) Scoring Formulation

$$\text{Viability Score} = \min\left(40.0, \frac{\text{adtt\_cur}}{15000} \times 40.0\right) + \min\left(25.0, \frac{\text{truck\_pct}}{50} \times 25.0\right) + \max(0.0, 20.0 - 5.0 \cdot \text{dc\_fast}) + \max(0.0, 15.0 - 5.0 \cdot \text{chains})$$

| Column Name | BigQuery Type | Calculation / Source | Weight / Cap |
| :--- | :--- | :--- | :--- |
| `object_id` | `INT64` | Highway segment identifier | — |
| `route_number` | `STRING` | Interstate route designation | — |
| `county_name` | `STRING` | Host county name | — |
| `cur_aadt` | `INT64` | Baseline highway volume | — |
| `adtt_cur` | `INT64` | Daily truck traffic | Contributes up to 40.0 pts |
| `truck_pct` | `FLOAT64` | Truck concentration percentage | Contributes up to 25.0 pts |
| `competitor_count_1mi` | `INT64` | Total retail amenities within 1-mile buffer | Analytical context |
| `major_chain_count_1mi` | `INT64` | Direct competing travel plazas within buffer | Deducts 5 pts/chain (Max 15 pts) |
| `ev_station_count_1mi` | `INT64` | Total EV stations within buffer | Analytical context |
| `dc_fast_ports_1mi` | `INT64` | Level 3 DC Fast ports within buffer | Deducts 5 pts/port (Max 20 pts) |
| `avg_county_median_income`| `FLOAT64` | County-level mean tract median income | Economic baseline |
| `county_unemployment_rate`| `FLOAT64` | County labor force unemployment rate | Economic baseline |
| `travel_plaza_viability_score`| `FLOAT64` | **Standardized Composite Viability Index** | **0.0 to 100.0 scale** |
| `geom` | `GEOGRAPHY` | Centerline geometry | — |

---

## 5. Gold Tier (Presentation & Analytical Mart)

### 5.1 Table: `gold_travel_plaza_candidates`
The curated final delivery table filtering viable candidates and establishing rank hierarchy for capital allocation.

* **Viability Threshold:** `travel_plaza_viability_score >= 70.0`
* **Ranking Logic:**
  ```sql
  ROW_NUMBER() OVER (
    PARTITION BY county_name
    ORDER BY travel_plaza_viability_score DESC, object_id ASC
  ) AS county_priority_rank