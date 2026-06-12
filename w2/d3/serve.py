import json
import os
import time
from collections import Counter, defaultdict, deque
from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import FastAPI, HTTPException, Response

try:
    from pydantic import BaseModel, ConfigDict, Field, model_validator

    PYDANTIC_V2 = True
except ImportError:  # pragma: no cover - compatibility for older lab images
    from pydantic import BaseModel, Field, root_validator

    ConfigDict = None
    PYDANTIC_V2 = False

try:
    import networkx as nx
except ImportError:  # pragma: no cover - networkx is optional for this lab
    nx = None

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Histogram, generate_latest
except ImportError:  # pragma: no cover - metrics are optional
    CONTENT_TYPE_LATEST = None
    Histogram = None
    generate_latest = None


BASE_DIR = Path(__file__).resolve().parent
D1_DIR = (BASE_DIR / "../d1").resolve()
D2_DIR = (BASE_DIR / "../d2").resolve()

ALERTS_PATH = D1_DIR / "dataset" / "alerts_sample.jsonl"
GRAPH_PATH = D1_DIR / "dataset" / "services.json"
HISTORY_PATH = D2_DIR / "dataset" / "incidents_history.json"

DEFAULT_GAP_SEC = 120
DEFAULT_MAX_HOP = 2
SEVERITY_RANK = {"info": 0, "warn": 1, "warning": 1, "crit": 2, "critical": 2}
AIOPS_USE_LLM = os.getenv("AIOPS_USE_LLM", "false").lower() == "true"

REQUEST_LATENCY = (
    Histogram("aiops_request_latency_seconds", "Request latency by path", ["path", "method"])
    if Histogram is not None
    else None
)


if PYDANTIC_V2:

    class AlertInput(BaseModel):
        model_config = ConfigDict(extra="allow")

        id: Optional[str] = None
        service: str
        metric: str
        severity: str
        ts: Optional[str] = None
        timestamp: Optional[str] = None
        value: Optional[Any] = None
        threshold: Optional[Any] = None
        labels: Dict[str, Any] = Field(default_factory=dict)

        @model_validator(mode="before")
        @classmethod
        def normalize_time_field(cls, values: Any) -> Any:
            if isinstance(values, dict) and not values.get("ts") and values.get("timestamp"):
                values = dict(values)
                values["ts"] = values["timestamp"]
            return values

        @model_validator(mode="after")
        def require_time_field(self) -> "AlertInput":
            if not self.ts and not self.timestamp:
                raise ValueError("alert must include ts or timestamp")
            return self

else:

    class AlertInput(BaseModel):
        id: Optional[str] = None
        service: str
        metric: str
        severity: str
        ts: Optional[str] = None
        timestamp: Optional[str] = None
        value: Optional[Any] = None
        threshold: Optional[Any] = None
        labels: Dict[str, Any] = Field(default_factory=dict)

        @root_validator(pre=True)
        def normalize_time_field(cls, values: Dict[str, Any]) -> Dict[str, Any]:
            if isinstance(values, dict) and not values.get("ts") and values.get("timestamp"):
                values = dict(values)
                values["ts"] = values["timestamp"]
            return values

        @root_validator
        def require_time_field(cls, values: Dict[str, Any]) -> Dict[str, Any]:
            if not values.get("ts") and not values.get("timestamp"):
                raise ValueError("alert must include ts or timestamp")
            return values

        class Config:
            extra = "allow"


class IncidentRequest(BaseModel):
    alerts: Optional[List[AlertInput]] = None
    gap_sec: int = Field(DEFAULT_GAP_SEC, ge=1, le=3600)
    max_hop: int = Field(DEFAULT_MAX_HOP, ge=1, le=10)


app = FastAPI(title="AIOps W2-D3 RCA Service", version="1.0")


