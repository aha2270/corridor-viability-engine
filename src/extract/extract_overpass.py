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
logger = logging.getLogger("extract_overpass")


def load_config(config_path: str = "config/pipeline_config.yaml") -> Dict[str, Any]:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def fetch_osm_corridor_amenities(
    mirrors: List[str],
    bbox: List[float],
) -> Dict[str, Any]:
    s, w, n, e = bbox[1], bbox[0], bbox[3], bbox[2]
    bbox_str = f"{s},{w},{n},{e}"

    query = f"""
    [out:json][timeout:60];
    (
      node["amenity"="fuel"]({bbox_str});
      node["shop"="convenience"]({bbox_str});
    );
    out body;
    """

    headers = {
        "User-Agent": "WGU-Capstone-CorridorEngine/1.0 (contact: student@wgu.edu)",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }

    payload = None
    for endpoint in mirrors:
        logger.info(f"Attempting full Overpass extraction against {endpoint}...")
        try:
            response = requests.post(
                endpoint,
                data={"data": query},
                headers=headers,
                timeout=90,
            )
            if response.status_code == 200:
                payload = response.json()
                logger.info(f"Successfully retrieved data from {endpoint}.")
                break
            else:
                logger.warning(f"Mirror {endpoint} returned status {response.status_code}.")
        except requests.RequestException as err:
            logger.warning(f"Mirror {endpoint} connection failed: {err}")

    if not payload:
        raise RuntimeError("All Overpass mirrors failed to return corridor amenities.")

    elements = payload.get("elements", [])
    logger.info(f"Processing {len(elements)} raw POIs into GeoJSON...")

    features = []
    for elem in elements:
        lat = elem.get("lat")
        lon = elem.get("lon")
        if lat is None or lon is None:
            continue

        tags = elem.get("tags", {})
        feature = {
            "type": "Feature",
            "id": elem.get("id"),
            "geometry": {
                "type": "Point",
                "coordinates": [float(lon), float(lat)],
            },
            "properties": {
                "osm_id": elem.get("id"),
                "name": tags.get("name"),
                "brand": tags.get("brand"),
                "operator": tags.get("operator"),
                "amenity": tags.get("amenity"),
                "shop": tags.get("shop"),
                "hgv": tags.get("hgv"),
            },
        }
        features.append(feature)

    return {
        "type": "FeatureCollection",
        "metadata": {
            "source": "OpenStreetMap Overpass API",
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
    mirrors = config["endpoints"].get("overpass_mirrors", [
        "https://overpass-api.de/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ])
    bbox = config["scope"]["bbox"]

    bucket_name = os.getenv("GCS_BUCKET_NAME")
    if not bucket_name:
        raise ValueError("GCS_BUCKET_NAME missing from .env")

    # 1. Fetch & Transform
    geojson_payload = fetch_osm_corridor_amenities(mirrors, bbox)

    # 2. Local Save
    raw_dir = Path("data/raw")
    raw_dir.mkdir(parents=True, exist_ok=True)
    local_output = raw_dir / "osm_competitor_amenities.geojson"

    with open(local_output, "w", encoding="utf-8") as f:
        json.dump(geojson_payload, f, ensure_ascii=False)
    logger.info(f"Saved {len(geojson_payload['features'])} features to {local_output}")

    # 3. GCS Bronze Ingestion
    blob_name = f"bronze/osm/amenities_pa_corridor_{time.strftime('%Y%m%d')}.geojson"
    upload_to_gcs(local_output, bucket_name, blob_name)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    run()