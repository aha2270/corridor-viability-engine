import json
import logging
from pathlib import Path
import folium
from folium import plugins
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import pandas as pd
from shapely import wkt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("generate_interactive_map")


def build_corridor_map(csv_path: Path, output_html_path: Path):
    logger.info(f"Loading gold candidate data from {csv_path}...")
    df = pd.read_csv(csv_path)

    if df.empty:
        logger.warning("No candidate data found to plot.")
        return

    df = df.dropna(subset=["wkt_geometry"]).copy()
    df["shape"] = df["wkt_geometry"].apply(wkt.loads)

    all_lats, all_lons = [], []
    for geom in df["shape"]:
        if geom.geom_type == "LineString":
            for lon, lat in geom.coords:
                all_lons.append(lon)
                all_lats.append(lat)

    center_lat = sum(all_lats) / len(all_lats)
    center_lon = sum(all_lons) / len(all_lons)

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=11,
        tiles=None,
    )

    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Esri, USGS, PennDOT, Garmin, © OpenStreetMap contributors",
        name="Esri World Street Map",
        control=True,
    ).add_to(m)

    min_score = df["travel_plaza_viability_score"].min()
    max_score = df["travel_plaza_viability_score"].max()
    if min_score == max_score:
        min_score -= 1.0

    cmap = plt.get_cmap("viridis")
    norm = mcolors.Normalize(vmin=min_score, vmax=max_score)

    feature_group = folium.FeatureGroup(name="Ranked Corridors (Viridis Scale)")

    df_desc = df.sort_values(by="travel_plaza_viability_score", ascending=False).reset_index(drop=True)

    leaderboard_items_html = ""
    color_registry = {}

    for idx, row in df_desc.iterrows():
        score = float(row["travel_plaza_viability_score"])
        rgba = cmap(norm(score))
        hex_color = mcolors.to_hex(rgba)
        obj_id = str(row["object_id"])
        overall_rank = idx + 1
        color_registry[obj_id] = hex_color

        leaderboard_items_html += f"""
        <div id="leaderboard-item-{obj_id}"
             class="leaderboard-row"
             onclick="focusSegment('{obj_id}')"
             onmouseenter="highlightSegment('{obj_id}')"
             onmouseleave="resetSegment('{obj_id}')"
             title="Click to center corridor segment"
             style="display: flex; justify-content: space-between; align-items: center; padding: 5px 4px; border-bottom: 1px solid #eee; font-size: 11px; cursor: pointer; transition: background 0.15s ease;">
            <div style="display: flex; align-items: center;">
                <span id="dot-{obj_id}" style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background-color: {hex_color}; margin-right: 6px;"></span>
                <b>#{overall_rank}</b>&nbsp;Rte {row['route_number']}&nbsp;<span style="color: #666;">({row['county_name'][:4]}.)</span>
            </div>
            <div>
                <span style="font-weight: bold; color: #222;">{score:.1f}</span><span style="color: #888;">/100</span>
            </div>
        </div>
        """

    df_asc = df_desc.iloc[::-1]
    for _, row in df_asc.iterrows():
        shape = row["shape"]
        score = float(row["travel_plaza_viability_score"])
        rgba = cmap(norm(score))
        hex_color = mcolors.to_hex(rgba)
        obj_id = str(row["object_id"])

        popup_html = f"""
        <div style="font-family: Arial, sans-serif; font-size: 12px; width: 240px;">
            <h4 style="margin: 0 0 6px 0; color: #111;">Route {row['route_number']} ({row['county_name']})</h4>
            <b>County Rank:</b> #{row['county_priority_rank']}<br/>
            <b>Viability Score:</b> <span style="font-weight:bold; color:#111111;">{score:.2f} / 100</span><br/>
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
            poly = folium.PolyLine(
                locations=lat_lon_coords,
                color=hex_color,
                weight=4.5,
                opacity=1.0,
                tooltip=f"ID:{obj_id} | Rank #{row['county_priority_rank']} - Route {row['route_number']} ({row['county_name']}) - Score: {score:.2f}/100",
                popup=folium.Popup(popup_html, max_width=320),
            )
            poly.add_to(feature_group)

    feature_group.add_to(m)

    legend_html = f"""
    <div style="
    position: fixed; 
    bottom: 25px; left: 25px; width: 200px; height: 100px; 
    background-color: white; border: 1px solid #bbb; z-index: 9999; font-size: 11px;
    padding: 10px; border-radius: 6px; box-shadow: 2px 2px 6px rgba(0,0,0,0.25);
    font-family: Arial, sans-serif;">
        <b>Viability Score (0–100)</b><br>
        <div style="background: linear-gradient(to right, #440154, #21918c, #fde725); height: 12px; margin: 6px 0; border-radius: 2px;"></div>
        <div style="display: flex; justify-content: space-between; font-size: 10px; color: #444;">
            <span>{min_score:.1f} (Low)</span>
            <span>{(min_score + max_score)/2:.1f}</span>
            <span>{max_score:.1f} (Peak)</span>
        </div>
        <div style="margin-top: 5px; font-size: 9px; color: #666; text-align: center;">Viridis Palette (Colorblind Safe)</div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    sidebar_html = f"""
    <div style="
    position: fixed; 
    bottom: 25px; right: 25px; width: 250px; max-height: 290px; 
    background-color: white; border: 1px solid #bbb; z-index: 9999; font-size: 12px;
    padding: 12px; border-radius: 6px; box-shadow: 2px 2px 8px rgba(0,0,0,0.3);
    font-family: Arial, sans-serif; display: flex; flex-direction: column;">
        <div style="font-weight: bold; border-bottom: 2px solid #333; padding-bottom: 5px; margin-bottom: 6px; display: flex; justify-content: space-between;">
            <span>Viability Leaderboard</span>
            <span style="font-size: 10px; color: #777; align-self: flex-end;">{len(df_desc)} Segments</span>
        </div>
        <div style="overflow-y: auto; flex-grow: 1; padding-right: 4px;">
            {leaderboard_items_html}
        </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(sidebar_html))

    color_registry_json = json.dumps(color_registry)
    script_html = f"""
    <script>
    const originalColors = {color_registry_json};
    let polylineMap = {{}};
    let leafletMapInstance = null;

    window.addEventListener('load', function() {{
        setTimeout(function() {{
            for (let key in window) {{
                if (window[key] && window[key]._layers && typeof window[key].setView === 'function') {{
                    leafletMapInstance = window[key];
                    for (let layerId in window[key]._layers) {{
                        let layer = window[key]._layers[layerId];
                        if (layer.options && layer.options.color && layer.getTooltip) {{
                            let tt = layer.getTooltip();
                            if (tt && tt._content) {{
                                for (let objId in originalColors) {{
                                    if (tt._content.indexOf('ID:' + objId) !== -1) {{
                                        polylineMap[objId] = layer;
                                    }}
                                }}
                            }}
                        }}
                    }}
                    break;
                }}
            }}
        }}, 500);
    }});

    function highlightSegment(objId) {{
        let row = document.getElementById('leaderboard-item-' + objId);
        if (row) row.style.backgroundColor = '#eef3f8';
        let layer = polylineMap[objId];
        if (layer) {{
            layer.setStyle({{
                weight: 8,
                color: '#ff0055',
                opacity: 1.0
            }});
            if (layer.bringToFront) layer.bringToFront();
        }}
    }}

    function resetSegment(objId) {{
        let row = document.getElementById('leaderboard-item-' + objId);
        if (row) row.style.backgroundColor = '';
        let layer = polylineMap[objId];
        if (layer) {{
            layer.setStyle({{
                weight: 4.5,
                color: originalColors[objId] || '#333333',
                opacity: 1.0
            }});
        }}
    }}

    function focusSegment(objId) {{
        let layer = polylineMap[objId];
        if (!layer || !leafletMapInstance) return;

        let centerPoint = layer.getBounds().getCenter();
        highlightSegment(objId);

        // Smooth cinematic pan directly to the geographic center
        leafletMapInstance.flyTo(centerPoint, 13, {{
            animate: true,
            duration: 0.9
        }});

        // Trigger the popup once the flight animation completes, disabling popup autoPan
        leafletMapInstance.once('moveend', function() {{
            if (layer.getPopup()) {{
                layer.getPopup().options.autoPan = false;
                layer.openPopup(centerPoint);
            }}
        }});
    }}
    </script>
    """
    m.get_root().html.add_child(folium.Element(script_html))

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