@app.middleware("http")
async def latency_middleware(request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    response.headers["X-Process-Time-Ms"] = f"{elapsed * 1000:.2f}"
    if REQUEST_LATENCY is not None:
        REQUEST_LATENCY.labels(path=request.url.path, method=request.method).observe(elapsed)
    return response


def parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if not value:
        raise ValueError("missing timestamp")
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def format_ts(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def model_to_dict(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        data = model.model_dump()
    else:
        data = model.dict()
    if not data.get("ts") and data.get("timestamp"):
        data["ts"] = data["timestamp"]
    return data


def fingerprint(alert: Dict[str, Any]) -> str:
    return f"{alert['service']}|{alert['metric']}|{alert['severity']}"


def prepare_alerts(raw_alerts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    prepared = []
    for idx, raw in enumerate(raw_alerts, start=1):
        alert = dict(raw)
        alert.setdefault("id", f"a-{idx:04d}")
        alert["ts"] = alert.get("ts") or alert.get("timestamp")
        alert["timestamp"] = parse_ts(alert["ts"])
        alert["fingerprint"] = fingerprint(alert)
        prepared.append(alert)
    return sorted(prepared, key=lambda item: item["timestamp"])


def load_alerts_jsonl(path: Path) -> List[Dict[str, Any]]:
    alerts = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                alerts.append(json.loads(line))
    return alerts


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_static_data() -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    return read_json(GRAPH_PATH), read_json(HISTORY_PATH), load_alerts_jsonl(ALERTS_PATH)


def service_name(item: Any) -> str:
    return item["name"] if isinstance(item, dict) else item


def build_graph(graph_data: Dict[str, Any]) -> Tuple[Any, Dict[str, Set[str]], Dict[str, Set[str]], Set[str]]:
    stores = {store["name"] for store in graph_data.get("stores", [])}
    nodes = {service_name(service) for service in graph_data.get("services", [])} | stores

    adjacency: Dict[str, Set[str]] = defaultdict(set)
    reverse: Dict[str, Set[str]] = defaultdict(set)
    for node in nodes:
        adjacency[node]
        reverse[node]

    nx_graph = nx.DiGraph() if nx is not None else None
    if nx_graph is not None:
        nx_graph.add_nodes_from(nodes)

    for edge in graph_data.get("edges", []):
        src, dst = (edge["from"], edge["to"]) if isinstance(edge, dict) else edge
        adjacency[src].add(dst)
        reverse[dst].add(src)
        adjacency[dst]
        reverse[src]
        if nx_graph is not None:
            nx_graph.add_edge(src, dst)
    return nx_graph, adjacency, reverse, stores


def undirected_neighbors(adjacency: Dict[str, Set[str]], reverse: Dict[str, Set[str]], node: str) -> Set[str]:
    return set(adjacency[node]) | set(reverse[node])


def within_hops(
    adjacency: Dict[str, Set[str]],
    reverse: Dict[str, Set[str]],
    start: str,
    max_hop: int,
    stores: Set[str],
    alerted_services: Set[str],
) -> Set[str]:
    seen = {start}
    queue = deque([(start, 0)])
    while queue:
        node, depth = queue.popleft()
        if depth == max_hop:
            continue
        if node in stores and node not in alerted_services and node != start:
            continue
        for nxt in undirected_neighbors(adjacency, reverse, node):
            if nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, depth + 1))
    return seen


def dedup(alerts: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Counter]:
    counts = Counter(alert["fingerprint"] for alert in alerts)
    representatives: Dict[str, Dict[str, Any]] = {}
    for alert in alerts:
        representatives.setdefault(alert["fingerprint"], alert)
    return [dict(alert, duplicate_count=counts[fp]) for fp, alert in representatives.items()], counts


def session_groups(alerts: List[Dict[str, Any]], gap_sec: int) -> List[List[Dict[str, Any]]]:
    sessions = []
    current = []
    last_ts = None
    for alert in alerts:
        if last_ts is None or (alert["timestamp"] - last_ts).total_seconds() <= gap_sec:
            current.append(alert)
        else:
            sessions.append(current)
            current = [alert]
        last_ts = alert["timestamp"]
    if current:
        sessions.append(current)
    return sessions


def topology_group(
    session: List[Dict[str, Any]],
    adjacency: Dict[str, Set[str]],
    reverse: Dict[str, Set[str]],
    stores: Set[str],
    max_hop: int,
) -> List[List[Dict[str, Any]]]:
    unassigned = list(session)
    alerted_services = {alert["service"] for alert in session}
    groups = []
    while unassigned:
        seed = max(
            unassigned,
            key=lambda alert: (SEVERITY_RANK.get(alert["severity"], -1), -alert["timestamp"].timestamp()),
        )
        reachable = within_hops(adjacency, reverse, seed["service"], max_hop, stores, alerted_services)
        group = [alert for alert in unassigned if alert["service"] in reachable]
        grouped_ids = {alert["id"] for alert in group}
        groups.append(group)
        unassigned = [alert for alert in unassigned if alert["id"] not in grouped_ids]
    return sorted(groups, key=lambda group: min(alert["timestamp"] for alert in group))


def build_cluster(cluster_index: int, session_index: int, alerts: List[Dict[str, Any]]) -> Dict[str, Any]:
    timestamps = [alert["timestamp"] for alert in alerts]
    severities = [alert["severity"] for alert in alerts]
    max_severity = max(severities, key=lambda sev: SEVERITY_RANK.get(sev, -1))
    return {
        "cluster_id": f"c-{session_index:03d}-{cluster_index:03d}",
        "alert_count": len(alerts),
        "services": sorted({alert["service"] for alert in alerts}),
        "time_range": [format_ts(min(timestamps)), format_ts(max(timestamps))],
        "max_severity": max_severity,
        "fingerprints": sorted({alert["fingerprint"] for alert in alerts}),
    }


def correlate(
    alerts: List[Dict[str, Any]],
    graph_data: Dict[str, Any],
    gap_sec: int = DEFAULT_GAP_SEC,
    max_hop: int = DEFAULT_MAX_HOP,
) -> Dict[str, Any]:
    prepared = prepare_alerts(alerts)
    _, adjacency, reverse, stores = build_graph(graph_data)
    dedup(prepared)
    sessions = session_groups(prepared, gap_sec)

    clusters = []
    for session_index, session in enumerate(sessions, start=1):
        for cluster_index, group in enumerate(topology_group(session, adjacency, reverse, stores, max_hop)):
            clusters.append(build_cluster(cluster_index, session_index, group))

    return {
        "input_alerts": len(prepared),
        "output_clusters": len(clusters),
        "reduction_ratio": round(1 - len(clusters) / len(prepared), 2) if prepared else 0,
        "clusters": clusters,
    }


def shortest_distance(adjacency: Dict[str, Set[str]], start: str, target: str) -> Optional[int]:
    if start == target:
        return 0
    queue = deque([(start, 0)])
    seen = {start}
    while queue:
        node, distance = queue.popleft()
        for nxt in adjacency[node]:
            if nxt == target:
                return distance + 1
            if nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, distance + 1))
    return None


