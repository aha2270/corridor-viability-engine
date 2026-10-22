import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Dict, List
from google.cloud import storage
import requests
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("extract_census")


def load_config(config_path: str = "config/pipeline_config.yaml") -> Dict[str, Any]:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def fetch_census_tract_data(
    base_url: str,
    api_key: str,
    county_fips: List[str],
    variables: Dict[str, str],
    state_fips: str = "42",
) -> List[Dict[str, Any]]:
    """
    Extracts census tract demographic variables for specified counties.
    Transforms raw 2D array output into structured dictionaries with unified GEOIDs.
    """
    var_list = list(variables.values())
    get_param = "NAME," + ",".join(var_list)
    headers = {"User-Agent": "WGU-Capstone-CorridorEngine/1.0"}
    all_tract_records = []

    for county in county_fips:
        logger.info(f"Querying Census ACS5 for PA County FIPS: {county}...")
        params = {
            "get": get_param,
            "for": "tract:*",
            "in": f"state:{state_fips} county:{county}",
            "key": api_key,
        }

        retries = 3
        response = None
        for attempt in range(retries):
            try:
                response = requests.get(base_url, params=params, headers=headers, timeout=30)
                response.raise_for_status()
                break
            except requests.RequestException as exc:
                logger.warning(f"Census API request failed for county {county} (attempt {attempt + 1}/{retries}): {exc}")
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)

        raw_rows = response.json()
        if not raw_rows or len(raw_rows) < 2:
            logger.warning(f"No records returned for county {county}")
            continue

        column_headers = raw_rows[0]
        data_rows = raw_rows[1:]

        # Map inverted variable codes back to semantic column keys
        var_to_name = {v: k for k, v in variables.items()}

        for row in data_rows:
            record_raw = dict(zip(column_headers, row))
            state = record_raw.get("state", "")
            cty = record_raw.get("county", "")
            tract = record_raw.get("tract", "")
            geoid = f"{state}{cty}{tract}"

            record = {
                "geoid": geoid,
                "tract_name": record_raw.get("NAME"),
                "state_fips": state,
                "county_fips": cty,
                "tract_code": tract,
            }

            for code, semantic_name in var_to_name.items():
                raw_val = record_raw.get(code)
                # Handle Census null/sentinel indicators (e.g. -666666666)
                if raw_val is None or raw_val.startswith("-"):
                    record[semantic_name] = None
                else:
                    record[semantic_name] = int(raw_val)

            all_tract_records.append(record)

        logger.info(f"Retrieved {len(data_rows)} tracts for county {county}.")

    return all_tract_records


def upload_to_gcs(local_file_path: Path, bucket_name: str, destination_blob_name: str) -> None:
    """Streams extracted bronze artifact to Cloud Storage."""
    logger.info(f"Uploading {local_file_path} to gs://{bucket_name}/{destination_blob_name}...")
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(str(local_file_path))
    logger.info("GCS upload complete.")


def run():
    config = load_config()
    census_base = config["endpoints"]["census_api_base"]
    county_fips = config["scope"]["census_county_fips"]
    variables = config["census_variables"]

    api_key = os.getenv("CENSUS_API_KEY")
    if not api_key:
        raise ValueError("CENSUS_API_KEY missing from .env")

    bucket_name = os.getenv("GCS_BUCKET_NAME")
    if not bucket_name:
        raise ValueError("GCS_BUCKET_NAME missing from .env")

    # 1. Fetch Demographics
    records = fetch_census_tract_data(census_base, api_key, county_fips, variables)

    # 2. Save locally
    raw_dir = Path("data/raw")
    raw_dir.mkdir(parents=True, exist_ok=True)
    local_output = raw_dir / "census_tracts_demographics.json"

    with open(local_output, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
    logger.info(f"Saved {len(records)} total census tracts to {local_output}")

    # 3. Stream to GCS Bronze Bucket
    blob_name = f"bronze/census/demographics_pa_corridor_{time.strftime('%Y%m%d')}.json"
    upload_to_gcs(local_output, bucket_name, blob_name)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    run()