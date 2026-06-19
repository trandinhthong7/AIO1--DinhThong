#!/usr/bin/env python3
"""Break-even calculator for the AIOps mini-platform."""

import math


def is_worth_it(
    num_services: int,
    incidents_per_month: int,
    avg_incident_duration_hours: float,
    downtime_cost_per_hour: float,
    expected_mttr_reduction_pct: float = 0.4,
    aiops_monthly_cost: float = 15_000,
) -> dict:
    if num_services < 0 or incidents_per_month < 0:
        raise ValueError("service and incident counts must be non-negative")
    if avg_incident_duration_hours < 0 or downtime_cost_per_hour < 0:
        raise ValueError("duration and downtime cost must be non-negative")
    if not 0 <= expected_mttr_reduction_pct <= 1:
        raise ValueError("expected_mttr_reduction_pct must be between 0 and 1")
    if aiops_monthly_cost < 0:
        raise ValueError("aiops_monthly_cost must be non-negative")

    downtime_hours = incidents_per_month * avg_incident_duration_hours
    monthly_value = downtime_hours * expected_mttr_reduction_pct * downtime_cost_per_hour
    roi = monthly_value / aiops_monthly_cost if aiops_monthly_cost else math.inf
    payback = aiops_monthly_cost / monthly_value if monthly_value > 0 else math.inf
    verdict = "worth_it" if roi > 1.5 else "marginal" if roi > 1.0 else "not_worth_it"
    return {
        "monthly_value": float(monthly_value),
        "monthly_cost": float(aiops_monthly_cost),
        "roi": float(roi),
        "payback_months": float(payback),
        "verdict": verdict,
    }


if __name__ == "__main__":
    print(
        is_worth_it(
            num_services=20,
            incidents_per_month=2,
            avg_incident_duration_hours=1,
            downtime_cost_per_hour=10_000,
            aiops_monthly_cost=15_000,
        )
    )
    print(
        is_worth_it(
            num_services=100,
            incidents_per_month=5,
            avg_incident_duration_hours=2,
            downtime_cost_per_hour=20_000,
            aiops_monthly_cost=25_000,
        )
    )
    # Ronki e-commerce: 80,000 orders/day and roughly 1,000 lost orders per
    # 15-minute outage justify a conservative downtime estimate of $50k/hour.
    print(
        is_worth_it(
            num_services=50,
            incidents_per_month=4,
            avg_incident_duration_hours=1.25,
            downtime_cost_per_hour=50_000,
            expected_mttr_reduction_pct=0.4,
            aiops_monthly_cost=30_000,
        )
    )
