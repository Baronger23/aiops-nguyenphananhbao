import json
from features import parse_metric_delta

def get_primary_anomalous_service(alert_service: str, trace_anomalies: list[dict]) -> str:
    adj = {}
    for t in trace_anomalies:
        if t["p99_deviation_ratio"] > 1.3 or t["error_rate"] > 0.05:
            if t["from"] not in adj:
                adj[t["from"]] = []
            adj[t["from"]].append(t["to"])
            
    visited = set()
    last_api_service = alert_service
    queue = [alert_service]
    while queue:
        curr = queue.pop(0)
        if curr in visited:
            continue
        visited.add(curr)
        if not (curr.endswith("-db") or curr.endswith("-redis") or "events" in curr or curr.endswith("-db-replica") or "redis" in curr or "kafka" in curr):
            last_api_service = curr
        if curr in adj:
            for neighbor in adj[curr]:
                if neighbor not in visited:
                    queue.append(neighbor)
    return last_api_service

def map_service_name(hist_svc: str, live_primary: str, hist_primary: str) -> str:
    if not hist_svc:
        return ""
    if hist_svc == hist_primary:
        return live_primary
    if hist_svc.endswith("-db") and live_primary.endswith("-svc"):
        return live_primary.replace("-svc", "-db")
    if hist_svc.endswith("-redis") and live_primary.endswith("-svc"):
        return live_primary.replace("-svc", "-redis")
    return hist_svc

def map_history_action_to_catalog(action_str: str, live_primary: str, hist_primary: str) -> dict:
    parts = action_str.split(":")
    name = parts[0]
    params = {}
    
    if name == "rollback_service":
        svc = parts[1] if len(parts) > 1 else ""
        params["service"] = map_service_name(svc, live_primary, hist_primary)
        params["target_version"] = parts[2] if len(parts) > 2 else "previous"
    elif name == "increase_pool_size":
        svc = parts[1] if len(parts) > 1 else ""
        params["service"] = map_service_name(svc, live_primary, hist_primary)
        params["from_value"] = parts[2] if len(parts) > 2 else "50"
        params["to_value"] = parts[3] if len(parts) > 3 else "100"
    elif name == "restart_pod":
        svc = parts[1] if len(parts) > 1 else ""
        params["service"] = map_service_name(svc, live_primary, hist_primary)
        params["pod_selector"] = parts[2] if len(parts) > 2 else "default"
    elif name == "dns_config_rollback":
        params["configmap_name"] = parts[1] if len(parts) > 1 else "kube-dns"
        params["target_revision"] = parts[2] if len(parts) > 2 else "previous"
    elif name == "network_policy_revert":
        params["policy_name"] = parts[1] if len(parts) > 1 else "default-deny"
    elif name == "page_oncall":
        params["team"] = parts[1] if len(parts) > 1 else "platform-team"
        
    return {"name": name, "params": params}

