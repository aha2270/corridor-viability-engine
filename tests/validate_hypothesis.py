import os
from dotenv import load_dotenv
from google.cloud import bigquery
import pandas as pd
from scipy import stats

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
DATASET_ID = os.getenv("BQ_DATASET_NAME", "corridor_dw")

def run_hypothesis_validation():
    client = bigquery.Client(project=PROJECT_ID)
    query = f"""
    SELECT
      object_id,
      travel_plaza_viability_score,
      commuter_market_viability_score,
      travel_plaza_priority_rank,
      commuter_market_priority_rank
    FROM `{PROJECT_ID}.{DATASET_ID}.gold_travel_plaza_candidates`
    """
    df = client.query(query).to_dataframe()

    tp_scores = df["travel_plaza_viability_score"]
    cm_scores = df["commuter_market_viability_score"]

    # 1. Paired Difference Test (Wilcoxon Signed-Rank)
    stat, p_value_wilcoxon = stats.wilcoxon(tp_scores, cm_scores)

    # 2. Spearman Rank Correlation (Testing if rankings are identical)
    spearman_corr, p_value_spearman = stats.spearmanr(
        df["travel_plaza_priority_rank"], 
        df["commuter_market_priority_rank"]
    )

    print("=" * 60)
    print("CAPSTONE HYPOTHESIS VALIDATION RESULTS")
    print("=" * 60)
    print(f"Sample Size (Corridors Evaluated): {len(df)}")
    print(f"Travel Plaza Mean Score: {tp_scores.mean():.2f} (Std: {tp_scores.std():.2f})")
    print(f"Commuter Market Mean Score: {cm_scores.mean():.2f} (Std: {cm_scores.std():.2f})")
    print("-" * 60)
    print(f"Wilcoxon Signed-Rank Statistic: {stat:.2f}")
    print(f"Wilcoxon p-value: {p_value_wilcoxon:.4e}")
    print(f"Spearman Rank Correlation: {spearman_corr:.4f} (p-value: {p_value_spearman:.4e})")
    print("-" * 60)

    alpha = 0.05
    if p_value_wilcoxon < alpha:
        print(f"VERDICT: REJECT NULL HYPOTHESIS (p < {alpha}).")
        print("Corridor evaluation demonstrates statistically significant divergence between archetypes.")
    else:
        print("VERDICT: FAIL TO REJECT NULL HYPOTHESIS.")
    print("=" * 60)

if __name__ == "__main__":
    run_hypothesis_validation()