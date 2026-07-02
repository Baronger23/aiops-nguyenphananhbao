import os
import math
import pandas as pd
import numpy as np
import networkx as nx
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import LabelEncoder

# Define paths relative to the script location
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir)) # parent of ai
ce_file = os.path.join(project_root, "tf2-finops", "cost_explorer_daily.csv")
cur_file = os.path.join(project_root, "tf2-finops", "cur_line_items.csv")
labels_file = os.path.join(project_root, "tf2-finops", "anomaly_labels_public.csv")

# Simulated Change Management (Jira / AWS Systems Manager Change Manager) database
MOCK_APPROVED_TICKETS = [
    {"pattern": "migration", "start": "2026-03-28", "end": "2026-03-30", "ticket": "CHG-90812", "desc": "Lake migration"},
    {"pattern": "loadtest", "start": "2026-05-06", "end": "2026-05-07", "ticket": "CHG-88712", "desc": "Load test"},
    {"pattern": "flashsale", "start": "2026-05-23", "end": "2026-05-26", "ticket": "CHG-77123", "desc": "Flash sale autoscaling"}
]

def is_change_approved(resource_id, date_str):
    """
    Checks if a cost spike has been pre-approved via Change Management system
    using resource name patterns and date ranges.
    """
    for ticket in MOCK_APPROVED_TICKETS:
        if ticket["pattern"] in resource_id.lower():
            if ticket["start"] <= date_str <= ticket["end"]:
                return True
    return False

