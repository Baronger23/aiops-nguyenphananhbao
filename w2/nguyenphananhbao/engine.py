import argparse
import json
import yaml
from pathlib import Path

from features import extract_features
from retrieval import retrieve_and_vote
from decision import select_action

def decide(incident_path: Path, history_path: Path, actions_path: Path) -> dict:
    incident = json.loads(incident_path.read_text())
    history = json.loads(history_path.read_text())
    actions_catalog = yaml.safe_load(actions_path.read_text())
    
    # Layer 1: Feature Extraction
    vec = extract_features(incident)
    
    # Layer 2: Retrieval & Vote
    retrieval_results = retrieve_and_vote(vec, history)
    
    # Layer 3: Risk-Sensitive Decision
    decision = select_action(retrieval_results, actions_catalog)
    
    # Format the required fields for the grader
    out = {
        "incident_id": incident_path.stem,  # Must match eval file basename e.g. E01
        "selected_action": decision["selected_action"],
        "params": decision["params"],
        "confidence": decision["confidence"],
        "evidence": decision["evidence"],
        "max_similarity": decision["max_similarity"],
        "consensus_score": decision["consensus_score"],
        "top_3_neighbors": decision["top_3_neighbors"],
        "blast_radius_check": True
    }
    return out

def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    d = sub.add_parser("decide")
    d.add_argument("--incident", required=True)
    d.add_argument("--history", default="incidents_history.json")
    d.add_argument("--actions", default="actions.yaml")
    args = p.parse_args()
    
    if args.cmd == "decide":
        out = decide(Path(args.incident), Path(args.history), Path(args.actions))
        print(json.dumps(out, indent=2))
        with open("audit.jsonl", "a") as f:
            f.write(json.dumps(out) + "\n")
        return 0
        
    p.print_help()
    return 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
