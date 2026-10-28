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
logger = logging.getLogger("extract_nrel")


def load_config(config_path: str = "config/pipeline_config.yaml") -> Dict[str, Any]:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def fetch_and_filter_ev_stations(
    endpoint: str,
    api_key: str,
    bbox: List[float],
) -> Dict[str, Any]:
    """
    Extracts operational public EV charging stations from the NLR API
    and filters records spatially to the corridor bounding box.
    """
    min_lon, min_lat, max_lon, max_lat = bbox

    params = {
        "api_key": api_key,
        "status": "E",
        "fuel_type": "ELEC",
        "state": "PA",
        "access": "public",
        "limit": "all",
    }
    headers = {"User-Agent": "WGU-Capstone-CorridorEngine/1.0"}

    logger.info(f"Querying NLR Alt-Fuel endpoint: {endpoint}...")
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

    raw_stations = response.json().get("fuel_stations", [])
    logger.info(f"Retrieved {len(raw_stations)} total public EV stations across Pennsylvania.")

    features = []
    for station in raw_stations:
        lat = station.get("latitude")
        lon = station.get("longitude")

        if lat is None or lon is None:
            continue

        lat = float(lat)
        lon = float(lon)

        # Spatial filter to corridor bounding box
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            feature = {
                "type": "Feature",
                "id": station.get("id"),
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat],
                },
                "properties": {
                    "station_id": station.get("id"),
                    "station_name": station.get("station_name"),
                    "street_address": station.get("street_address"),
                    "city": station.get("city"),
                    "state": station.get("state"),
                    "zip": station.get("zip"),
                    "ev_network": station.get("ev_network"),
                    "ev_pricing": station.get("ev_pricing"),
                    "level2_ports": station.get("ev_level2_evse_num") or 0,
                    "dc_fast_ports": station.get("ev_dc_fast_num") or 0,
                    "facility_type": station.get("facility_type"),
                    "access_days_time": station.get("access_days_time"),
                },
            }
            features.append(feature)

    logger.info(f"Filtered down to {len(features)} EV stations within corridor bounding box.")

    return {
        "type": "FeatureCollection",
        "metadata": {
            "source": "National Laboratory of the Rockies (NLR / AFDC)",
            "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "bbox": bbox,
            "total_features": len(features),
        },
        "features": features,
    }


def upload_to_gcs(local_file_path: Path, bucket_name: str, destination_blob_name: str) -> None:
    logger.info(f"Uploading {local_file_path} to gs://{bucket_name}/{destination_blob_name}...")
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(str(local_file_path))
    logger.info("GCS upload complete.")


def run():
    config = load_config()
    endpoint = config["endpoints"]["nrel_base_url"]
    bbox = config["scope"]["bbox"]

    api_key = os.getenv("NREL_API_KEY")
    if not api_key:
        raise ValueError("NREL_API_KEY missing from .env")

    bucket_name = os.getenv("GCS_BUCKET_NAME")
    if not bucket_name:
        raise ValueError("GCS_BUCKET_NAME missing from .env")

    # 1. Fetch & Filter
    geojson_payload = fetch_and_filter_ev_stations(endpoint, api_key, bbox)

    # 2. Local Save
    raw_dir = Path("data/raw")
    raw_dir.mkdir(parents=True, exist_ok=True)
    local_output = raw_dir / "nrel_ev_stations.geojson"

    with open(local_output, "w", encoding="utf-8") as f:
        json.dump(geojson_payload, f, ensure_ascii=False)
    logger.info(f"Saved {len(geojson_payload['features'])} EV stations to {local_output}")

    # 3. Stream to GCS Bronze Bucket
    blob_name = f"bronze/nrel/ev_stations_pa_corridor_{time.strftime('%Y%m%d')}.geojson"
    upload_to_gcs(local_output, bucket_name, blob_name)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    run()