def run_backtest():
    print("==================================================")
    print("RUNNING OFFLINE BACKTEST: HYBRID MODEL (ISOLATION FOREST + COV)")
    print("==================================================")
    
    if not os.path.exists(cur_file):
        print(f"ERROR: Dataset files not found at {cur_file}.")
        print("Please ensure the 'tf2-finops' folder is placed at the project root directory.")
        return
        
    cur = pd.read_csv(cur_file, parse_dates=["line_item_usage_start_date"])
    labels = pd.read_csv(labels_file)
    
    cur = cur.sort_values("line_item_usage_start_date")
    dates = sorted(cur["line_item_usage_start_date"].unique())
    
    print(f"Loaded {len(cur)} line items covering {len(dates)} days.")
    print("Building NetworkX dependency graph...")
    
    G = nx.Graph()
    # Sample subset for topology generation
    for _, row in cur.sample(min(1500, len(cur))).iterrows():
        rid = row["line_item_resource_id"]
        acc = row["line_item_usage_account_name"]
        prod = row["line_item_product_code"]
        G.add_node(rid, type="resource", product=prod)
        G.add_node(acc, type="account")
        G.add_edge(rid, acc)

    res_daily = cur.groupby([
        "line_item_usage_start_date",
        "line_item_product_code",
        "product_region_code",
        "line_item_resource_id",
        "line_item_usage_account_name",
        "resource_tags_user_team"
    ], dropna=False)["line_item_unblended_cost"].sum().reset_index()
    
    unique_resources = res_daily["line_item_resource_id"].unique()
    
    all_records = []
    metadata = []
    
    # 1. Static Idle detection using CoV
    flat_idle_resources = {}
    
    print("Preparing features and scanning for flat idle spend...")
    for rid in unique_resources:
        res_subset = res_daily[res_daily["line_item_resource_id"] == rid].copy()
        
        prod = res_subset["line_item_product_code"].iloc[0]
        reg = str(res_subset["product_region_code"].iloc[0]) if not pd.isna(res_subset["product_region_code"].iloc[0]) else "us-east-1"
        account = res_subset["line_item_usage_account_name"].iloc[0]
        team = str(res_subset["resource_tags_user_team"].iloc[0]) if not pd.isna(res_subset["resource_tags_user_team"].iloc[0]) else "unknown"
        
        res_subset = res_subset.set_index("line_item_usage_start_date").reindex(dates).reset_index()
        res_subset["line_item_unblended_cost"] = res_subset["line_item_unblended_cost"].fillna(0.0)
        
        costs = res_subset["line_item_unblended_cost"].values
        rolling_7d = res_subset["line_item_unblended_cost"].rolling(7, min_periods=1).mean().values
        
        # 1. Flat continuous spend (Orphan resources)
        non_zero_costs = costs[costs > 0]
        if len(non_zero_costs) > 30:
            mean_cost = np.mean(non_zero_costs)
            std_cost = np.std(non_zero_costs)
            cov = std_cost / mean_cost if mean_cost > 0 else 999
            if cov < 0.05 and mean_cost > 5.0:
                first_date = res_subset[res_subset["line_item_unblended_cost"] > 0]["line_item_usage_start_date"].min()
                flat_idle_resources[rid] = {
                    "resource_id": rid,
                    "account": account,
                    "product": prod,
                    "team": team,
                    "date": str(first_date.date()),
                    "cost_sample": round(mean_cost, 2),
                    "score": 0.0,
                    "type": "idle_resource",
                    "reason": f"Flat continuous spend detected (${mean_cost:.2f}/day)."
                }

        # Build feature set for all resource-days
        for idx, date in enumerate(dates):
            cost = costs[idx]
            avg_7d = rolling_7d[idx]
            
            if avg_7d == 0.0:
                cost_ratio = 1.0
            else:
                cost_ratio = cost / avg_7d
                
            day_of_week = date.dayofweek
            is_weekend = 1 if day_of_week >= 5 else 0
            
            all_records.append({
                "unblended_cost": cost,
                "service_code": prod,
                "region": reg,
                "cost_ratio_to_7d_avg": cost_ratio,
                "day_of_week": day_of_week,
                "is_weekend": is_weekend
            })
            
            metadata.append({
                "date": str(date.date()),
                "resource_id": rid,
                "account": account,
                "product": prod,
                "team": team,
                "cost": cost
            })

    df_features = pd.DataFrame(all_records)
    
    # Encode categorical features
    le_service = LabelEncoder()
    df_features["service_code"] = le_service.fit_transform(df_features["service_code"])
    
    le_region = LabelEncoder()
    df_features["region"] = le_region.fit_transform(df_features["region"])
    
    # Log transform unblended_cost to reduce scale disparity
    df_features["unblended_cost_log"] = np.log1p(df_features["unblended_cost"])
    
    # Prepare training matrix X
    X = df_features[["unblended_cost_log", "service_code", "region", "cost_ratio_to_7d_avg", "day_of_week", "is_weekend"]].values
    
    # 2. Fit Isolation Forest for spikes
    print("Fitting Isolation Forest model on all resource-days...")
    clf = IsolationForest(n_estimators=150, contamination=0.005, random_state=42)
    predictions = clf.fit_predict(X)
    scores = clf.score_samples(X)
    
    detected_anomalies = {}
    
    # Add CoV detections first
    detected_anomalies.update(flat_idle_resources)
    
    # Add Isolation Forest detections with post-filtering
    for idx, pred in enumerate(predictions):
        if pred == -1: # Anomaly detected by IF
            meta = metadata[idx]
            cost = meta["cost"]
            rid = meta["resource_id"]
            date_str = meta["date"]
            
            # Post-filtering rules to reduce FPs
            # Ignore low costs (under $15.0)
            if cost < 15.0:
                continue
                
            # Filter out pre-approved scheduled changes
            if is_change_approved(rid, date_str):
                continue
                
            if rid not in detected_anomalies or date_str < detected_anomalies[rid]["date"]:
                # Classify anomaly type
                anom_type = "sudden_spike"
                if meta["product"] == "AmazonEC2" and "gpu" in rid.lower():
                    anom_type = "runaway_usage"
                elif meta["team"] == "unknown":
                    anom_type = "untagged_spend"
                    
                detected_anomalies[rid] = {
                    "resource_id": rid,
                    "account": meta["account"],
                    "product": meta["product"],
                    "team": meta["team"],
                    "date": date_str,
                    "cost_sample": round(cost, 2),
                    "score": round(float(scores[idx]), 4),
                    "type": anom_type,
                    "reason": f"Isolation Forest detected anomaly at cost ${cost:.2f} (score: {scores[idx]:.4f})."
                }

    detected_df = pd.DataFrame(detected_anomalies.values())
    print("\n==================================================")
    print(f"DETECTION RESULTS (Found {len(detected_df)} unique anomalies):")
    print("==================================================")
    if not detected_df.empty:
        print(detected_df[["resource_id", "account", "product", "team", "date", "cost_sample", "type"]].to_string(index=False))
        
    print("\n==================================================")
    print("EVALUATION VS PUBLIC LABELS (GROUND-TRUTH):")
    print("==================================================")
    passed_labels = 0
    for idx, row in labels.iterrows():
        label_id = row["anomaly_id"]
        rid = row["resource_id"]
        expected = row["label"]
        is_detected = rid in detected_anomalies
        
        status = "FAILED"
        if expected == "anomaly" and is_detected:
            status = "PASSED"
            passed_labels += 1
        elif expected == "benign" and not is_detected:
            status = "PASSED"
            passed_labels += 1
            
        print(f"Label {label_id} ({expected.upper()}): {rid} -> Detected: {is_detected} -> {status}")
        
    print("==================================================")
    print(f"Backtest Score on Public Labels: {passed_labels}/{len(labels)} Passed ({passed_labels/len(labels)*100:.1f}%)")
    print("==================================================")

if __name__ == "__main__":
    run_backtest()