def calculate_similarity(q: dict, h: dict, live_primary: str) -> float:
    # Get mapped historical entry before comparing
    hist_primary = h["affected_services"][0] if h.get("affected_services") else ""
    
    # 1. Alert service matching
    alert_svc = q["trigger_alert"]["service"]
    # Map historical affected services to query context
    h_affected_mapped = [map_service_name(s, live_primary, hist_primary) for s in h.get("affected_services", [])]
    alert_match = 1.0 if alert_svc in h_affected_mapped else 0.0
    
    # 2. Log similarity (Jaccard on matching log signatures)
    q_logs = set(q.get("log_signatures", []))
    h_logs = set(h.get("log_signatures", []))
    if not q_logs and not h_logs:
        log_match = 1.0
        log_weight = 0.35
    elif not h_logs:
        # History has no log signatures specified, treat log match as not applicable
        log_match = 1.0
        log_weight = 0.0
    else:
        log_match = len(q_logs.intersection(h_logs)) / len(q_logs.union(h_logs))
        log_weight = 0.35
        
    # 3. Trace similarity
    q_edges = {(t["from"], t["to"]) for t in q.get("trace_signatures", [])}
    h_edges = set()
    for t in h.get("trace_signatures", []):
        f_mapped = map_service_name(t["from"], live_primary, hist_primary)
        t_mapped = map_service_name(t["to"], live_primary, hist_primary)
        h_edges.add((f_mapped, t_mapped))
        
    if not h_edges:
        # History has no trace signatures, don't penalize
        trace_match = 1.0
        trace_weight = 0.0
    elif not q_edges:
        trace_match = 0.0
        trace_weight = 0.35
    else:
        edge_intersect = q_edges.intersection(h_edges)
        if not edge_intersect:
            trace_match = 0.0
            trace_weight = 0.35
        else:
            edge_similarities = []
            q_by_edge = {(t["from"], t["to"]): t for t in q["trace_signatures"]}
            h_by_edge = {}
            for t in h["trace_signatures"]:
                f_mapped = map_service_name(t["from"], live_primary, hist_primary)
                t_mapped = map_service_name(t["to"], live_primary, hist_primary)
                h_by_edge[(f_mapped, t_mapped)] = t
                
            for edge in edge_intersect:
                qe = q_by_edge[edge]
                he = h_by_edge[edge]
                
                err_diff = abs(qe.get("error_rate", 0.0) - he.get("error_rate", 0.0))
                err_sim = max(0.0, 1.0 - err_diff)
                
                qd = qe.get("p99_deviation_ratio", 1.0)
                hd = he.get("p99_deviation_ratio", 1.0)
                dev_diff = abs(qd - hd) / max(1e-5, qd + hd)
                dev_sim = max(0.0, 1.0 - dev_diff)
                
                edge_similarities.append(0.5 * err_sim + 0.5 * dev_sim)
                
            jaccard = len(edge_intersect) / len(q_edges.union(h_edges))
            trace_match = jaccard * (sum(edge_similarities) / len(edge_similarities))
            trace_weight = 0.35
            
    # 4. Metric similarity
    q_metrics = {(m["service"], m["metric"]) for m in q.get("metric_signatures", [])}
    h_metrics = set()
    for m in h.get("metric_signatures", []):
        svc_mapped = map_service_name(m["service"], live_primary, hist_primary)
        h_metrics.add((svc_mapped, m["metric"]))
        
    if not h_metrics:
        metric_match = 1.0
        metric_weight = 0.0
    elif not q_metrics:
        metric_match = 0.0
        metric_weight = 0.10
    else:
        metric_intersect = q_metrics.intersection(h_metrics)
        if not metric_intersect:
            metric_match = 0.0
            metric_weight = 0.10
        else:
            metric_similarities = []
            q_by_met = {(m["service"], m["metric"]): m for m in q["metric_signatures"]}
            h_by_met = {}
            for m in h["metric_signatures"]:
                svc_mapped = map_service_name(m["service"], live_primary, hist_primary)
                h_by_met[(svc_mapped, m["metric"])] = m
                
            for met in metric_intersect:
                qm = q_by_met[met]
                hm = h_by_met[met]
                
                try:
                    q_before, q_after = parse_metric_delta(qm["delta"])
                    h_before, h_after = parse_metric_delta(hm["delta"])
                    
                    q_ratio = q_after / max(1e-5, q_before)
                    h_ratio = h_after / max(1e-5, h_before)
                    
                    ratio_diff = abs(q_ratio - h_ratio) / max(1e-5, q_ratio + h_ratio)
                    ratio_sim = max(0.0, 1.0 - ratio_diff)
                    metric_similarities.append(ratio_sim)
                except Exception:
                    metric_similarities.append(0.5)
                    
            jaccard = len(metric_intersect) / len(q_metrics.union(h_metrics))
            metric_match = jaccard * (sum(metric_similarities) / len(metric_similarities))
            metric_weight = 0.10
            
    # 5. Affected services similarity
    q_affected = set(q.get("affected_services", []))
    h_affected = set(h_affected_mapped)
    if not q_affected and not h_affected:
        affected_match = 1.0
    elif not q_affected or not h_affected:
        affected_match = 0.0
    else:
        affected_match = len(q_affected.intersection(h_affected)) / len(q_affected.union(h_affected))
        
    w_alert = 0.10
    w_affected = 0.10
    
    total_weight = w_alert + w_affected + log_weight + trace_weight + metric_weight
    weighted_score = (w_alert * alert_match +
                      w_affected * affected_match +
                      log_weight * log_match +
                      trace_weight * trace_match +
                      metric_weight * metric_match)
                      
    return weighted_score / total_weight if total_weight > 0 else 0.0

def retrieve_and_vote(query: dict, history: list[dict], top_k: int = 3) -> dict:
    # Identify live query primary service
    live_primary = get_primary_anomalous_service(
        query["trigger_alert"]["service"],
        query["trace_signatures"]
    )
    
    scored = []
    for h in history:
        sim = calculate_similarity(query, h, live_primary)
        scored.append((sim, h))
        
    scored.sort(key=lambda x: x[0], reverse=True)
    
    top_neighbors = scored[:top_k]
    max_sim = scored[0][0] if scored else 0.0
    
    # Voting aggregation
    votes = {}
    evidence = []
    
    for sim, h in top_neighbors:
        if sim < 0.2:
            continue
            
        hist_primary = h["affected_services"][0] if h.get("affected_services") else ""
        
        outcome = h.get("outcome", "success")
        if outcome == "success":
            outcome_weight = 1.0
        elif outcome == "partial":
            outcome_weight = 0.5
        else:
            outcome_weight = -1.0
            
        vote_weight = sim * outcome_weight
        
        evidence.append({
            "neighbor_id": h["id"],
            "root_cause_class": h["root_cause_class"],
            "similarity": round(sim, 3),
            "outcome": outcome,
            "vote_weight": round(vote_weight, 3),
            "actions_taken": h["actions_taken"]
        })
        
        for action_str in h.get("actions_taken", []):
            mapped_action = map_history_action_to_catalog(action_str, live_primary, hist_primary)
            param_key = json.dumps(mapped_action["params"], sort_keys=True)
            action_key = (mapped_action["name"], param_key)
            
            if action_key not in votes:
                votes[action_key] = {
                    "action": mapped_action,
                    "score": 0.0
                }
            votes[action_key]["score"] += vote_weight
            
    candidates = []
    for action_key, v in votes.items():
        candidates.append({
            "name": v["action"]["name"],
            "params": v["action"]["params"],
            "consensus_score": round(v["score"], 3)
        })
        
    candidates.sort(key=lambda x: x["consensus_score"], reverse=True)
    
    return {
        "max_similarity": round(max_sim, 3),
        "candidates": candidates,
        "evidence_neighbors": evidence,
        "top_3_neighbors": [n["id"] for _, n in top_neighbors]
    }
