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
logger = logging.getLogger("extract_penndot")


def load_config(config_path: str = "config/pipeline_config.yaml") -> Dict[str, Any]:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def fetch_penndot_corridor_data(
    endpoint: str,
    county_codes: List[str],
    attributes: List[str],
    batch_size: int = 1000,
) -> Dict[str, Any]:
    """
    Paginates through PennDOT ArcGIS REST API to collect all roadway segments
    matching target county codes and valid traffic counts.
    """
    formatted_counties = ", ".join(f"'{c}'" for c in county_codes)
    where_clause = f"CTY_CODE IN ({formatted_counties}) AND CUR_AADT > 0"
    out_fields = ",".join(attributes)

    headers = {"User-Agent": "WGU-Capstone-CorridorEngine/1.0"}
    all_features = []
    offset = 0

    while True:
        params = {
            "where": where_clause,
            "outFields": out_fields,
            "returnGeometry": "true",
            "resultOffset": offset,
            "resultRecordCount": batch_size,
            "f": "geojson",
        }

        logger.info(f"Querying PennDOT records: offset {offset} (batch size {batch_size})...")
        retries = 3
        response = None
        for attempt in range(retries):
            try:
                response = requests.get(endpoint, params=params, headers=headers, timeout=45)
                response.raise_for_status()
                break
            except requests.RequestException as exc:
                logger.warning(f"Request failed (attempt {attempt + 1}/{retries}): {exc}")
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)

        payload = response.json()
        features = payload.get("features", [])
        if not features:
            logger.info("No further records returned from endpoint.")
            break

        all_features.extend(features)
        logger.info(f"Retrieved {len(features)} segments. Total so far: {len(all_features)}")

        # If batch returned fewer records than the limit, we have reached the end
        if len(features) < batch_size:
            break

        offset += batch_size

    geojson_collection = {
        "type": "FeatureCollection",
        "metadata": {
            "source": "PennDOT RMS Roadway Traffic",
            "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "counties": county_codes,
            "total_features": len(all_features),
        },
        "features": all_features,
    }
    return geojson_collection


def upload_to_gcs(local_file_path: Path, bucket_name: str, destination_blob_name: str) -> None:
    """Uploads extracted raw artifact to GCS bronze landing bucket."""
    logger.info(f"Uploading {local_file_path} to gs://{bucket_name}/{destination_blob_name}...")
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(str(local_file_path))
    logger.info("GCS upload complete.")


def run():
    config = load_config()
    endpoint = config["endpoints"]["penndot_traffic_url"]
    county_codes = config["scope"]["penndot_county_codes"]
    attributes = config["penndot_attributes"]

    bucket_name = os.getenv("GCS_BUCKET_NAME")
    if not bucket_name:
        raise ValueError("GCS_BUCKET_NAME environment variable not set in .env")

    # 1. Fetch all corridor data with pagination
    geojson_payload = fetch_penndot_corridor_data(endpoint, county_codes, attributes)

    # 2. Persist locally to bronze landing folder
    raw_dir = Path("data/raw")
    raw_dir.mkdir(parents=True, exist_ok=True)
    local_output = raw_dir / "penndot_traffic.geojson"

    with open(local_output, "w", encoding="utf-8") as f:
        json.dump(geojson_payload, f, ensure_ascii=False)
    logger.info(f"Saved {len(geojson_payload['features'])} roadway segments to {local_output}")

    # 3. Stream to GCS Bronze Bucket
    blob_name = f"bronze/penndot/traffic_pa_corridor_{time.strftime('%Y%m%d')}.geojson"
    upload_to_gcs(local_output, bucket_name, blob_name)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    run()