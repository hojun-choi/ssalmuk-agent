from __future__ import annotations

from internal.schemas.state import PolicyGateState, TestPlanItem, UserConstraints


def apply_policy_gate(
    test_plan: list[TestPlanItem],
    hitl: bool,
    approve_mid_high: bool,
    deny_mid_high: bool,
    user_constraints: UserConstraints,
) -> tuple[PolicyGateState, list[str]]:
    blocked_ids: list[str] = []
    rewritten_commands: list[str] = []

    if approve_mid_high and deny_mid_high:
        return (
            PolicyGateState(
                status="blocked",
                need_human=False,
                blocked_items=[],
                message="Invalid policy flags: both approve and deny were specified.",
            ),
            [],
        )

    approved_ids = set(user_constraints.approved_ids or [])
    denied_ids = set(user_constraints.denied_ids or [])
    fallback_only_mode = (user_constraints.mode or "fallback_only") == "fallback_only"
    approve_all = "*" in approved_ids
    hitl_confirmed = bool(getattr(user_constraints, "hitl_confirmed", False))

    for item in test_plan:
        if item.risk == "low":
            rewritten_commands.append(item.cmd)
            continue

        is_denied = item.id in denied_ids or "all" in denied_ids
        if is_denied:
            blocked_ids.append(item.id)
            continue

        if not hitl:
            blocked_ids.append(item.id)
            continue
        if deny_mid_high:
            blocked_ids.append(item.id)
            continue
        if approve_mid_high:
            rewritten_commands.append(item.cmd)
            continue
        if not hitl_confirmed:
            blocked_ids.append(item.id)
            continue

        if fallback_only_mode:
            if item.fallback:
                rewritten_commands.append(item.fallback)
            else:
                blocked_ids.append(item.id)
            continue

        if approve_all or item.id in approved_ids:
            rewritten_commands.append(item.cmd)
            continue

        blocked_ids.append(item.id)

    if blocked_ids and not (hitl and approve_mid_high and not deny_mid_high):
        if hitl:
            maybe_denied_only = all((bid in denied_ids or "all" in denied_ids) for bid in blocked_ids)
            if maybe_denied_only:
                return (
                    PolicyGateState(
                        status="allowed",
                        need_human=False,
                        blocked_items=blocked_ids,
                        message="PolicyGate: denied items were skipped by HITL constraints.",
                    ),
                    rewritten_commands,
                )
        return (
            PolicyGateState(
                status="blocked",
                need_human=True,
                blocked_items=blocked_ids,
                message="PolicyGate blocked mid/high risk test items. Use HITL approvals/denials/fallback mode and continue.",
            ),
            [],
        )

    forbidden_actions = [a.lower() for a in user_constraints.forbidden_actions]
    for cmd in rewritten_commands:
        lowered = cmd.lower()
        if any(action and action in lowered for action in forbidden_actions):
            return (
                PolicyGateState(
                    status="blocked",
                    need_human=True,
                    blocked_items=blocked_ids,
                    message="PolicyGate blocked by user forbidden_actions constraint.",
                ),
                [],
            )

    return (
        PolicyGateState(
            status="allowed",
            need_human=False,
            blocked_items=blocked_ids,
            message="PolicyGate passed.",
        ),
        rewritten_commands,
    )
