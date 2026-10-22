import os
import requests
import yaml
from dotenv import load_dotenv

load_dotenv()

# Load project configuration
with open("config/pipeline_config.yaml", "r") as f:
    config = yaml.safe_load(f)

base_url = config["endpoints"]["census_api_base"]
county_fips = config["scope"]["census_county_fips"]
variables = config["census_variables"]
api_key = os.getenv("CENSUS_API_KEY")

if not api_key:
    raise ValueError("CENSUS_API_KEY not found in environment or .env file.")

# Test query using Cumberland County (041)
target_county = county_fips[0]
var_list = list(variables.values())
get_param = "NAME," + ",".join(var_list)

params = {
    "get": get_param,
    "for": "tract:*",
    "in": f"state:42 county:{target_county}",
    "key": api_key,
}

headers = {"User-Agent": "WGU-Capstone-CorridorEngine/1.0"}

print(f"Querying US Census API for PA County {target_county}...")
response = requests.get(base_url, params=params, headers=headers, timeout=20)

print(f"HTTP Status: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    headers_row = data[0]
    data_rows = data[1:]
    
    print(f"Successfully retrieved {len(data_rows)} census tracts.")
    print("-" * 70)
    print(f"Raw Column Headers: {headers_row}")
    print("-" * 70)
    
    # Invert variables dict to map code -> semantic name
    code_to_name = {v: k for k, v in variables.items()}
    
    # Display the first 3 sample tracts
    for idx, row in enumerate(data_rows[:3], start=1):
        row_dict = dict(zip(headers_row, row))
        geoid = f"{row_dict.get('state')}{row_dict.get('county')}{row_dict.get('tract')}"
        
        print(f"Tract #{idx}: {row_dict.get('NAME')}")
        print(f"  Composite GEOID: {geoid}")
        for code, semantic_name in code_to_name.items():
            val = row_dict.get(code)
            display_val = "NULL / Suppressed" if (val is None or val.startswith("-")) else f"{int(val):,}"
            print(f"  {semantic_name} ({code}): {display_val}")
        print("-" * 70)
else:
    print(f"Request failed: {response.text}")