import os
import requests
import yaml
from dotenv import load_dotenv

load_dotenv()

with open("config/pipeline_config.yaml", "r") as f:
    config = yaml.safe_load(f)

base_url = config["endpoints"]["nrel_base_url"]
api_key = os.getenv("NREL_API_KEY")

if not api_key:
    raise ValueError("NREL_API_KEY missing from environment or .env file.")

# Query 5 existing public electric charging stations in Pennsylvania
params = {
    "api_key": api_key,
    "status": "E",          # Existing / operational
    "fuel_type": "ELEC",    # Electric vehicle supply equipment
    "state": "PA",
    "access": "public",
    "limit": 5,
}

headers = {"User-Agent": "WGU-Capstone-CorridorEngine/1.0"}

print(f"Querying NLR/AFDC Alt-Fuel API at: {base_url}...")
response = requests.get(base_url, params=params, headers=headers, timeout=20)

print(f"HTTP Status: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    stations = data.get("fuel_stations", [])
    print(f"Successfully retrieved {len(stations)} sample stations.")
    print("-" * 70)
    for idx, station in enumerate(stations, start=1):
        print(f"Station #{idx}: {station.get('station_name')}")
        print(f"  Station ID:     {station.get('id')}")
        print(f"  Location:       {station.get('city')}, {station.get('state')} {station.get('zip')}")
        print(f"  Coordinates:    [{station.get('longitude')}, {station.get('latitude')}]")
        print(f"  EV Network:     {station.get('ev_network')}")
        print(f"  Level 2 Ports:  {station.get('ev_level2_evse_num')}")
        print(f"  DC Fast Ports:  {station.get('ev_dc_fast_num')}")
        print(f"  Facility Type:  {station.get('facility_type')}")
        print("-" * 70)
else:
    print(f"Request failed: {response.status_code} - {response.text}")