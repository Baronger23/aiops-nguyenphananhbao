import json

def get_action_meta(action_name: str, actions_catalog: list[dict]) -> dict | None:
    for a in actions_catalog:
        if a["name"] == action_name:
            return a
    return None

def calculate_action_penalty(action_name: str, actions_catalog: list[dict], is_page_oncall: bool = False) -> float:
    meta = get_action_meta(action_name, actions_catalog)
    if not meta:
        return 999.0  # Infinite penalty for unknown action
        
    cost = meta.get("cost_min", 0.0)
    downtime = meta.get("downtime_min", 0.0)
    blast_radius = meta.get("blast_radius_services", 0.0)
    
    penalty = cost + 2.0 * downtime + 5.0 * blast_radius
    if is_page_oncall:
        penalty += 70.0  # Assign a virtual penalty to page_oncall to make it last resort
        
    return penalty

def select_action(retrieval_results: dict, actions_catalog: list[dict]) -> dict:
    max_sim = retrieval_results["max_similarity"]
    candidates = retrieval_results["candidates"]
    evidence = retrieval_results["evidence_neighbors"]
    top_3_neighbors = retrieval_results["top_3_neighbors"]
    
    # 1. OOD Check (Threshold = 0.35)
    if max_sim < 0.35:
        return {
            "selected_action": "page_oncall",
            "params": {"team": "platform-team"},
            "confidence": round(1.0 - max_sim, 2),
            "max_similarity": max_sim,
            "top_3_neighbors": top_3_neighbors,
            "consensus_score": 0.0,
            "reason": "Out of Distribution (OOD) - no similar historical incidents found.",
            "evidence": {
                "message": "Novel incident detected. Similarity is below OOD threshold (0.35).",
                "max_similarity": max_sim,
                "ood_threshold": 0.35,
                "candidate_votes": candidates,
                "evidence_neighbors": evidence,
                "neighbors_searched": len(evidence)
            }
        }
        
    # 2. Find max positive consensus score to scale success probability
    # Exclude page_oncall from max score calculation
    non_page_scores = [c["consensus_score"] for c in candidates if c["name"] != "page_oncall"]
    max_score = max(non_page_scores) if non_page_scores else 0.0
    if max_score <= 0.0:
        max_score = 1e-5
        
    # We always include page_oncall as a fallback candidate in the decision space
    has_page_oncall_candidate = False
    for c in candidates:
        if c["name"] == "page_oncall":
            has_page_oncall_candidate = True
            break
            
    if not has_page_oncall_candidate:
        candidates.append({
            "name": "page_oncall",
            "params": {"team": "platform-team"},
            "consensus_score": 0.0
        })
        
    evaluated = []
    
    for c in candidates:
        name = c["name"]
        params = c["params"]
        score = c["consensus_score"]
        
        meta = get_action_meta(name, actions_catalog)
        if not meta:
            continue
            
        if name == "page_oncall":
            p_success = 0.99
            penalty = calculate_action_penalty(name, actions_catalog, is_page_oncall=True)
        else:
            # Scale success probability by consensus score relative to maximum consensus score
            if score > 0:
                scale_ratio = score / max_score
                p_success = max(0.01, min(0.95, max_sim * scale_ratio))
            else:
                p_success = 0.01  # Negatively voted or non-voted actions are highly unlikely to succeed
            penalty = calculate_action_penalty(name, actions_catalog, is_page_oncall=False)
            
        # Expected Value calculation
        # Utility of success = 100 - penalty
        # Utility of failure = -150 - penalty
        ev = p_success * (100.0 - penalty) + (1.0 - p_success) * (-150.0 - penalty)
        
        # Blast Radius safety gate
        blast_radius = meta.get("blast_radius_services", 0)
        blocked_by_gate = False
        if blast_radius >= 3 and p_success < 0.65:
            blocked_by_gate = True
            
        evaluated.append({
            "name": name,
            "params": params,
            "p_success": p_success,
            "penalty": penalty,
            "ev": ev,
            "blocked": blocked_by_gate,
            "score": score,
            "blast_radius": blast_radius
        })
        
    # Filter out blocked candidates
    allowed = [e for e in evaluated if not e["blocked"]]
    
    if not allowed:
        # Fallback to page_oncall
        best = {
            "name": "page_oncall",
            "params": {"team": "platform-team"},
            "ev": -999.0,
            "p_success": 0.99,
            "score": 0.0
        }
    else:
        # Sort allowed by EV descending
        allowed.sort(key=lambda x: x["ev"], reverse=True)
        best = allowed[0]
        
    confidence = best["p_success"]
    
    justification = {
        "max_similarity": max_sim,
        "primary_candidate": best["name"],
        "primary_params": best["params"],
        "ev_evaluation": [
            {
                "action": e["name"],
                "params": e["params"],
                "ev": round(e["ev"], 2),
                "p_success": round(e["p_success"], 2),
                "penalty": round(e["penalty"], 2),
                "blocked": e["blocked"]
            } for e in evaluated
        ],
        "evidence_neighbors": evidence
    }
    
    return {
        "selected_action": best["name"],
        "params": best["params"],
        "confidence": round(confidence, 2),
        "max_similarity": max_sim,
        "top_3_neighbors": top_3_neighbors,
        "consensus_score": round(best["score"], 3),
        "reason": f"Selected {best['name']} based on Expected Value optimization.",
        "evidence": justification
    }