def reachable_upstream_count(reverse: Dict[str, Set[str]], candidate: str, services: Set[str]) -> int:
    queue = deque([candidate])
    seen = {candidate}
    while queue:
        node = queue.popleft()
        for upstream in reverse[node]:
            if upstream not in seen:
                seen.add(upstream)
                queue.append(upstream)
    return len(seen & services)


def cluster_alerts(cluster: Dict[str, Any], alerts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    fingerprints = set(cluster["fingerprints"])
    services = set(cluster["services"])
    start, end = [parse_ts(ts) for ts in cluster["time_range"]]
    prepared = prepare_alerts(alerts)
    return [
        alert
        for alert in prepared
        if alert["service"] in services and alert["fingerprint"] in fingerprints and start <= alert["timestamp"] <= end
    ]


def first_alert_by_service(cluster: Dict[str, Any], alerts: List[Dict[str, Any]]) -> Dict[str, datetime]:
    first = {}
    for alert in cluster_alerts(cluster, alerts):
        svc = alert["service"]
        if svc not in first or alert["timestamp"] < first[svc]:
            first[svc] = alert["timestamp"]
    return first


def graph_score(
    service: str,
    cluster_services: List[str],
    adjacency: Dict[str, Set[str]],
    reverse: Dict[str, Set[str]],
    stores: Set[str],
) -> float:
    services = set(cluster_services)
    impact = reachable_upstream_count(reverse, service, services) / max(len(services), 1)
    depth_distance = shortest_distance(adjacency, "edge-lb", service)
    depth = min(depth_distance / 3, 1.0) if depth_distance is not None else 0.2
    store_penalty = 0.85 if service in stores else 1.0
    return min(1.0, store_penalty * (0.7 * impact + 0.3 * depth))


def timestamp_score(service: str, first_by_service: Dict[str, datetime]) -> float:
    if not first_by_service or service not in first_by_service:
        return 0.0
    times = list(first_by_service.values())
    start, end = min(times), max(times)
    span = max((end - start).total_seconds(), 1)
    offset = (first_by_service[service] - start).total_seconds()
    return 1 - (offset / span)


def rank_cluster(
    cluster: Dict[str, Any],
    alerts: List[Dict[str, Any]],
    adjacency: Dict[str, Set[str]],
    reverse: Dict[str, Set[str]],
    stores: Set[str],
) -> List[Tuple[str, float]]:
    first = first_alert_by_service(cluster, alerts)
    rows = []
    for service in cluster["services"]:
        g_score = graph_score(service, cluster["services"], adjacency, reverse, stores)
        t_score = timestamp_score(service, first)
        final_score = round(0.6 * g_score + 0.4 * t_score, 2)
        rows.append((service, final_score))
    return sorted(rows, key=lambda row: row[1], reverse=True)


def incident_similarity(cluster: Dict[str, Any], incident: Dict[str, Any]) -> float:
    cluster_services = set(cluster["services"])
    incident_services = set(incident.get("services", []))
    cluster_fps = set(cluster.get("fingerprints", []))
    incident_fps = set(incident.get("fingerprints", []))

    root_bonus = 0.3 if incident.get("root_cause_service") in cluster_services else 0.0
    service_union = cluster_services | incident_services
    service_overlap = len(cluster_services & incident_services) / max(len(service_union), 1)
    severity_bonus = 0.15 if incident.get("severity") == cluster.get("max_severity") else 0.0
    fp_union = cluster_fps | incident_fps
    fp_overlap = len(cluster_fps & incident_fps) / max(len(fp_union), 1)
    return round(root_bonus + 0.35 * service_overlap + severity_bonus + 0.2 * fp_overlap, 3)


def top_k_similar(cluster: Dict[str, Any], incidents_history: List[Dict[str, Any]], k: int = 3):
    scored = [(incident_similarity(cluster, incident), incident) for incident in incidents_history]
    return sorted(scored, key=lambda item: item[0], reverse=True)[:k]


def classify_from_history(cluster: Dict[str, Any], incidents_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    similar = top_k_similar(cluster, incidents_history, 3)
    if not similar or similar[0][0] <= 0:
        return {
            "class": "other",
            "actions": ["Investigate manually"],
            "confidence": 0.2,
            "similar_incidents": [],
            "method": "graph+retrieval-fallback",
        }
    best_score, best = similar[0]
    return {
        "class": best["root_cause_class"],
        "actions": best.get("actions", ["Investigate manually"]),
        "confidence": min(0.95, round(0.55 + best_score * 0.45, 2)),
        "similar_incidents": [incident["incident_id"] for _, incident in similar],
        "method": "graph+retrieval",
    }


def reasoning_for(cluster: Dict[str, Any], top_service: str) -> str:
    if cluster["alert_count"] == 1:
        return (
            f"{top_service} is the only alerted service in this cluster, so the RCA remains local "
            "unless more topology evidence appears."
        )
    return (
        f"{top_service} is ranked highest because it is downstream in the dependency graph, can explain "
        "upstream/victim alerts, and its alert appears early in the cluster time range."
    )


def run_rca(
    cluster_summary: Dict[str, Any],
    alerts: List[Dict[str, Any]],
    graph_data: Dict[str, Any],
    incidents_history: List[Dict[str, Any]],
) -> Dict[str, Any]:
    _, adjacency, reverse, stores = build_graph(graph_data)
    results = []
    for cluster in cluster_summary["clusters"]:
        ranked = rank_cluster(cluster, alerts, adjacency, reverse, stores)
        graph_top3 = [[service, score] for service, score in ranked[:3]]
        root_cause = graph_top3[0][0] if graph_top3 else "unknown"
        classification = classify_from_history(cluster, incidents_history)
        results.append(
            {
                "cluster_id": cluster["cluster_id"],
                "graph_top3": graph_top3,
                "root_cause": root_cause,
                "class": classification["class"],
                "confidence": classification["confidence"],
                "actions": classification["actions"],
                "reasoning": reasoning_for(cluster, root_cause),
                "similar_incidents": classification["similar_incidents"],
                "method": classification["method"],
            }
        )
    return {"clusters_analyzed": len(results), "results": results}


@app.get("/healthz")
def healthz() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> Dict[str, Any]:
    required = {
        "alerts": ALERTS_PATH,
        "graph": GRAPH_PATH,
        "history": HISTORY_PATH,
    }
    missing = {name: str(path) for name, path in required.items() if not path.exists()}
    if missing:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "missing": missing})
    load_static_data()
    return {"status": "ready", "llm_enabled": AIOPS_USE_LLM, "networkx_enabled": nx is not None}


@app.post("/incident")
def incident(request: IncidentRequest) -> Dict[str, Any]:
    graph_data, incidents_history, sample_alerts = load_static_data()
    if request.alerts:
        raw_alerts = [model_to_dict(alert) for alert in request.alerts]
    else:
        raw_alerts = deepcopy(sample_alerts)

    cluster_summary = correlate(raw_alerts, graph_data, request.gap_sec, request.max_hop)
    rca = run_rca(cluster_summary, raw_alerts, graph_data, incidents_history)
    primary = rca["results"][0] if rca["results"] else {}
    return {
        "clusters": cluster_summary["clusters"],
        "root_cause": primary.get("root_cause"),
        "recommended_actions": primary.get("actions", []),
        "rca": rca["results"],
        "summary": {
            "input_alerts": cluster_summary["input_alerts"],
            "output_clusters": cluster_summary["output_clusters"],
            "reduction_ratio": cluster_summary["reduction_ratio"],
            "gap_sec": request.gap_sec,
            "max_hop": request.max_hop,
            "llm_enabled": AIOPS_USE_LLM,
        },
    }


if generate_latest is not None:

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
