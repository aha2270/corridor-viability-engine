import logging
from pathlib import Path
import folium
from folium import plugins
import pandas as pd
from shapely import wkt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("generate_interactive_map")


def build_corridor_map(
    csv_path: Path,
    output_html_path: Path,
):
    logger.info(f"Loading gold candidate data from {csv_path}...")
    df = pd.read_csv(csv_path)

    # Initialize map centered on Harrisburg / PA Capital Region corridor
    center_lat, center_lon = 40.2732, -76.8867
    
    # Initialize base map with None to bind custom tile provider
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=10,
        tiles=None,
    )

    # Esri World Street Map: Clean, high-performance, and permits local file rendering
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Esri, USGS, PennDOT, Garmin, © OpenStreetMap contributors",
        name="Esri World Street Map",
        control=True,
    ).add_to(m)

    # Distinct high-contrast colors per county
    county_colors = {
        "Cumberland": "#0056b3",  # Deep Blue
        "Dauphin": "#d9534f",     # Coral Red
        "Lebanon": "#2e7d32",     # Forest Green
    }

    feature_group_candidates = folium.FeatureGroup(name="Viable Corridors (Gold Tier)")

    for _, row in df.iterrows():
        geom_wkt = row.get("wkt_geometry")
        if not geom_wkt or pd.isna(geom_wkt):
            continue

        shape = wkt.loads(geom_wkt)
        county = row["county_name"]
        color = county_colors.get(county, "#333333")

        popup_html = f"""
        <div style="font-family: Arial, sans-serif; font-size: 12px; width: 230px;">
            <h4 style="margin: 0 0 6px 0; color: #111;">Route {row['route_number']} ({county})</h4>
            <b>County Priority Rank:</b> #{row['county_priority_rank']}<br/>
            <b>Viability Score:</b> {row['travel_plaza_viability_score']} / 100<br/>
            <hr style="margin: 6px 0; border: 0; border-top: 1px solid #ccc;"/>
            <b>Daily Freight (ADTT):</b> {int(row['adtt_cur']):,} trucks<br/>
            <b>Truck Share:</b> {row['truck_pct']}%<br/>
            <b>Total AADT:</b> {int(row['cur_aadt']):,}<br/>
            <b>Segment Length:</b> {round(row['segment_length_feet'] / 5280, 2)} mi<br/>
            <hr style="margin: 6px 0; border: 0; border-top: 1px solid #ccc;"/>
            <b>Competitor Amenities (1-mi):</b> {row['competitor_count_1mi']}<br/>
            <b>DC Fast Ports (1-mi):</b> {row['dc_fast_ports_1mi']}<br/>
        </div>
        """

        if shape.geom_type == "LineString":
            lat_lon_coords = [(pt[1], pt[0]) for pt in shape.coords]
            folium.PolyLine(
                locations=lat_lon_coords,
                color=color,
                weight=6,
                opacity=0.9,
                tooltip=f"Rank #{row['county_priority_rank']} - Route {row['route_number']} ({county}) - Score: {row['travel_plaza_viability_score']}",
                popup=folium.Popup(popup_html, max_width=300),
            ).add_to(feature_group_candidates)

    feature_group_candidates.add_to(m)

    # Map controls
    folium.LayerControl(collapsed=False).add_to(m)
    plugins.Fullscreen().add_to(m)

    output_html_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(output_html_path))
    logger.info(f"Interactive corridor viability map saved to: {output_html_path}")


def run():
    input_csv = Path("data/processed/gold_travel_plaza_candidates.csv")
    output_html = Path("docs/corridor_viability_map.html")
    build_corridor_map(input_csv, output_html)


if __name__ == "__main__":
    run()