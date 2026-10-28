import json
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from google.cloud import bigquery
import folium
import matplotlib as mpl
import matplotlib.colors as colors
import pandas as pd
from shapely import wkt
from shapely.geometry import mapping

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("generate_map")

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
DATASET_ID = os.getenv("BQ_DATASET_NAME", "corridor_dw")

if not PROJECT_ID:
    logger.error("GCP_PROJECT_ID not set in environment or .env file.")
    sys.exit(1)


def get_color(score, vmin, vmax):
    """Maps a score between vmin and vmax to a Viridis hex color string."""
    norm = colors.Normalize(vmin=vmin, vmax=vmax, clip=True)
    colormap = mpl.colormaps["viridis"]
    rgba = colormap(norm(score))
    return colors.to_hex(rgba)


def generate_map():
    client = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.{DATASET_ID}.gold_travel_plaza_candidates"

    logger.info(f"Querying scored corridor candidates from {table_id}...")

    sql = f"""
    SELECT
      object_id,
      route_number,
      county_name,
      segment_length_feet,
      cur_aadt,
      adtt_cur,
      truck_pct,
      competitor_count_1mi,
      major_chain_count_1mi,
      ev_station_count_1mi,
      dc_fast_ports_1mi,
      avg_county_median_income,
      county_unemployment_rate,
      travel_plaza_viability_score,
      commuter_market_viability_score,
      optimal_store_archetype,
      travel_plaza_priority_rank,
      commuter_market_priority_rank,
      wkt_geometry
    FROM `{table_id}`
    ORDER BY travel_plaza_viability_score DESC;
    """

    df = client.query(sql).to_dataframe()

    if df.empty:
        logger.warning("No candidate records found in gold table. Aborting map build.")
        return

    logger.info(f"Loaded {len(df)} candidate segments for interactive rendering.")

    # Calculate score bounds for colormap normalization
    tp_min = float(df["travel_plaza_viability_score"].min())
    tp_max = float(df["travel_plaza_viability_score"].max())
    cm_min = float(df["commuter_market_viability_score"].min())
    cm_max = float(df["commuter_market_viability_score"].max())

    logger.info(f"Travel Plaza bounds: [{tp_min:.1f}, {tp_max:.1f}] | Commuter bounds: [{cm_min:.1f}, {cm_max:.1f}]")

    # Center map on Harrisburg / Cumberland / Dauphin corridor nexus
    m = folium.Map(
        location=[40.2732, -76.8867],
        zoom_start=10,
        tiles=None,
        control_scale=True
    )

    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Street Map",
        name="Esri Streets",
        overlay=False,
        control=True
    ).add_to(m)

    # Build GeoJSON feature collection with dual attributes
    features = []
    leaderboard_data = []

    for _, row in df.iterrows():
        # Guard against NaN/Null geometry strings
        if pd.isna(row.get("wkt_geometry")) or not isinstance(row["wkt_geometry"], str):
            continue
        geom = wkt.loads(row["wkt_geometry"])
        obj_id = str(row["object_id"])

        tp_score = float(row["travel_plaza_viability_score"])
        cm_score = float(row["commuter_market_viability_score"])

        tp_color = get_color(tp_score, tp_min, tp_max)
        cm_color = get_color(cm_score, cm_min, cm_max)

        props = {
            "object_id": obj_id,
            "route_number": str(row["route_number"]),
            "county_name": str(row["county_name"]),
            "optimal_archetype": str(row["optimal_store_archetype"]),
            "tp_score": tp_score,
            "cm_score": cm_score,
            "tp_rank": int(row["travel_plaza_priority_rank"]),
            "cm_rank": int(row["commuter_market_priority_rank"]),
            "tp_color": tp_color,
            "cm_color": cm_color,
            "cur_aadt": int(row["cur_aadt"]),
            "adtt_cur": int(row["adtt_cur"]),
            "truck_pct": float(row["truck_pct"]),
            "median_income": int(row["avg_county_median_income"]),
            "unemployment_rate": float(row["county_unemployment_rate"]),
            "competitors_1mi": int(row["competitor_count_1mi"]),
            "chains_1mi": int(row["major_chain_count_1mi"]),
            "dc_fast_1mi": int(row["dc_fast_ports_1mi"]),
            "length_miles": round(float(row["segment_length_feet"]) / 5280.0, 2)
        }

        leaderboard_data.append(props)

        features.append({
            "type": "Feature",
            "id": obj_id,
            "properties": props,
            "geometry": mapping(geom)
        })

    geojson_collection = {
        "type": "FeatureCollection",
        "features": features
    }

    # Inject client-side application state, UI components, and Leaflet layer hooks
    app_script = f"""
    <div id="archetype-control" style="
        position: fixed;
        top: 15px;
        left: 60px;
        z-index: 1000;
        background: #ffffff;
        padding: 6px;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        display: flex;
        gap: 6px;
        font-family: Arial, sans-serif;
    ">
        <button id="btn-tp" onclick="setMode('travel_plaza')" style="
            background: #1e3a8a;
            color: #ffffff;
            border: none;
            padding: 8px 14px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.2s ease;
        ">🚚 Commercial Travel Plaza</button>
        <button id="btn-cm" onclick="setMode('commuter_market')" style="
            background: #e2e8f0;
            color: #334155;
            border: none;
            padding: 8px 14px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.2s ease;
        ">🚗 Commuter Convenience</button>
    </div>

    <div id="corridor-sidebar" style="
        position: fixed;
        top: 65px;
        left: 15px;
        width: 320px;
        height: calc(100vh - 85px);
        background: rgba(255, 255, 255, 0.95);
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.25);
        z-index: 1000;
        display: flex;
        flex-direction: column;
        font-family: Arial, sans-serif;
        overflow: hidden;
    ">
        <div style="padding: 12px 14px; background: #0f172a; color: #ffffff;">
            <div id="sidebar-title" style="font-size: 13px; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px;">
                Travel Plaza Priority Rank
            </div>
            <div id="sidebar-subtitle" style="font-size: 11px; color: #94a3b8; margin-top: 2px;">
                Freight-Dominant Multi-Criteria Index
            </div>
        </div>
        <div id="leaderboard-container" style="overflow-y: auto; flex: 1; padding: 4px;">
        </div>
    </div>

    <div id="legend-box" style="
        position: fixed;
        bottom: 25px;
        right: 25px;
        background: #ffffff;
        padding: 12px 14px;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.25);
        font-family: Arial, sans-serif;
        font-size: 11px;
        z-index: 1000;
    ">
        <div id="legend-title" style="font-weight: bold; margin-bottom: 6px;">Viability Score (Viridis)</div>
        <div style="
            width: 180px;
            height: 12px;
            background: linear-gradient(to right, #440154, #3b528b, #21918c, #5ec962, #fde725);
            border-radius: 3px;
        "></div>
        <div style="display: flex; justify-content: space-between; margin-top: 4px; color: #555;">
            <span id="legend-min">{tp_min:.1f}</span>
            <span id="legend-mid">{(tp_min + tp_max)/2:.1f}</span>
            <span id="legend-max">{tp_max:.1f}</span>
        </div>
    </div>

    <script>
        const geojsonData = {json.dumps(geojson_collection)};
        const leaderboardData = {json.dumps(leaderboard_data)};
        const scoreBounds = {{
            "travel_plaza": {{ min: {tp_min}, max: {tp_max} }},
            "commuter_market": {{ min: {cm_min}, max: {cm_max} }}
        }};

        let activeMode = "travel_plaza";
        let geojsonLayer = null;
        let mapInstance = null;
        const segmentLayers = {{}};

        function getLeafletMap() {{
            for (let k in window) {{
                if (k.startsWith("map_") && window[k] && window[k].addLayer) {{
                    return window[k];
                }}
            }}
            return null;
        }}

        function buildPopupContent(props, mode) {{
            if (mode === "travel_plaza") {{
                return `
                <div style="font-family: Arial, sans-serif; font-size: 12px; width: 250px;">
                    <h4 style="margin: 0 0 4px 0; color: #1e3a8a;">Rt ${{props.route_number}} (${{props.county_name}})</h4>
                    <b>Archetype Focus:</b> Commercial Travel Plaza<br/>
                    <b>County Rank:</b> #${{props.tp_rank}}<br/>
                    <b>Viability Score:</b> <span style="font-weight: bold; color: #111;">${{props.tp_score.toFixed(2)}} / 100</span><br/>
                    <hr style="margin: 5px 0; border: 0; border-top: 1px solid #ccc;"/>
                    <b>Daily Freight (ADTT):</b> ${{props.adtt_cur.toLocaleString()}} trucks (${{props.truck_pct}}%)<br/>
                    <b>Total AADT:</b> ${{props.cur_aadt.toLocaleString()}}<br/>
                    <b>Travel Plaza Saturation:</b> ${{props.chains_1mi}} chains (1-mi)<br/>
                    <b>DC Fast Ports:</b> ${{props.dc_fast_1mi}} ports<br/>
                    <b>County Unemployment:</b> ${{props.unemployment_rate}}%
                </div>`;
            }} else {{
                return `
                <div style="font-family: Arial, sans-serif; font-size: 12px; width: 250px;">
                    <h4 style="margin: 0 0 4px 0; color: #0f766e;">Rt ${{props.route_number}} (${{props.county_name}})</h4>
                    <b>Archetype Focus:</b> Commuter Convenience<br/>
                    <b>County Rank:</b> #${{props.cm_rank}}<br/>
                    <b>Viability Score:</b> <span style="font-weight: bold; color: #111;">${{props.cm_score.toFixed(2)}} / 100</span><br/>
                    <hr style="margin: 5px 0; border: 0; border-top: 1px solid #ccc;"/>
                    <b>Commuter Volume (AADT):</b> ${{props.cur_aadt.toLocaleString()}} vehicles<br/>
                    <b>County Median Income:</b> $${{props.median_income.toLocaleString()}}<br/>
                    <b>Retail Density:</b> ${{props.competitors_1mi}} amenities (1-mi)<br/>
                    <b>DC Fast Ports:</b> ${{props.dc_fast_1mi}} ports<br/>
                    <b>County Unemployment:</b> ${{props.unemployment_rate}}%
                </div>`;
            }}
        }}

        function renderLeaderboard(mode) {{
            const container = document.getElementById("leaderboard-container");
            container.innerHTML = "";

            const sorted = [...leaderboardData].sort((a, b) => {{
                return mode === "travel_plaza" ? b.tp_score - a.tp_score : b.cm_score - a.cm_score;
            }});

            sorted.slice(0, 100).forEach((item, index) => {{
                const score = mode === "travel_plaza" ? item.tp_score : item.cm_score;
                const countyRank = mode === "travel_plaza" ? item.tp_rank : item.cm_rank;
                const activeColor = mode === "travel_plaza" ? item.tp_color : item.cm_color;
                const globalRank = index + 1;

                const card = document.createElement("div");
                card.id = `card-${{item.object_id}}`;
                card.style.cssText = "padding: 8px 10px; border-bottom: 1px solid #e2e8f0; cursor: pointer; font-size: 11px; transition: background 0.15s;";
                card.innerHTML = `
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-weight: bold; color: #1e293b;">
                            <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: ${{activeColor}}; margin-right: 4px;"></span>
                            #${{globalRank}} Rt ${{item.route_number}} (${{item.county_name}} · #${{countyRank}})
                        </span>
                        <span style="font-weight: bold; color: #0f172a;">${{score.toFixed(1)}}</span>
                    </div>
                    <div style="color: #64748b; font-size: 10px; margin-top: 2px;">
                        ${{mode === "travel_plaza" ? item.adtt_cur.toLocaleString() + ' trucks (' + item.truck_pct + '%)' : item.cur_aadt.toLocaleString() + ' vehicles | $' + item.median_income.toLocaleString()}}
                    </div>
                `;

                card.onmouseover = () => highlightSegment(item.object_id);
                card.onmouseout = () => resetSegment(item.object_id);
                card.onclick = () => focusSegment(item.object_id);

                container.appendChild(card);
            }});
        }}

        function setMode(mode) {{
            activeMode = mode;

            const btnTp = document.getElementById("btn-tp");
            const btnCm = document.getElementById("btn-cm");
            const sTitle = document.getElementById("sidebar-title");
            const sSub = document.getElementById("sidebar-subtitle");
            const lMin = document.getElementById("legend-min");
            const lMid = document.getElementById("legend-mid");
            const lMax = document.getElementById("legend-max");

            if (mode === "travel_plaza") {{
                btnTp.style.background = "#1e3a8a";
                btnTp.style.color = "#ffffff";
                btnCm.style.background = "#e2e8f0";
                btnCm.style.color = "#334155";
                sTitle.innerText = "Travel Plaza Priority Rank";
                sSub.innerText = "Freight-Dominant Multi-Criteria Index";
            }} else {{
                btnCm.style.background = "#0f766e";
                btnCm.style.color = "#ffffff";
                btnTp.style.background = "#e2e8f0";
                btnTp.style.color = "#334155";
                sTitle.innerText = "Commuter Market Rank";
                sSub.innerText = "Passenger Volume & Socioeconomic Index";
            }}

            const b = scoreBounds[mode];
            lMin.innerText = b.min.toFixed(1);
            lMid.innerText = ((b.min + b.max) / 2).toFixed(1);
            lMax.innerText = b.max.toFixed(1);

            // Re-style segments and update popups
            Object.keys(segmentLayers).forEach(objId => {{
                const layer = segmentLayers[objId];
                const p = layer.feature.properties;
                const targetColor = mode === "travel_plaza" ? p.tp_color : p.cm_color;

                layer.setStyle({{ color: targetColor, weight: 4, opacity: 0.85 }});
                layer.bindPopup(buildPopupContent(p, mode));
            }});

            renderLeaderboard(mode);
        }}

        function highlightSegment(objId) {{
            const layer = segmentLayers[objId];
            if (layer) {{
                layer.setStyle({{ color: "#ff007f", weight: 8, opacity: 1.0 }});
                layer.bringToFront();
            }}
            const card = document.getElementById(`card-${{objId}}`);
            if (card) card.style.background = "#f1f5f9";
        }}

        function resetSegment(objId) {{
            const layer = segmentLayers[objId];
            if (layer) {{
                const p = layer.feature.properties;
                const c = activeMode === "travel_plaza" ? p.tp_color : p.cm_color;
                layer.setStyle({{ color: c, weight: 4, opacity: 0.85 }});
            }}
            const card = document.getElementById(`card-${{objId}}`);
            if (card) card.style.background = "transparent";
        }}

        function focusSegment(objId) {{
            const layer = segmentLayers[objId];
            if (layer && mapInstance) {{
                mapInstance.fitBounds(layer.getBounds(), {{ maxZoom: 13, animate: true }});
                layer.openPopup();
            }}
        }}

        window.addEventListener("DOMContentLoaded", () => {{
            const checkMap = setInterval(() => {{
                mapInstance = getLeafletMap();
                if (mapInstance) {{
                    clearInterval(checkMap);

                    geojsonLayer = L.geoJSON(geojsonData, {{
                        style: feature => ({{
                            color: feature.properties.tp_color,
                            weight: 4,
                            opacity: 0.85
                        }}),
                        onEachFeature: (feature, layer) => {{
                            const id = feature.properties.object_id;
                            segmentLayers[id] = layer;
                            layer.bindPopup(buildPopupContent(feature.properties, activeMode));
                            layer.on("mouseover", () => highlightSegment(id));
                            layer.on("mouseout", () => resetSegment(id));
                        }}
                    }}).addTo(mapInstance);

                    renderLeaderboard("travel_plaza");
                }}
            }}, 150);
        }});
    </script>
    """

    m.get_root().html.add_child(folium.Element(app_script))

    output_dir = Path("docs")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "corridor_viability_map.html"

    m.save(str(output_file))
    logger.info(f"Interactive dual-view map successfully generated at {output_file}.")


if __name__ == "__main__":
    generate_map()