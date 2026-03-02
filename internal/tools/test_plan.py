from __future__ import annotations

from internal.schemas.state import TestPlanItem
from internal.tools.runner import classify_risk


def build_test_plan(commands: list[str], network_indicator_detected: bool = False) -> list[TestPlanItem]:
    items: list[TestPlanItem] = []
    for idx, cmd in enumerate(commands, start=1):
        base_risk = classify_risk(cmd)
        risk = _elevate_risk_for_network(base_risk, network_indicator_detected)
        reason = _reason_for_risk(risk, network_indicator_detected, base_risk)
        fallback = "python -m compileall ." if risk in {"mid", "high"} else None
        items.append(
            TestPlanItem(
                id=f"test-{idx}",
                cmd=cmd,
                risk=risk,
                reason=reason,
                fallback=fallback,
            )
        )
    return items


def _elevate_risk_for_network(risk: str, network_indicator_detected: bool) -> str:
    if network_indicator_detected and risk == "low":
        return "mid"
    return risk


def _reason_for_risk(risk: str, network_indicator_detected: bool, base_risk: str) -> str:
    if network_indicator_detected and base_risk == "low" and risk == "mid":
        return "Network indicator detected in touched/test/config files; elevated to mid risk (HITL required)"
    if risk == "low":
        return "Safe local verification command"
    if risk == "mid":
        return "Potentially unsafe/non-standard command; requires HITL approval"
    return "High-risk command pattern detected; requires explicit HITL approval"
