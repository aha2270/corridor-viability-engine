import os
from pathlib import Path
from dotenv import load_dotenv
from google.cloud import bigquery
import pandas as pd
import pytest

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
DATASET_ID = os.getenv("BQ_DATASET_NAME", "corridor_dw")


@pytest.fixture(scope="session")
def bq_client():
    if not PROJECT_ID:
        pytest.fail("GCP_PROJECT_ID missing from environment or .env file.")
    return bigquery.Client(project=PROJECT_ID)


def test_gold_csv_export_contract():
    """Validates that the Gold mart export exists, is non-empty, and satisfies schema bounds."""
    csv_path = Path("data/processed/gold_travel_plaza_candidates.csv")
    assert csv_path.exists(), f"Processed CSV export missing at {csv_path}"

    df = pd.read_csv(csv_path)
    assert not df.empty, "Gold CSV export contains no candidate records."

    required_columns = {
        "object_id",
        "route_number",
        "county_name",
        "county_priority_rank",
        "segment_length_feet",
        "cur_aadt",
        "adtt_cur",
        "truck_pct",
        "travel_plaza_viability_score",
        "wkt_geometry",
    }
    assert required_columns.issubset(df.columns), f"Missing required columns: {required_columns - set(df.columns)}"

    # Assert standardized 0-100 MCDA bounds
    assert df["travel_plaza_viability_score"].between(0.0, 100.0).all(), "Viability scores fall outside 0-100."


def test_gold_tier_sequential_ranking(bq_client):
    """Confirms no duplicate priority ranks exist per county within the warehouse table."""
    sql = f"""
    SELECT county_name, county_priority_rank, COUNT(1) AS count_records
    FROM `{PROJECT_ID}.{DATASET_ID}.gold_travel_plaza_candidates`
    GROUP BY county_name, county_priority_rank
    HAVING count_records > 1
    """
    duplicates = list(bq_client.query(sql).result())
    assert len(duplicates) == 0, f"Detected duplicate priority ranks: {duplicates}"


def test_interactive_map_artifact():
    """Validates that the self-contained HTML map artifact was compiled."""
    html_path = Path("docs/corridor_viability_map.html")
    assert html_path.exists(), f"Interactive map missing at {html_path}"
    assert html_path.stat().st_size > 10000, "Interactive map artifact is truncated or empty."