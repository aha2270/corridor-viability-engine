import logging
import requests
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_overpass")

with open("config/pipeline_config.yaml", "r") as f:
    config = yaml.safe_load(f)

mirrors = config["endpoints"].get("overpass_mirrors", [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
])
bbox = config["scope"]["bbox"]  # [-77.45, 40.05, -76.35, 40.65]

# Overpass format: (south, west, north, east)
s, w, n, e = bbox[1], bbox[0], bbox[3], bbox[2]
bbox_str = f"{s},{w},{n},{e}"

# Lightweight node-only query with explicit limit
query = f"""
[out:json][timeout:30];
(
  node["amenity"="fuel"]({bbox_str});
  node["shop"="convenience"]({bbox_str});
);
out body 5;
"""

headers = {
    "User-Agent": "WGU-Capstone-CorridorEngine/1.0 (contact: student@wgu.edu)",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}

data = None
for endpoint in mirrors:
    logger.info(f"Attempting query on Overpass mirror: {endpoint}")
    try:
        response = requests.post(
            endpoint,
            data={"data": query},
            headers=headers,
            timeout=60,
        )
        logger.info(f"HTTP Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            break
        else:
            logger.warning(f"Mirror returned {response.status_code}: {response.text[:120]}")
    except requests.RequestException as e:
        logger.warning(f"Connection to {endpoint} failed: {e}")

if data:
    elements = data.get("elements", [])
    logger.info(f"Successfully retrieved {len(elements)} sample POIs.")
    print("-" * 70)
    for idx, node in enumerate(elements, start=1):
        tags = node.get("tags", {})
        print(f"Node #{idx} (OSM ID: {node.get('id')}):")
        print(f"  Coordinates: [{node.get('lon')}, {node.get('lat')}]")
        print(f"  Name:        {tags.get('name', 'N/A')}")
        print(f"  Brand:       {tags.get('brand', 'N/A')}")
        print(f"  Amenity:     {tags.get('amenity', 'None')}")
        print(f"  Shop:        {tags.get('shop', 'None')}")
        print("-" * 70)
else:
    logger.error("All Overpass mirrors timed out or failed.")