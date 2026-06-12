# Lab — Evidence-Driven Remediation Engine

This project implements an evidence-driven remediation engine that analyzes microservice incidents using logs, traces, and metrics, retrieves similar historical incidents, and selects the optimal action using Expected Value (EV) decision theory.

## System Architecture

Dưới đây là sơ đồ kiến trúc đường ống xử lý (Pipeline) của hệ thống gồm 3 Layer chính và các luồng dữ liệu di chuyển giữa các cấu phần:

```mermaid
graph TD
    %% Define styles
    classDef inputStyle fill:#ffe6cc,stroke:#d79b00,stroke-width:2px;
    classDef processStyle fill:#dae8fc,stroke:#6c8ebf,stroke-width:2px;
    classDef outputStyle fill:#d5e8d4,stroke:#82b366,stroke-width:2px;
    
    %% Inputs
    Incident[Live Incident JSON<br/>- logs raw<br/>- traces raw<br/>- metrics window]:::inputStyle
    History[Historical Incident Corpus<br/>- log/trace/metric signatures<br/>- actions taken & outcome]:::inputStyle
    Actions[Actions Catalog YAML<br/>- cost, downtime<br/>- blast radius]:::inputStyle
    
    %% Layer 1
    subgraph Layer1 [Layer 1: Feature Extraction & Schema Bridging]
        F_Log[parse_raw_logs<br/>Map log raw to signatures]:::processStyle
        F_Trace[extract_trace_anomalies<br/>Calculate error_rate & p99_deviation]:::processStyle
        F_Metric[extract_metric_deltas<br/>Calculate metric deltas]:::processStyle
        F_Svc[derive_affected_services<br/>Alert + trace anomalies + log bursts]:::processStyle
    end
    
    %% Layer 2
    subgraph Layer2 [Layer 2: Retrieval & Voting]
        SvcMap[Service Mapper<br/>Map history service to query primary service]:::processStyle
        SimCalc[calculate_similarity<br/>Weighted Jaccard on features<br/>Dynamic weight normalization]:::processStyle
        VoteAgg[retrieve_and_vote<br/>Outcome-weighted voting<br/>Score = Sim * OutcomeWeight]:::processStyle
    end
    
    %% Layer 3
    subgraph Layer3 [Layer 3: Decision Maker]
        OOD{OOD Check:<br/>max_similarity < 0.35?}:::processStyle
        EVCalc[calculate_action_penalty & EV<br/>Virtual page_oncall penalty]:::processStyle
        BRGate{Blast Radius Gate:<br/>blast_radius >= 3 & p_success < 0.65?}:::processStyle
        Select[Select Max EV Action]:::processStyle
    end
    
    %% Outputs
    Output[audit.jsonl & stdout<br/>- selected_action<br/>- confidence<br/>- detailed evidence]:::outputStyle
    
    %% Connections
    Incident --> F_Log
    Incident --> F_Trace
    Incident --> F_Metric
    Incident --> F_Svc
    
    F_Log --> SimCalc
    F_Trace --> SimCalc
    F_Metric --> SimCalc
    F_Svc --> SimCalc
    History --> SimCalc
    
    SimCalc --> SvcMap
    SvcMap --> VoteAgg
    
    VoteAgg --> OOD
    Actions --> EVCalc
    
    OOD -- Yes --> Output
    OOD -- No --> EVCalc
    
    EVCalc --> BRGate
    BRGate -- Yes/Blocked --> Output
    BRGate -- No/Allowed --> Select
    
    Select --> Output
```

## Setup & How to Run

1. **Install Dependencies**:
   Ensure you have Python 3.12 installed. Install the required YAML library:
   ```bash
   pip install pyyaml
   ```

2. **Run the Engine on an Incident**:
   Run the engine CLI using the `decide` command:
   ```bash
   python engine.py decide --incident eval/E01.json \
                           --history incidents_history.json \
                           --actions actions.yaml
   ```

3. **Verify Decisions**:
   You can run the engine on all 8 evaluation incidents and run the auto-grader to verify predictions:
   ```bash
   # In PowerShell (Windows):
   if (Test-Path audit.jsonl) { Remove-Item audit.jsonl }
   1..8 | ForEach-Object { $i = "{0:D2}" -f $_; python engine.py decide --incident eval/E$i.json }
   python grade.py --audit audit.jsonl --expected eval/expected.json
   ```

Expected Output: `Correct: 8/8` with an auto-rubric estimate of `85/85` points.
