import json
from pathlib import Path
import numpy as np
import pandas as pd

# 1. Load dataset (supports .csv, .geojson, or .json)
DATA_PATH = Path("./data/silver_corridor_viability.csv") 

if DATA_PATH.suffix == ".csv":
    df = pd.read_csv(DATA_PATH)
else:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    df = pd.DataFrame(
        [feat["properties"] for feat in raw["features"]]
        if isinstance(raw, dict) and "features" in raw
        else raw
    )

# Filter to valid positive traffic segments
df = df[(df["cur_aadt"] > 0) & (df["adtt_cur"] >= 0)].copy()

# 2. Compute Empirical Bayes Parameters (Dynamic Cohort Prior)
mu = float(df["adtt_cur"].sum() / df["cur_aadt"].sum())
k_median = float(df["cur_aadt"].median())

df["raw_truck_pct"] = (df["adtt_cur"] / df["cur_aadt"]) * 100
df["eb_truck_pct"] = ((df["adtt_cur"] + k_median * mu) / (df["cur_aadt"] + k_median)) * 100

# 3. Min-Max Normalization Helper (0-100 scale)
def min_max(series: pd.Series) -> pd.Series:
    rng = series.max() - series.min()
    return ((series - series.min()) / rng) * 100 if rng > 0 else pd.Series(50.0, index=series.index)

df["norm_aadt"] = min_max(df["cur_aadt"])
df["norm_trucks"] = min_max(df["adtt_cur"])
df["norm_eb_truck_pct"] = min_max(df["eb_truck_pct"])
df["norm_ev_gap"] = 100 - min_max(df["dc_fast_ports_1mi"].fillna(0))
df["norm_comp_gap"] = 100 - min_max(df["major_chain_count_1mi"].fillna(0))

# 4. Recompute Travel Plaza Viability Score (Adjust weights to match BigQuery SQL view)
df["calibrated_travel_plaza_score"] = (
    0.45 * df["norm_eb_truck_pct"]
    + 0.30 * df["norm_trucks"]
    + 0.15 * df["norm_ev_gap"]
    + 0.10 * df["norm_comp_gap"]
)

# Tie-breaker sort: Unrounded score DESC, then Truck Volume DESC
df = df.sort_values(
    by=["calibrated_travel_plaza_score", "adtt_cur"], ascending=[False, False]
).reset_index(drop=True)
df["calibrated_rank"] = df.index + 1

# 5. Output Calibration Audit Report
audit_cols = [
    "calibrated_rank",
    "route_number",
    "county_name",
    "cur_aadt",
    "adtt_cur",
    "raw_truck_pct",
    "eb_truck_pct",
    "travel_plaza_viability_score",
    "calibrated_travel_plaza_score",
]

print("=" * 80)
print("CORRIDOR VIABILITY SCORING AUDIT REPORT")
print(f"Sample Size           : {len(df):,} roadway segments")
print(f"Regional Truck Prior  : {mu * 100:.2f}% (mu)")
print(f"Confidence Threshold  : {k_median:,.0f} AADT (k = Median AADT)")
print("=" * 80)

print("\n--- TOP 15 CALIBRATED CORRIDORS (Empirical Bayes + Tie-Breaker Sort) ---")
print(df[audit_cols].head(15).to_string(index=False, float_format="%.1f"))

df["score_delta"] = df["calibrated_travel_plaza_score"] - df["travel_plaza_viability_score"]
print("\n--- TOP 10 OUTLIER CORRECTIONS (Largest Downward Score Adjustments) ---")
print(
    df.sort_values("score_delta", ascending=True)[audit_cols + ["score_delta"]]
    .head(10)
    .to_string(index=False, float_format="%.1f")
)