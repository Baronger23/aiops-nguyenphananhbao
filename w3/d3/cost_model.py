#!/usr/bin/env python3
"""Cost-benefit and ROI model for AIOps Platform.

Defines the is_worth_it function and evaluates three scenarios.
"""

def is_worth_it(
    num_services: int,
    incidents_per_month: int,
    avg_incident_duration_hours: float,
    downtime_cost_per_hour: float,
    expected_mttr_reduction_pct: float = 0.4,
    aiops_monthly_cost: float = 15_000,
) -> dict:
    """Calculates monthly value, cost, ROI, payback period, and returns a verdict.

    Verdict rules:
      roi > 1.5 → worth_it
      1.0 < roi <= 1.5 → marginal
      roi <= 1.0 → not_worth_it
    """
    # Monthly value is the downtime cost avoided by reducing MTTR
    monthly_value = (
        incidents_per_month 
        * avg_incident_duration_hours 
        * downtime_cost_per_hour 
        * expected_mttr_reduction_pct
    )
    monthly_cost = float(aiops_monthly_cost)

    if monthly_cost == 0:
        roi = float("inf")
        payback_months = 0.0
    else:
        roi = monthly_value / monthly_cost
        payback_months = monthly_cost / monthly_value if monthly_value > 0 else float("inf")

    # Verdict rules
    if roi > 1.5:
        verdict = "worth_it"
    elif 1.0 < roi <= 1.5:
        verdict = "marginal"
    else:
        verdict = "not_worth_it"

    return {
        "monthly_value": float(monthly_value),
        "monthly_cost": float(monthly_cost),
        "roi": float(roi),
        "payback_months": float(payback_months),
        "verdict": verdict,
    }


if __name__ == "__main__":
    # Scenario 1: Small-scale application
    print("Scenario 1:")
    print(is_worth_it(
        num_services=20, 
        incidents_per_month=2,
        avg_incident_duration_hours=1.0, 
        downtime_cost_per_hour=10_000.0,
        aiops_monthly_cost=15_000
    ))
    print()

    # Scenario 2: Mid-scale enterprise
    print("Scenario 2:")
    print(is_worth_it(
        num_services=100, 
        incidents_per_month=5,
        avg_incident_duration_hours=2.0, 
        downtime_cost_per_hour=20_000.0,
        aiops_monthly_cost=25_000
    ))
    print()

    # Scenario 3: E-commerce Platform (Bao's Custom Scenario)
    # Industry: Online Retail / E-commerce with $1B Annual GMV (~$114,000 revenue per hour).
    # Defense of Downtime Cost: 
    # An hour of downtime directly stops checkout transactions, causing ~$114,000 in immediate lost sales.
    # Factoring in marketing/ad spend waste, customer support overload, and brand trust degradation,
    # a conservative estimate for the total downtime cost is $120,000 per hour.
    # The AIOps monthly cost ($20,000) includes license fees plus 0.5 FTE engineer maintenance time.
    print("Scenario 3 (E-commerce / Retail):")
    print(is_worth_it(
        num_services=50,
        incidents_per_month=3,
        avg_incident_duration_hours=1.5,
        downtime_cost_per_hour=120_000.0,
        expected_mttr_reduction_pct=0.4,
        aiops_monthly_cost=20_000.0
    ))
