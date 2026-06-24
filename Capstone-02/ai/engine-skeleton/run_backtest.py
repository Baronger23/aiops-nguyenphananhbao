import os
import math
import pandas as pd
import numpy as np
import networkx as nx

# Define paths relative to the script location
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir)) # parent of ai
ce_file = os.path.join(project_root, "tf2-finops", "cost_explorer_daily.csv")
cur_file = os.path.join(project_root, "tf2-finops", "cur_line_items.csv")
labels_file = os.path.join(project_root, "tf2-finops", "anomaly_labels_public.csv")

# Simulated Change Management (Jira / AWS Systems Manager Change Manager) database
# In production, this would query a real API to check for approved change tickets.
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

def holt_winters_anomaly_detection(series, alpha=0.3, beta=0.1, gamma=0.3, L=7, z_threshold=3.5, min_cost=50.0):
    n = len(series)
    if n < 14:
        return [False] * n
        
    y = np.log(series + 1)
    
    level = np.mean(y[:L])
    trend = np.mean(y[L:2*L] - y[:L]) / L
    season = list(y[:L] - level)
    
    forecasts = [0.0] * n
    errors = [0.0] * n
    anomalies = [False] * n
    
    levels = [level] * (2*L)
    trends = [trend] * (2*L)
    seasons = season * 2
    
    for t in range(2*L, n):
        fore = levels[-1] + trends[-1] + seasons[t-L]
        forecasts[t] = np.exp(fore) - 1
        
        val = y[t]
        actual_val = series[t]
        
        err = val - fore
        errors[t] = err
        
        new_level = alpha * (val - seasons[t-L]) + (1 - alpha) * (levels[-1] + trends[-1])
        new_trend = beta * (new_level - levels[-1]) + (1 - beta) * trends[-1]
        new_season = gamma * (val - new_level) + (1 - gamma) * seasons[t-L]
        
        levels.append(new_level)
        trends.append(new_trend)
        seasons.append(new_season)
        
        if t >= 14:
            past_errors = errors[14:t]
            if len(past_errors) > 0:
                std_err = np.std(past_errors)
                mean_err = np.mean(past_errors)
            else:
                std_err = 0.20
                mean_err = 0.0
            
            if std_err == 0.0:
                std_err = 0.20
            std_err = max(std_err, 0.20)
                
            z = (err - mean_err) / std_err
            if z > z_threshold and actual_val > min_cost:
                anomalies[t] = True
                
    return anomalies

def run_backtest():
    print("==================================================")
    print("RUNNING OFFLINE BACKTEST ON 3-MONTH AWS CUR DATA")
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

    res_daily = cur.groupby(["line_item_usage_start_date", "line_item_usage_account_name", "line_item_product_code", "line_item_resource_id", "resource_tags_user_team"], dropna=False)["line_item_unblended_cost"].sum().reset_index()
    
    detected_anomalies = {}
    groups = res_daily.groupby(["line_item_usage_account_name", "line_item_product_code", "line_item_resource_id", "resource_tags_user_team"], dropna=False)
    
    print("\nScanning dataset for anomalies...")
    for (account, product, resource_id, team), group in groups:
        group = group.sort_values("line_item_usage_start_date")
        group = group.set_index("line_item_usage_start_date").reindex(dates).reset_index()
        group["line_item_unblended_cost"] = group["line_item_unblended_cost"].fillna(0.0)
        
        costs = group["line_item_unblended_cost"].values
        team_name = str(team) if str(team) != "nan" else "unknown"
        
        # Pre-approved scheduled spikes are dynamically filtered out below during detection.
            
        # 1. Flat continuous spend (Orphan resources)
        non_zero_costs = costs[costs > 0]
        if len(non_zero_costs) > 30:
            mean_cost = np.mean(non_zero_costs)
            std_cost = np.std(non_zero_costs)
            cov = std_cost / mean_cost if mean_cost > 0 else 999
            if cov < 0.05 and mean_cost > 5.0:
                start_date = group[group["line_item_unblended_cost"] > 0]["line_item_usage_start_date"].min()
                detected_anomalies[resource_id] = {
                    "resource_id": resource_id,
                    "account": account,
                    "product": product,
                    "team": team_name,
                    "date": str(start_date.date()),
                    "cost_sample": round(mean_cost, 2),
                    "type": "idle_resource",
                    "reason": f"Flat continuous spend detected (${mean_cost:.2f}/day)."
                }
                continue

        # 2. Untagged spend scanner
        if team_name == "unknown" and np.sum(costs) > 500:
            start_date = group[group["line_item_unblended_cost"] > 0]["line_item_usage_start_date"].min()
            detected_anomalies[resource_id] = {
                "resource_id": resource_id,
                "account": account,
                "product": product,
                "team": team_name,
                "date": str(start_date.date()),
                "cost_sample": round(np.max(costs), 2),
                "type": "untagged_spend",
                "reason": f"Untagged resource with high accumulative spend."
            }
            continue
            
        # 3. Holt-Winters Spike detector
        anoms = holt_winters_anomaly_detection(costs, alpha=0.3, beta=0.1, gamma=0.3, L=7, z_threshold=3.5, min_cost=50.0)
        for t in range(len(dates)):
            if anoms[t]:
                date_str = str(dates[t].date())
                # Filter out pre-approved scheduled changes (e.g. load tests, migrations, flash sales)
                if is_change_approved(resource_id, date_str):
                    continue
                    
                anomaly_type = "sudden_spike"
                if product == "AmazonEC2" and "gpu" in str(resource_id):
                    anomaly_type = "runaway_usage"
                    
                detected_anomalies[resource_id] = {
                    "resource_id": resource_id,
                    "account": account,
                    "product": product,
                    "team": team_name,
                    "date": str(dates[t].date()),
                    "cost_sample": round(costs[t], 2),
                    "type": anomaly_type,
                    "reason": f"Holt-Winters cost spike to ${costs[t]:.2f}."
                }
                break
                
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
