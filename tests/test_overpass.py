import requests

query = """
[out:json][timeout:25];
(
  node["amenity"="fuel"](40.05,-77.45,40.65,-76.35);
  node["shop"="convenience"](40.05,-77.45,40.65,-76.35);
);
out body 5;
"""

url = "https://overpass-api.de/api/interpreter"
headers = {"User-Agent": "WGU-Capstone-CorridorEngine/1.0"}

response = requests.post(url, data={"data": query}, headers=headers)
print("HTTP Status Code:", response.status_code)

if response.status_code == 200:
    elements = response.json().get("elements", [])
    print(f"Success! Retrieved {len(elements)} sample nodes.")
    if elements:
        print("Sample node tag data:", elements[0].get("tags"))
else:
    print("Error:", response.text)