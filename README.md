# Corridor Viability Engine: Automated Geospatial Data Pipeline for Travel Plaza Site Optimization

[![Tests](https://img.shields.io/badge/pytest-passing-brightgreen.svg)](#testing--verification)
[![Python](https://img.shields.io/badge/python-3.13-blue.svg)](#environment--prerequisites)
[![GCP](https://img.shields.io/badge/GCP-BigQuery%20%7C%20GCS-orange.svg)](#architecture--medallion-design)

An enterprise-grade, automated geospatial data engineering pipeline built to evaluate and rank highway corridor segments for commercial travel plaza development. Utilizing a Medallion Architecture across Google Cloud Platform (Google Cloud Storage and BigQuery) and Python, the engine extracts, transforms, scores, and visualizes multimodal freight, demographic, and infrastructure datasets across Pennsylvania interstate corridors.

Developed as the Capstone Project for the Master of Science in Data Engineering program at Western Governors University (WGU).

---

## Table of Contents

- [Business Problem & Solution](#business-problem--solution)
- [Architecture & Medallion Design](#architecture--medallion-design)
- [Multi-Criteria Decision Analysis (MCDA) Scoring](#multi-criteria-decision-analysis-mcda-scoring)
- [Repository Structure](#repository-structure)
- [Environment & Prerequisites](#environment--prerequisites)
- [Installation & Setup](#installation--setup)
- [Pipeline Execution](#pipeline-execution)
- [Testing & Verification](#testing--verification)
- [Interactive Visualization](#interactive-visualization)
- [Data Dictionary & Documentation](#data-dictionary--documentation)

---

## Business Problem & Solution

Commercial travel plaza developers and fleet fueling networks face substantial capital risk when selecting locations for new multi-acre facilities. Traditional site selection relies on fragmented municipal traffic counts, static competitor lists, and manual desktop review. This approach leads to sub-optimal capital allocation, overlooked freight corridors, and unmitigated exposure to competitor saturation or infrastructure voids.

The **Corridor Viability Engine** solves this challenge by operationalizing an automated, reproducible data engineering pipeline that:
1. Ingests heterogeneous data streams (state DOT freight volumes, Census socioeconomic profiles, OpenStreetMap competitor points of interest, and NREL electric vehicle infrastructure).
2. Normalizes, validates, and buffers spatial geometries inside a cloud data warehouse (Google BigQuery).
3. Applies a standardized 0–100 Multi-Criteria Decision Analysis (MCDA) index to score commercial viability.
4. Produces deduplicated, ranked priority corridors exported to analytical flat files and interactive, colorblind-safe cartographic dashboards.

---

## Architecture & Medallion Design

The pipeline follows a tiered **Medallion Data Architecture** orchestrated via Python and backed by Google Cloud Platform:

```
[ External APIs ]
  │  ├── PennDOT RMS Open Data (ArcGIS REST)
  │  ├── U.S. Census Bureau API (ACS 5-Year)
  │  ├── OpenStreetMap (Overpass QL API)
  │  └── NREL Alternative Fuels Data Center API
  ▼
[ Bronze Tier (Storage) ] ──────── gs://corridor-viability-engine-data/bronze/
  │  └── Raw, immutable JSON & GeoJSON snapshots with execution run timestamps
  ▼
[ Staging / Raw Layer (BigQuery) ]
  │  ├── raw_penndot_traffic (LineString geometries & AADT/ADTT metrics)
  │  ├── raw_census_demographics (Tract-level income & labor data)
  │  ├── raw_osm_amenities (Point geometries & competitor retail brands)
  │  └── raw_nrel_ev_stations (Point geometries & DC Fast port counts)
  ▼
[ Silver Tier (Feature Engineering) ]
  │  ├── silver_high_volume_corridors (1-mile geodesic ST_BUFFER envelopes)
  │  ├── silver_amenities (Flagged competitor brands)
  │  └── silver_corridor_viability (Spatial ST_INTERSECTS joins & 0-100 MCDA scoring)
  ▼
[ Gold Tier (Analytical Mart) ]
  │  └── gold_travel_plaza_candidates (Ranked corridors, score >= 70.0)
  ▼
[ Presentation & Artifacts ]
  ├── data/processed/gold_travel_plaza_candidates.csv (Flat file export)
  └── docs/corridor_viability_map.html (Standalone Folium/Leaflet application)
```

The system architecture diagram is available at `docs/architecture_diagram.png`.

---

## Multi-Criteria Decision Analysis (MCDA) Scoring

Corridor viability is evaluated using an objective, 100-point multi-criteria index calculated natively within BigQuery SQL:

```text
Viability Score = MIN(40.0, (adtt_cur / 15000.0) * 40.0)
                + MIN(25.0, (truck_pct / 50.0) * 25.0)
                + MAX(0.0, 20.0 - (dc_fast_ports * 5.0))
                + MAX(0.0, 15.0 - (major_chains * 5.0))
```

### Weight Distribution & Justification
- **Heavy Truck Volume (ADTT) — 40 Points (Max):** Commercial travel plazas require sustained diesel fleet demand. Linear scaling reaches maximum score at 15,000+ daily trucks.
- **Commercial Vehicle Share (Truck %) — 25 Points (Max):** Higher commercial traffic share indicates a dedicated logistics corridor rather than commuter traffic. Scales to max score at 50% truck share.
- **EV Fast Charging Deficit — 20 Points (Max):** High scores reward corridor voids lacking National Electric Vehicle Infrastructure (NEVI) compliant DC Fast Charging. Corridors receive 20 points for 0 ports, penalizing 5 points per existing port down to 0.
- **Retail Competitor Gap — 15 Points (Max):** Evaluates brand saturation within a 1-mile spatial buffer. Corridors receive 15 points if 0 major competing travel plazas exist, decreasing by 5 points per competing chain down to 0.

---

## Repository Structure

```
corridor-viability-engine/
├── config/
│   ├── pipeline_config.yaml         # Parameterized scope, FIPS codes, and bounding boxes
│   └── service_account.json.example # GCP IAM credential template
├── data/
│   ├── raw/                         # Local landing cache (Bronze staging)
│   └── processed/
│       └── gold_travel_plaza_candidates.csv # Curated, ranked delivery export
├── docs/
│   ├── architecture_diagram.png     # System architecture diagram
│   ├── corridor_viability_map.html  # Standalone interactive Folium application
│   └── data_dictionary.md           # Schema definitions and data contracts
├── src/
│   ├── extract/
│   │   ├── extract_census.py        # U.S. Census Bureau ACS demographic ingestion
│   │   ├── extract_nrel.py          # NREL Alternative Fuels Data Center ingestion
│   │   ├── extract_overpass.py      # OpenStreetMap Overpass retail ingestion
│   │   └── extract_penndot.py       # PennDOT RMS traffic geometry ingestion
│   ├── load/
│   │   └── load_bronze_to_bq.py     # Schema-enforced GCS/Local to BigQuery loading
│   ├── transform/
│   │   ├── transform_silver.py      # Spatial buffering, joins, and MCDA scoring
│   │   └── transform_gold.py        # Filtering, deduplication, and ranking mart
│   └── visualize/
│       └── generate_interactive_map.py # Folium map compiler with JavaScript bridge
├── tests/
│   └── test_pipeline_integration.py # Automated pytest test suite
├── .gitignore                       # Credentials, cache, and raw data exclusions
├── LICENSE                          # MIT License
├── main.py                          # Unified end-to-end master pipeline runner
├── README.md                        # Project documentation
└── requirements.txt                 # Frozen Python dependencies
```

---

## Environment & Prerequisites

- **Python:** Version 3.10+ (tested on Python 3.13)
- **Google Cloud Platform:**
  - Active GCP Project with billing enabled.
  - BigQuery API and Cloud Storage API enabled.
  - Service Account with `BigQuery Admin` and `Storage Admin` roles.
- **External API Keys:**
  - NREL Developer API Key ([Sign up via NREL](https://developer.nrel.gov/signup/))
  - U.S. Census Bureau API Key ([Sign up via Census.gov](https://api.census.gov/data/key_signup.html))

---

## Installation & Setup

1. **Clone the Repository:**
   ```powershell
   git clone [https://github.com/](https://github.com/)<your-username>/corridor-viability-engine.git
   cd corridor-viability-engine
   ```

2. **Create and Activate a Virtual Environment:**
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

3. **Install Dependencies:**
   ```powershell
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables:**
   Create a `.env` file in the root directory:
   ```env
   # Google Cloud Configuration
   GCP_PROJECT_ID=your-gcp-project-id
   BQ_DATASET_NAME=corridor_dw
   GCS_BUCKET_NAME=your-gcs-bucket-name
   GOOGLE_APPLICATION_CREDENTIALS=config/service_account.json

   # External Data API Keys
   NREL_API_KEY=your_nrel_api_key_here
   CENSUS_API_KEY=your_census_api_key_here
   ```

5. **Place GCP Credentials:**
   Ensure your service account key file is located at the path defined in `GOOGLE_APPLICATION_CREDENTIALS` (e.g., `config/service_account.json`). Note that `.gitignore` strictly prevents committing this file.

---

## Pipeline Execution

Execute the entire end-to-end pipeline with a single command:

```powershell
python main.py
```

### Execution Flow
1. **Bronze Ingestion:** Fetches data from PennDOT, Census, OpenStreetMap, and NREL, writing raw snapshots to local cache and Google Cloud Storage.
2. **Raw Staging:** Loads Bronze datasets into schema-enforced BigQuery tables (`raw_*`).
3. **Silver Transformation:** Executes spatial buffering (`ST_BUFFER`), spatial intersection joins (`ST_INTERSECTS`), and calculates the 0–100 MCDA score.
4. **Gold Mart Aggregation:** Filters high-viability corridors ($\ge 70.0$), computes sequential `ROW_NUMBER()` county priority rankings, and exports results to `data/processed/gold_travel_plaza_candidates.csv`.
5. **Presentation Generation:** Compiles the self-contained interactive map into `docs/corridor_viability_map.html`.

---

## Testing & Verification

The project includes an automated integration test suite validating data contracts, warehouse integrity, scoring boundaries, and output artifact completeness.

Run the test suite using pytest:

```powershell
python -m pytest -v
```

### Verified Test Contracts
- `test_gold_csv_export_contract`: Verifies that the processed CSV export exists, contains valid candidate records, satisfies required schema attributes, and complies with bounded 0–100 score limits.
- `test_gold_tier_sequential_ranking`: Executes a SQL query against BigQuery confirming that county priority rankings (`county_priority_rank`) are strictly unique and non-duplicated.
- `test_interactive_map_artifact`: Validates the physical generation and file size integrity of the standalone HTML visualization deliverable.

---

## Interactive Visualization

The presentation layer compiles into a standalone, browser-executable GIS application located at `docs/corridor_viability_map.html`.

### Features
- **Base Layer:** High-contrast Esri World Street Map tiles.
- **Cartographic Encoding:** Uses the **Viridis** perceptual colormap (yellow = highest viability, teal = moderate, deep indigo = baseline). Viridis is mathematically uniform and colorblind-safe (accessible for deuteranopia and protanopia).
- **Directional Highway Fidelity:** Visualizes opposing interstate carriageways (Northbound and Southbound centerlines) with crisp, non-overlapping line weights.
- **Bidirectional Leaderboard:** A floating sidebar displays ranked corridor segments. Hovering over a leaderboard entry highlights the corresponding highway segment on the map in neon magenta; clicking an entry smoothly flies the camera to the segment center and triggers its detailed metrics popup.

To view the dashboard, open `docs/corridor_viability_map.html` in any modern web browser.

---

## Data Dictionary & Documentation

- **Data Dictionary:** Complete schema contracts, SQL data types, field definitions, and mathematical formulations are documented in [`docs/data_dictionary.md`](docs/data_dictionary.md).
- **Architecture Diagram:** Visual system layout is provided in [`docs/architecture_diagram.png`](docs/architecture_diagram.png).