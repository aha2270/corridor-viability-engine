import json
import requests

PENNDOT_URL = (
    "https://gis.penndot.pa.gov/arcgis/rest/services/opendata/roadwaytraffic/MapServer/0/query"
)

# Targeted attributes defined during schema inspection
OUT_FIELDS = [
    "OBJECTID",
    "ST_RT_NO",
    "CTY_CODE",
    "SEG_LNGTH_FEET",
    "CUR_AADT",
    "ADTT_CUR",
    "TRK_PCT",
    "DLY_TRK_VMT",
]

# Query parameters for Cumberland (21), Dauphin (22), and Lebanon (38)
params = {
    "where": "CTY_CODE IN ('21', '22', '38') AND CUR_AADT > 0",
    "outFields": ",".join(OUT_FIELDS),
    "returnGeometry": "true",
    "resultRecordCount": 5,
    "f": "geojson",
}

headers = {"User-Agent": "WGU-Capstone-CorridorEngine/1.0"}

print(f"Querying PennDOT Feature Layer: {PENNDOT_URL}...")
response = requests.get(PENNDOT_URL, params=params, headers=headers, timeout=20)

print(f"HTTP Status: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    features = data.get("features", [])
    print(f"\nSuccessfully retrieved {len(features)} sample records.")
    print("-" * 70)

    for idx, feature in enumerate(features, start=1):
        props = feature.get("properties", {})
        geometry = feature.get("geometry", {})
        coords = geometry.get("coordinates", [])

        print(f"Record #{idx}:")
        print(f"  Route: SR {props.get('ST_RT_NO')}")
        print(f"  County Code: {props.get('CTY_CODE')}")
        print(f"  Segment Length (ft): {props.get('SEG_LNGTH_FEET')}")
        print(f"  Current AADT: {props.get('CUR_AADT'):,}")
        print(f"  Daily Truck Volume: {props.get('ADTT_CUR'):,}")
        print(f"  Truck Percentage: {props.get('TRK_PCT')}%")
        print(f"  Daily Truck VMT: {props.get('DLY_TRK_VMT'):,}")
        print(f"  Geometry Type: {geometry.get('type')}")
        print(f"  Coordinate Vertices: {len(coords)} points")
        if coords:
            print(f"  Start Vertex: {coords[0]}")
            print(f"  End Vertex:   {coords[-1]}")
        print("-" * 70)
else:
    print(f"Request failed: {response.text}")