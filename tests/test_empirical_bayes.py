import json
import numpy as np
import pandas as pd
from pathlib import Path

# 1. Load your dataset (supports .geojson, .json, or .csv)
DATA_PATH = Path("./data/silver_corridor_viability.csv") 

if DATA_PATH.suffix == ".csv":
    df = pd.read_csv(DATA_PATH)
else:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict) and "features" in raw:
        df = pd.DataFrame([feat["properties"] for feat in raw["features"]])
    else:
        df = pd.DataFrame(raw)

# 2. Map your exact column names here
COL_ROUTE = "route_number"   # e.g., 'route', 'ST_RT_NO', etc.
COL_COUNTY = "county_name"      # e.g., 'CTY_CODE', 'county_name'
COL_AADT = "cur_aadt"          # Total daily volume
COL_TRUCKS = "adtt_cur"  # Commercial truck volume (or compute from aadt * truck_pct)

# Filter to valid positive traffic records
df = df[(df[COL_AADT] > 0) & (df[COL_TRUCKS] >= 0)].copy()

# --- STEP 1: Calculate Regional Prior (mu) ---
mu = df[COL_TRUCKS].sum() / df[COL_AADT].sum()

# --- METHOD A: Median AADT as k ---
k_median = float(df[COL_AADT].median())

# --- METHOD B: Beta-Binomial Method of Moments k ---
def compute_mom_k(data: pd.DataFrame, weighted_mean: float) -> float:
    # Filter out tiny-volume noise (< 500 AADT) when estimating regional variance
    reliable = data[data[COL_AADT] >= 500]
    if len(reliable) < 2:
        return float(data[COL_AADT].median())

    p = reliable[COL_TRUCKS] / reliable[COL_AADT]
    weights = reliable[COL_AADT]
    weighted_var = np.average((p - weighted_mean) ** 2, weights=weights)

    if weighted_var <= 0:
        return float(data[COL_AADT].median())

    k = (weighted_mean * (1 - weighted_mean) / weighted_var) - 1
    return max(float(k), 100.0)  # Floor at 100 to prevent under-smoothing

k_mom = compute_mom_k(df, mu)

# --- STEP 2: Apply Empirical Bayes Shrinkage ---
df["raw_pct"] = (df[COL_TRUCKS] / df[COL_AADT]) * 100
df["eb_median_pct"] = ((df[COL_TRUCKS] + k_median * mu) / (df[COL_AADT] + k_median)) * 100
df["eb_mom_pct"] = ((df[COL_TRUCKS] + k_mom * mu) / (df[COL_AADT] + k_mom)) * 100

# --- STEP 3: Print Diagnostic Summaries ---
print("=" * 55)
print(f"Total Valid Segments  : {len(df):,}")
print(f"Regional Truck Avg (μ): {mu * 100:.2f}%")
print(f"k (Median AADT)       : {k_median:,.0f} AADT")
print(f"k (Method of Moments) : {k_mom:,.0f} AADT")
print("=" * 55)

display_cols = [COL_ROUTE, COL_COUNTY, COL_AADT, COL_TRUCKS, "raw_pct", "eb_median_pct", "eb_mom_pct"]

print("\n--- TOP 10 BY RAW TRUCK % (Current Distorted Baseline) ---")
print(df.sort_values("raw_pct", ascending=False)[display_cols].head(10).to_string(index=False, float_format="%.1f"))

print("\n--- TOP 10 BY EB MEDIAN SMOOTHED % ---")
print(df.sort_values("eb_median_pct", ascending=False)[display_cols].head(10).to_string(index=False, float_format="%.1f"))

print("\n--- TOP 10 BY EB METHOD-OF-MOMENTS SMOOTHED % ---")
print(df.sort_values("eb_mom_pct", ascending=False)[display_cols].head(10).to_string(index=False, float_format="%.1f"))

print("\n--- LOW-VOLUME OUTLIER CHECK (< 1,000 AADT with Highest Raw %) ---")
low_vol = df[df[COL_AADT] < 1000].sort_values("raw_pct", ascending=False)
print(low_vol[display_cols].head(5).to_string(index=False, float_format="%.1f"))