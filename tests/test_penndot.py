import pytest
import requests
import yaml

@pytest.fixture(scope="module")
def config():
    with open("config/pipeline_config.yaml", "r") as f:
        return yaml.safe_load(f)

def test_penndot_endpoint_contract(config):
    """Verify PennDOT FeatureServer responds with valid GeoJSON and required attributes."""
    url = config["endpoints"]["penndot_traffic_url"]
    counties = config["scope"]["penndot_county_codes"]
    attributes = config["penndot_attributes"]
    
    where_clause = f"CTY_CODE IN ({', '.join(f'\'{c}\'' for c in counties)}) AND CUR_AADT > 0"
    params = {
        "where": where_clause,
        "outFields": ",".join(attributes),
        "returnGeometry": "true",
        "resultRecordCount": 5,
        "f": "geojson",
    }
    headers = {"User-Agent": "WGU-Capstone-CorridorEngine/1.0"}
    
    response = requests.get(url, params=params, headers=headers, timeout=20)
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    payload = response.json()
    features = payload.get("features", [])
    assert len(features) > 0, "No features returned from query"
    
    # Validate schema contract on first feature
    sample_props = features[0]["properties"]
    for field in ["CUR_AADT", "ADTT_CUR", "TRK_PCT", "ST_RT_NO", "CTY_CODE"]:
        assert field in sample_props, f"Missing required property: {field}"