from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from internal.agents.adapter import AgentAdapter, load_provider_registry
from internal.agents.adapter.registry import apply_provider_overrides
from internal.agents.coder import build_coder_input, revise_verify_commands
from internal.schemas.state import (
    AlertEvent,
    AgentState,
    ImprovementProposal,
    PolicyGateState,
    ProviderRun,
    ReviewBundleConfig,
    ReviewIssue,
    ReviewResult,
    ReviewsState,
    TaskSpec,
    UserConstraints,
    VerificationResult,
    to_plain_dict,
)
from internal.tools.artifacts import ArtifactPaths, build_artifact_paths, mask_sensitive, report_header_lines
from internal.tools.patch import (
    apply_unified_diff,
    extract_touched_files,
    get_critical_touched_files,
    get_git_diff,
    summarize_diff,
)
from internal.tools.policy_gate import apply_policy_gate
from internal.tools.risk_scan import detect_network_indicators
from internal.tools.runner import run_verification_commands
from internal.tools.test_plan import build_test_plan
from internal.tools.tracing import TraceWriter

KST = timezone(timedelta(hours=9))
ALERT_STOP_TYPES = {"quota", "rate_limit", "timeout"}
PROPOSAL_POLICY_HINTS = {"optional", "recommended", "strong"}
DEFAULT_PROVIDER_CONFIG_REL = "configs/local/providers.yaml"
EXAMPLE_PROVIDER_CONFIG_REL = "configs/examples/providers_example.yaml"


class StopRunError(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="my_opt_code_agent", description="Phase-based delivery agent")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Run Phase 3 flow (TestPlan + PolicyGate + Consensus Review)")
    run.add_argument("--repo", required=True, help="Repository path")
    run.add_argument("--task", required=True, help="Task instruction")
    run.add_argument("--diff-file", help="Optional unified diff file to apply")
    run.add_argument(
        "--verify-cmd",
        action="append",
        default=[],
        help="Verification command (repeatable).",
    )
    run.add_argument("--max-iters", type=int, default=5, help="Max coder-reviewer reject loop iterations")
    run.add_argument(
        "--accept-proposals",
        choices=["never", "strong", "all"],
        default="strong",
        help="Policy for applying reviewer improvement proposals (default: strong).",
    )
    stop_group = run.add_mutually_exclusive_group()
    stop_group.add_argument(
        "--stop-on-alert",
        dest="stop_on_alert",
        action="store_true",
        help="Stop the run immediately when auth/quota/rate-limit/provider-unavailable alerts occur (default).",
    )
    stop_group.add_argument(
        "--no-stop-on-alert",
        dest="stop_on_alert",
        action="store_false",
        help="Allow non-strict fallback to continue after alert events.",
    )
    run.set_defaults(stop_on_alert=True)

    run.add_argument("--hitl", action="store_true", help="Enable HITL policy gate decision path")
    run.add_argument(
        "--approve-mid-high",
        action="store_true",
        help="When used with --hitl, skip interactive prompt and treat mid/high as approve-all.",
    )
    run.add_argument("--deny-mid-high", action="store_true", help="Deny mid/high test items")
    run.add_argument("--global-qps", type=float, default=1.0, help="Global command rate limit")
    run.add_argument(
        "--forbidden-action",
        action="append",
        default=[],
        help="Forbidden action keyword (repeatable)",
    )

    run.add_argument(
        "--review-providers",
        default="codex",
        help="Comma-separated review providers list (default: codex)",
    )
    run.add_argument(
        "--provider-config",
        default=DEFAULT_PROVIDER_CONFIG_REL,
        help=f"Provider config path (default: {DEFAULT_PROVIDER_CONFIG_REL})",
    )
    run.add_argument(
        "--set-provider",
        action="append",
        default=[],
        help="Provider override, e.g. codex.model=gpt-5.3-codex",
    )
    run.add_argument(
        "--strict-review-providers",
        action="store_true",
        help="Fail if any requested review provider is unavailable (missing env/CLI/adapter).",
    )

    run.add_argument(
        "--allow-critical",
        action="store_true",
        help="Allow critical change files in this run (explicit approval).",
    )
    run.add_argument(
        "--allow-critical-files",
        default="",
        help="Comma-separated glob list to allow specific critical files.",
    )
    run.add_argument(
        "--allow-critical-all",
        action="store_true",
        help="Allow all critical files in this run.",
    )

    sub.add_parser("doctor", help="Check Python venv and pip wiring")
    return parser


def _default_verify_commands() -> list[str]:
    return ["python -m compileall ."]


def _parse_allow_patterns(raw: str) -> list[str]:
    if not raw.strip():
        return []
    return [part.strip().replace("\\", "/") for part in raw.split(",") if part.strip()]


def _parse_csv(raw: str) -> list[str]:
    values = [part.strip() for part in raw.split(",") if part.strip()]
    return values or ["codex"]


def _now_kst_iso() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _short_message(text: str, limit: int = 180) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "..."


def _detect_alert_type_from_text(text: str) -> str | None:
    lowered = (text or "").lower()
    if not lowered:
        return None
    if "login required" in lowered or "login is required" in lowered or "unauthorized" in lowered or "auth required" in lowered:
        return "auth"
    if "429" in lowered or "rate limit" in lowered or "too many requests" in lowered:
        return "rate_limit"
    if "insufficient_quota" in lowered or "quota exceeded" in lowered or "resource_exhausted" in lowered:
        return "quota"
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    if "auth" in lowered or "login" in lowered or "api key" in lowered or "credentials" in lowered:
        return "auth"
    if "not found" in lowered or "unavailable" in lowered or "unsupported" in lowered:
        return "provider_unavailable"
    return None


def _emit_alert_console(alert: AlertEvent) -> None:
    role_part = f" role={alert.role}" if alert.role else ""
    print(f'ALERT: {alert.type} provider={alert.provider}{role_part} message="{_short_message(alert.message)}"')


def _append_alert(
    alerts: list[AlertEvent],
    trace: TraceWriter | None,
    *,
    alert_type: str,
    provider: str,
    role: str | None,
    message: str,
    severity: str = "warn",
) -> AlertEvent:
    alert = AlertEvent(
        type=alert_type,
        provider=provider,
        role=role,
        message=_short_message(message, 300),
        ts=_now_kst_iso(),
        severity=severity,
    )
    alerts.append(alert)
    _emit_alert_console(alert)
    if trace:
        trace.event(
            "alert",
            type=alert.type,
            provider=alert.provider,
            role=alert.role,
            severity=alert.severity,
            message=alert.message,
        )
    return alert


def _collect_provider_alerts(provider: str, role: str, raw: dict[str, Any] | None) -> list[tuple[str, str, str]]:
    if not raw:
        return []
    texts: list[str] = []
    for key in ["note", "error", "message", "stderr_tail", "stdout_tail"]:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            texts.append(value.strip())
    mode = str(raw.get("mode", "")).strip().lower()
    if mode == "fallback_local_review":
        joined = " | ".join(texts) if texts else "provider runtime fallback triggered"
        alert_type = _detect_alert_type_from_text(joined) or "provider_unavailable"
        return [(alert_type, _short_message(joined, 260), "warn")]

    joined = " | ".join(texts)
    alert_type = _detect_alert_type_from_text(joined)
    if not alert_type:
        return []
    severity = "error" if alert_type in ALERT_STOP_TYPES.union({"auth", "provider_unavailable"}) else "warn"
    return [(alert_type, _short_message(joined, 260), severity)]


def _proposal_signature(proposal: ImprovementProposal) -> str:
    steps = "|".join(proposal.suggested_steps)
    files = "|".join(proposal.affected_files)
    return f"{proposal.title}|{proposal.description}|{proposal.risk_level}|{steps}|{files}"


def _dedup_proposals(proposals: list[ImprovementProposal]) -> list[ImprovementProposal]:
    out: list[ImprovementProposal] = []
    seen: set[str] = set()
    for proposal in proposals:
        sig = _proposal_signature(proposal)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(proposal)
    return out


def _select_proposals_for_rework(
    proposals: list[ImprovementProposal],
    policy_hint: str,
    accept_policy: str,
) -> tuple[list[ImprovementProposal], list[ImprovementProposal], str]:
    if accept_policy == "never":
        return [], list(proposals), "accept_proposals=never"
    if accept_policy == "all":
        return list(proposals), [], "accept_proposals=all"
    hint = policy_hint if policy_hint in PROPOSAL_POLICY_HINTS else "optional"
    if hint == "strong":
        selected = [item for item in proposals if item.risk_level in {"low", "mid", "high"}]
        return selected, [], "accept_proposals=strong+hint=strong"
    return [], list(proposals), "accept_proposals=strong+hint_not_strong"


def _is_truthy_env(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _format_critical_section(blocked_files: list[str], diff_summary: dict[str, dict[str, int]]) -> list[str]:
    lines = [
        "## Critical Changes (Approval Required)",
        "- change_risk: high",
        "- default_policy: deny_without_explicit_approval",
        "- reason: dependency/version/install/ci-build critical files were touched",
        "- impact_scope:",
    ]
    for path in blocked_files:
        item = diff_summary.get(path, {"added": 0, "removed": 0})
        lines.append(f"  - {path} (+{item['added']}/-{item['removed']})")
    lines += [
        "- rollback_method:",
        "  - Revert patch or restore previous lock/config files from version control.",
    ]
    return lines


def _build_empty_verification() -> VerificationResult:
    return VerificationResult(executed=[], passed=False)


def _build_empty_review() -> ReviewResult:
    return ReviewResult(verdict="reject", issues=[], rationale="No review executed.")


def _finding_to_dict(finding: Any) -> dict[str, Any]:
    return {
        "file": str(getattr(finding, "file", "")),
        "kind": str(getattr(finding, "kind", "")),
        "evidence": str(getattr(finding, "evidence", "")),
        "line_no": getattr(finding, "line_no", None),
        "snippet": str(getattr(finding, "snippet", "")),
    }


def _provider_config_copy_hint() -> str:
    return f"cp {EXAMPLE_PROVIDER_CONFIG_REL} {DEFAULT_PROVIDER_CONFIG_REL}"


def _resolve_provider_config_path(raw_path: str) -> tuple[Path | None, list[str]]:
    messages: list[str] = []
    requested = Path(raw_path).resolve()
    if requested.exists():
        return requested, messages

    default_requested = raw_path.replace("\\", "/") == DEFAULT_PROVIDER_CONFIG_REL
    example_path = Path(EXAMPLE_PROVIDER_CONFIG_REL).resolve()
    if default_requested:
        messages.append(f"provider config is missing: {requested}")
        messages.append(f"create local config from example: {_provider_config_copy_hint()}")
        if example_path.exists():
            messages.append(f"temporary fallback: using example provider config ({EXAMPLE_PROVIDER_CONFIG_REL})")
            return example_path, messages
    return None, messages


def _print_hitl_help() -> None:
    print("HITL commands:")
    print("- deny <ID...>")
    print("- approve <ID...>")
    print("- approve-all")
    print("- deny-all")
    print("- fallback-only")
    print("- set global_qps=<n>")
    print("- add forbidden_action=<kw>")
    print("- show")
    print("- help")
    print("- continue")
    print("- abort")


def _print_hitl_plan(test_plan: list[Any], title: str = "HITL TestPlan") -> None:
    print(f"== {title} ==")
    for idx, item in enumerate(test_plan, start=1):
        fallback = item.fallback if item.fallback else "-"
        print(
            f"{idx}. {item.id} | risk={item.risk} | cmd={item.cmd} | reason={item.reason} | fallback={fallback}"
        )
    print("Type commands, then `continue` (or `abort`).")


def _parse_ids(parts: list[str], test_plan: list[Any]) -> list[str]:
    known = {item.id for item in test_plan}
    picked = [part.strip() for part in parts if part.strip()]
    valid = [item for item in picked if item in known]
    invalid = [item for item in picked if item not in known]
    if invalid:
        print(f"[WARN] unknown test IDs: {', '.join(invalid)}")
    return valid


def _interactive_hitl_session(
    *,
    test_plan: list[Any],
    constraints: UserConstraints,
    input_fn: Callable[[str], str] = input,
    trace: TraceWriter | None = None,
) -> str:
    if not constraints.mode:
        constraints.mode = "fallback_only"
    _print_hitl_plan(test_plan)
    _print_hitl_help()
    if trace:
        trace.event("hitl_prompt_shown", item_count=len(test_plan), mode=constraints.mode)

    while True:
        if input_fn is input:
            try:
                raw = (input_fn("hitl> ") or "").strip()
            except EOFError:
                print("[WARN] HITL input stream closed. Aborting.")
                return "abort"
        else:
            print("hitl> ", end="")
            raw = (input_fn("hitl> ") or "").strip()
        if trace:
            trace.event("hitl_command_received", command=raw)
        if not raw:
            print("[WARN] empty command. Type `help`.")
            continue
        constraints.hitl_input_history.append(raw)
        lowered = raw.lower()

        if lowered == "help":
            _print_hitl_help()
            continue
        if lowered == "show":
            _print_hitl_plan(test_plan, title="HITL Current Plan")
            print(
                f"Current: mode={constraints.mode} approved={constraints.approved_ids} denied={constraints.denied_ids} "
                f"global_qps={constraints.rate_limit.get('global_qps', 1)} forbidden_actions={constraints.forbidden_actions}"
            )
            continue
        if lowered == "approve-all":
            constraints.approved_ids = ["*"]
            constraints.denied_ids = [item for item in constraints.denied_ids if item not in {"all", "*"}]
            constraints.mode = "normal"
            print("[OK] approve-all applied")
            continue
        if lowered == "deny-all":
            constraints.denied_ids = ["all"]
            constraints.approved_ids = []
            print("[OK] deny-all applied")
            continue
        if lowered == "fallback-only":
            constraints.mode = "fallback_only"
            print("[OK] fallback-only mode enabled")
            continue
        if lowered == "continue":
            constraints.hitl_confirmed = True
            if trace:
                trace.event(
                    "hitl_decision_finalized",
                    mode=constraints.mode,
                    approved_ids=constraints.approved_ids,
                    denied_ids=constraints.denied_ids,
                    global_qps=constraints.rate_limit.get("global_qps", 1),
                    forbidden_actions=constraints.forbidden_actions,
                )
            return "continue"
        if lowered == "abort":
            if trace:
                trace.event("hitl_decision_finalized", action="abort")
            return "abort"

        parts = raw.split()
        cmd = parts[0].lower()
        if cmd == "approve":
            ids = _parse_ids(parts[1:], test_plan)
            if not ids:
                print("[WARN] no valid IDs provided for approve")
                continue
            for item in ids:
                if item not in constraints.approved_ids:
                    constraints.approved_ids.append(item)
            constraints.denied_ids = [item for item in constraints.denied_ids if item not in ids and item != "all"]
            constraints.mode = "normal"
            print(f"[OK] approved: {', '.join(ids)}")
            continue
        if cmd == "deny":
            ids = _parse_ids(parts[1:], test_plan)
            if not ids:
                print("[WARN] no valid IDs provided for deny")
                continue
            for item in ids:
                if item not in constraints.denied_ids:
                    constraints.denied_ids.append(item)
            constraints.approved_ids = [item for item in constraints.approved_ids if item not in ids and item != "*"]
            print(f"[OK] denied: {', '.join(ids)}")
            continue
        if cmd == "set":
            if len(parts) < 2 or "=" not in parts[1]:
                print("[WARN] invalid set syntax. Example: set global_qps=1")
                continue
            key, value = parts[1].split("=", 1)
            key = key.strip().lower()
            value = value.strip()
            if key != "global_qps":
                print("[WARN] supported set key: global_qps")
                continue
            try:
                qps = float(value)
                if qps <= 0:
                    raise ValueError("qps must be > 0")
            except Exception:
                print("[WARN] invalid global_qps value")
                continue
            constraints.rate_limit["global_qps"] = qps
            print(f"[OK] global_qps={qps}")
            continue
        if cmd == "add":
            if len(parts) < 2 or "=" not in parts[1]:
                print("[WARN] invalid add syntax. Example: add forbidden_action=withdraw")
                continue
            key, value = parts[1].split("=", 1)
            key = key.strip().lower()
            value = value.strip()
            if key != "forbidden_action" or not value:
                print("[WARN] supported add key: forbidden_action=<kw>")
                continue
            lowered_kw = value.lower()
            if lowered_kw not in constraints.forbidden_actions:
                constraints.forbidden_actions.append(lowered_kw)
            print(f"[OK] forbidden_action added: {lowered_kw}")
            continue

        print("[WARN] unknown command. Type `help`.")


def _write_state_json(path: Path, state: AgentState) -> None:
    plain = to_plain_dict(state)
    masked = mask_sensitive(plain)
    path.write_text(json.dumps(masked, ensure_ascii=False, indent=2), encoding="utf-8")


def _latest_provider_runs(provider_runs: list[ProviderRun], iter_idx: int) -> list[ProviderRun]:
    result: list[ProviderRun] = []
    for run in provider_runs:
        raw = run.raw or {}
        if raw.get("iter") == iter_idx:
            result.append(run)
    return result


def _write_run_report(
    path: Path,
    artifacts: ArtifactPaths,
    state: AgentState,
    verification: VerificationResult,
    review: ReviewResult,
    final_diff_text: str,
    critical_section_lines: list[str] | None = None,
    runtime_error: str | None = None,
) -> None:
    lines = report_header_lines(artifacts, state.task.user_request)
    lines += [
        "## Summary",
        f"- task: {state.task.user_request}",
        f"- repo: {state.repo_root}",
        f"- patch_applied: {state.patch_applied}",
        f"- iterations: {state.iter}/{state.max_iters}",
        f"- review_providers: {', '.join(state.review_bundle.providers)}",
        f"- policy_gate_status: {state.policy_gate.status}",
        f"- final_verdict: {review.verdict}",
        f"- verification_passed: {verification.passed}",
        f"- run_status: {state.status}",
    ]
    if runtime_error:
        lines.append(f"- runtime_error: {runtime_error}")
    if state.stopped_reason:
        lines.append(f"- stopped_reason: {state.stopped_reason}")

    lines += ["", "## Alerts"]
    if state.alerts:
        for alert in state.alerts:
            role_text = f" role={alert.role}" if alert.role else ""
            lines.append(
                f"- {alert.type} provider={alert.provider}{role_text} severity={alert.severity} message={_short_message(alert.message, 180)}"
            )
        if any(a.type in {"quota", "rate_limit"} for a in state.alerts):
            lines.append("- guide: retry later, lower request frequency (global_qps), switch provider, and verify key/plan quota.")
        if any(a.type == "timeout" for a in state.alerts):
            lines.append("- guide: simplify prompt/workload, retry, or tune provider timeout/command complexity.")
        if state.status == "stopped":
            lines.append(f"- Run stopped due to alert: {state.stopped_reason or 'alert policy stop'}")
    else:
        lines.append("- None")
    lines += ["", "## Network Indicators Detected"]
    if state.network_findings:
        for item in state.network_findings[:20]:
            file_path = item.get("file", "")
            kind = item.get("kind", "")
            evidence = _short_message(str(item.get("evidence", "")), 80)
            line_no = item.get("line_no")
            loc = f":{line_no}" if isinstance(line_no, int) and line_no > 0 else ""
            lines.append(f"- {file_path}{loc} kind={kind} evidence={evidence}")
        if len(state.network_findings) > 20:
            lines.append(f"- ... and {len(state.network_findings) - 20} more finding(s)")
        lines.append("- note: low-risk verification commands were elevated to mid risk when indicators were detected.")
    else:
        lines.append("- None")
    if critical_section_lines:
        lines += ["", *critical_section_lines]

    lines += ["", "## TestPlan"]
    for item in state.test_plan:
        fallback = f" | fallback={item.fallback}" if item.fallback else ""
        lines.append(f"- {item.id}: `{item.cmd}` | risk={item.risk} | reason={item.reason}{fallback}")

    lines += ["", "## PolicyGate"]
    lines.append(f"- status: {state.policy_gate.status}")
    lines.append(f"- need_human: {state.policy_gate.need_human}")
    if state.policy_gate.blocked_items:
        lines.append(f"- blocked_items: {', '.join(state.policy_gate.blocked_items)}")
    if state.policy_gate.message:
        lines.append(f"- message: {state.policy_gate.message}")

    lines += ["", "## HITL"]
    hitl_enabled = bool(state.user_constraints.hitl_input_history) or state.policy_gate.need_human
    lines.append(f"- enabled: {hitl_enabled}")
    lines.append(f"- mode: {state.user_constraints.mode}")
    lines.append(f"- confirmed: {state.user_constraints.hitl_confirmed}")
    lines.append(f"- approved_ids: {state.user_constraints.approved_ids}")
    lines.append(f"- denied_ids: {state.user_constraints.denied_ids}")
    lines.append(f"- global_qps: {state.user_constraints.rate_limit.get('global_qps', 1)}")
    lines.append(f"- forbidden_actions: {state.user_constraints.forbidden_actions}")
    if state.user_constraints.hitl_input_history:
        lines.append("- input_history:")
        for cmd in state.user_constraints.hitl_input_history:
            lines.append(f"  - {cmd}")
    else:
        lines.append("- input_history: []")

    lines += ["", "## Changes (File-by-file)"]
    diff_summary = summarize_diff(final_diff_text)
    if diff_summary:
        for file_path, stats in diff_summary.items():
            lines.append(f"- {file_path}: +{stats['added']} / -{stats['removed']}")
    else:
        lines.append("- No working-tree diff changes detected.")

    lines += ["", "## Requirement Trace"]
    lines += [
        f"- TestPlan risk classification: {'PASS' if bool(state.test_plan) else 'FAIL'}",
        f"- PolicyGate execution: {'PASS' if state.policy_gate.status in {'allowed', 'blocked'} else 'FAIL'}",
        f"- Reviewer bundle/provider_runs recorded: {'PASS' if bool(state.reviews.provider_runs) or review.verdict == 'reject' else 'FAIL'}",
        f"- Critical gate policy linkage: {'PASS' if (critical_section_lines is None or bool(critical_section_lines)) else 'FAIL'}",
        f"- Artifact output contract (RUN_DIR/REPORT/DIFF/STATE): PASS",
    ]

    lines += ["", "## Verification"]
    for message in state.provider_messages:
        lines.append(f"- provider_setup: {message}")
    for item in verification.executed:
        lines.append(f"- `{item.cmd}` | risk={item.risk} | exit={item.exit_code} | passed={item.passed}")

    lines += ["", "## Review Notes"]
    latest_runs = _latest_provider_runs(state.reviews.provider_runs, state.iter)
    for message in state.provider_messages:
        if "fallback" in message or "missing" in message or "not found" in message:
            lines.append(f"- provider_note: {message}")
    for run in latest_runs:
        mode = ""
        if run.raw and run.raw.get("mode"):
            mode = f" mode={run.raw.get('mode')}"
        lines.append(
            f"- provider={run.provider} role={run.role} verdict={run.verdict} issues={len(run.issues)}{mode}"
        )
    lines.append(f"- aggregation_conclusion: {state.reviews.aggregation_conclusion}")

    lines += ["", "## Review (Aggregated Consensus)"]
    lines.append(f"- verdict: {review.verdict}")
    for issue in review.issues:
        lines.append(
            f"- issue[{issue.code}] {issue.severity} {issue.file}:{issue.location} - {issue.description}"
        )

    lines += ["", "## Improvement Proposals"]
    if state.proposal_decisions:
        for item in state.proposal_decisions:
            lines.append(
                f"- title={item.get('title','')} action={item.get('action','')} reason={item.get('reason','')}"
            )
    else:
        lines.append("- None")

    lines += ["", "## Tracing", f"- `{artifacts.trace_rel}` contains run-level trace events (jsonl)."]
    lines += ["", "## State Artifact", f"- `{artifacts.state_rel}` contains test_plan, policy_gate, and provider_runs."]
    lines += ["", "## Final Diff", f"See `{artifacts.diff_rel}`."]
    lines += ["", "## PR-ready"]
    lines.append(f"- verdict: {review.verdict}")
    lines.append("- next_action: open PR only when review verdict is approve and verification passed.")
    path.write_text("\n".join(lines), encoding="utf-8")


def _handle_critical_gate(
    diff_text: str,
    allow_critical: bool,
    allow_critical_all: bool,
    allow_critical_files_raw: str,
) -> tuple[bool, list[str] | None]:
    touched_files = extract_touched_files(diff_text)
    diff_summary = summarize_diff(diff_text)
    allow_patterns = _parse_allow_patterns(allow_critical_files_raw)
    blocked = get_critical_touched_files(
        touched_files=touched_files,
        allow_critical=allow_critical,
        allow_critical_all=allow_critical_all,
        allow_critical_patterns=allow_patterns,
    )
    if not blocked:
        return True, None

    critical_section_lines = _format_critical_section(blocked, diff_summary)
    print("CRITICAL CHANGE APPROVAL REQUIRED")
    print("change_risk=high")
    print("blocked_files:")
    for path in blocked:
        item = diff_summary.get(path, {"added": 0, "removed": 0})
        print(f"- {path} (+{item['added']}/-{item['removed']})")
    print("why_needed: dependency/version/install/ci-build file changes detected")
    print("impact_scope: environment/build/runtime behavior can change")
    print("rollback: revert the patch or restore previous file versions")
    return False, critical_section_lines


def _provider_setup_checks(
    provider: str,
    provider_cfg: dict[str, Any],
    adapter: AgentAdapter,
) -> tuple[bool, list[str]]:
    messages: list[str] = []
    if not adapter.supports(provider):
        messages.append(f"{provider}: unsupported provider")
        messages.append(f"{provider}: fix by removing from --review-providers or adding adapter implementation")
        return False, messages

    if provider == "codex":
        auth_mode = str(provider_cfg.get("auth_mode", "chatgpt_login")).strip() or "chatgpt_login"
        command = str(provider_cfg.get("command", "codex")).strip() or "codex"
        if auth_mode == "chatgpt_login":
            command_path = shutil.which(command)
            if not command_path:
                messages.append(f"codex: CLI command not found: {command}")
                messages.append("codex: fix by installing Codex CLI and running `codex login`")
                return False, messages
            messages.append(f"codex: ready auth_mode=chatgpt_login (command={command})")
            messages.append("codex: note login session may expire; run `codex login` if runtime auth fails")
            return True, messages
        if auth_mode == "api_key":
            key = os.environ.get("OPENAI_API_KEY", "").strip()
            if not key:
                messages.append("codex: OPENAI_API_KEY is missing (auth_mode=api_key)")
                messages.append("codex: fix by setting OPENAI_API_KEY in current shell")
                return False, messages
            return True, ["codex: ready auth_mode=api_key"]
        messages.append(f"codex: unsupported auth_mode={auth_mode}")
        messages.append("codex: supported auth_mode values are chatgpt_login, api_key")
        return False, messages

    if provider == "google":
        auth_mode = str(provider_cfg.get("auth_mode", "ai_studio_key")).strip() or "ai_studio_key"
        gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
        google_key = os.environ.get("GOOGLE_API_KEY", "").strip()
        command = str(provider_cfg.get("command", "gemini")).strip() or "gemini"
        command_path = shutil.which(command)
        if not command_path:
            messages.append(f"google: CLI command not found: {command}")
            messages.append(f"google: fix by installing CLI and verifying `{command} --help`")
            return False, messages

        if auth_mode == "ai_studio_key":
            if gemini_key or google_key:
                return True, [f"google: ready auth_mode=ai_studio_key (command={command})"]
            messages.append("google: GEMINI_API_KEY or GOOGLE_API_KEY is missing (auth_mode=ai_studio_key)")
            messages.append("google: fix by setting GEMINI_API_KEY (or GOOGLE_API_KEY)")
            return False, messages

        if auth_mode == "google_login":
            messages.append(f"google: ready auth_mode=google_login (command={command})")
            messages.append("google: note non-interactive mode requires prior `gemini` Login with Google in this environment")
            messages.append("google: if runtime fails, run `gemini` interactively to refresh login then retry")
            return True, messages

        if auth_mode == "vertex_api_key":
            vertex_flag = _is_truthy_env(os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", ""))
            project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
            location = os.environ.get("GOOGLE_CLOUD_LOCATION", "").strip()
            if google_key and vertex_flag and project and location:
                return True, [f"google: ready auth_mode=vertex_api_key (command={command})"]
            messages.append(
                "google: vertex_api_key requires GOOGLE_API_KEY, GOOGLE_GENAI_USE_VERTEXAI=true, GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION"
            )
            return False, messages

        if auth_mode == "vertex_adc":
            vertex_flag = _is_truthy_env(os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", ""))
            project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
            location = os.environ.get("GOOGLE_CLOUD_LOCATION", "").strip()
            creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
            has_gcloud = bool(shutil.which("gcloud"))
            if vertex_flag and project and location and (creds or has_gcloud):
                msg = [f"google: ready auth_mode=vertex_adc (command={command})"]
                if gemini_key or google_key:
                    msg.append("google: note unset API key vars when using vertex_adc to avoid auth precedence conflicts")
                return True, msg
            messages.append(
                "google: vertex_adc requires GOOGLE_GENAI_USE_VERTEXAI=true, GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION, and ADC credentials"
            )
            messages.append(
                "google: provide GOOGLE_APPLICATION_CREDENTIALS or run `gcloud auth application-default login`"
            )
            return False, messages

        messages.append(f"google: unsupported auth_mode={auth_mode}")
        messages.append(
            "google: supported auth_mode values are ai_studio_key, google_login, vertex_api_key, vertex_adc"
        )
        return False, messages

    if provider == "local":
        return True, ["local: ready"]

    return True, [f"{provider}: ready"]


def _resolve_review_providers_with_runtime_checks(
    requested: list[str],
    strict: bool,
    stop_on_alert: bool,
    adapter: AgentAdapter,
    provider_registry: dict[str, Any],
    alerts: list[AlertEvent],
    trace: TraceWriter | None,
) -> tuple[list[str], list[str]]:
    effective: list[str] = []
    messages: list[str] = []
    unavailable: dict[str, list[str]] = {}

    for provider in requested:
        cfg = provider_registry.get(provider, {})
        ok, check_messages = _provider_setup_checks(provider, cfg, adapter)
        messages.extend(check_messages)
        if ok:
            effective.append(provider)
        else:
            unavailable[provider] = check_messages
            message = "; ".join(check_messages)
            _append_alert(
                alerts,
                trace,
                alert_type="provider_unavailable",
                provider=provider,
                role=None,
                message=message,
                severity="error",
            )

    if not unavailable:
        return effective, messages

    if stop_on_alert:
        failed = ", ".join(unavailable.keys())
        raise StopRunError(f"provider setup unavailable: [{failed}]")

    if strict:
        print("strict review provider mode enabled -> aborting")
        for provider, items in unavailable.items():
            print(f"- {provider}: unavailable")
            for item in items:
                print(f"  - {item}")
        raise RuntimeError("strict mode provider setup check failed")

    requested_set = set(requested)
    if effective:
        dropped = ", ".join(unavailable.keys())
        kept = ", ".join(effective)
        print(f"non-strict provider fallback: dropped [{dropped}] -> using [{kept}]")
        messages.append(f"fallback_applied: dropped [{dropped}] -> using [{kept}]")
        return effective, messages

    requested_list = ", ".join(requested)
    print(f"provider setup failed in non-strict mode: requested [{requested_list}]")
    if requested_set == {"google"}:
        print("google-only request cannot fallback. configure GEMINI_API_KEY and gemini CLI, or include codex.")
    raise RuntimeError("no runnable providers after setup checks")


def _issue_signature(issue: ReviewIssue) -> str:
    return f"{issue.severity}|{issue.file}|{issue.location}|{issue.code}|{issue.description}"


def _aggregate_consensus(provider_runs: list[ProviderRun], review_bundle: ReviewBundleConfig) -> tuple[ReviewResult, str]:
    rules = review_bundle.aggregation.rules
    reject_runs = [run for run in provider_runs if run.verdict == "reject"]

    all_issues: list[ReviewIssue] = []
    seen: set[str] = set()
    for run in reject_runs:
        for issue in run.issues:
            sig = _issue_signature(issue)
            if sig in seen:
                continue
            seen.add(sig)
            all_issues.append(issue)

    has_blocker = any(issue.severity == "blocker" for issue in all_issues)
    has_major = any(issue.severity == "major" for issue in all_issues)
    has_minor = any(issue.severity == "minor" for issue in all_issues)
    all_proposals = _dedup_proposals(
        [proposal for run in provider_runs for proposal in getattr(run, "improvement_proposals", [])]
    )
    hint_priority = {"optional": 0, "recommended": 1, "strong": 2}
    hint = "optional"
    for run in provider_runs:
        value = run.proposal_policy_hint if run.proposal_policy_hint in hint_priority else "optional"
        if hint_priority[value] > hint_priority[hint]:
            hint = value

    if not reject_runs:
        return (
            ReviewResult(
                verdict="approve",
                issues=[],
                rationale="All provider role runs approved.",
                improvement_proposals=all_proposals,
                proposal_policy_hint=hint,
            ),
            "policy=consensus; decision=approve; reason=all_runs_approve",
        )

    if has_blocker and rules.if_any_blocker_reject:
        return (
            ReviewResult(
                verdict="reject",
                issues=all_issues,
                rationale="Consensus rejected by blocker issue.",
                improvement_proposals=all_proposals,
                proposal_policy_hint=hint,
            ),
            "policy=consensus; decision=reject; reason=blocker_issue",
        )

    if has_major and rules.if_any_major_reject:
        return (
            ReviewResult(
                verdict="reject",
                issues=all_issues,
                rationale="Consensus rejected by major issue.",
                improvement_proposals=all_proposals,
                proposal_policy_hint=hint,
            ),
            "policy=consensus; decision=reject; reason=major_issue",
        )

    if has_minor and not has_blocker and not has_major and rules.allow_minor_only:
        return (
            ReviewResult(
                verdict="approve",
                issues=[],
                rationale="Minor-only issues allowed by policy.",
                improvement_proposals=all_proposals,
                proposal_policy_hint=hint,
            ),
            "policy=consensus; decision=approve; reason=minor_only_allowed",
        )

    return (
        ReviewResult(
            verdict="reject",
            issues=all_issues,
            rationale="Consensus rejected by provider run verdicts.",
            improvement_proposals=all_proposals,
            proposal_policy_hint=hint,
        ),
        "policy=consensus; decision=reject; reason=reject_runs_present",
    )


def _run_review_bundle(
    adapter: AgentAdapter,
    providers: list[str],
    roles: list[str],
    review_bundle: ReviewBundleConfig,
    provider_registry: dict[str, dict],
    verification: VerificationResult,
    iter_idx: int,
    strict: bool,
    stop_on_alert: bool,
    provider_messages: list[str],
    alerts: list[AlertEvent],
    trace: TraceWriter | None,
) -> tuple[list[ProviderRun], ReviewResult, str]:
    provider_runs: list[ProviderRun] = []
    context = {"verification": verification}
    dropped_providers: set[str] = set()

    for provider in providers:
        if provider in dropped_providers:
            continue
        cfg = provider_registry.get(provider, {})
        for role in roles:
            result, raw = adapter.run_review(provider=provider, role=role, context=context, provider_cfg=cfg)
            run_raw = dict(raw or {})
            run_raw["iter"] = iter_idx
            warning_text = str(run_raw.get("warning", "")).strip()
            if warning_text:
                provider_messages.append(f"warning: {provider}/{role} {warning_text}")
            detected = _collect_provider_alerts(provider=provider, role=role, raw=run_raw)
            blocking_alert: AlertEvent | None = None
            for alert_type, alert_message, severity in detected:
                alert = _append_alert(
                    alerts,
                    trace,
                    alert_type=alert_type,
                    provider=provider,
                    role=role,
                    message=alert_message,
                    severity=severity,
                )
                if alert.type in ALERT_STOP_TYPES and blocking_alert is None:
                    blocking_alert = alert
                if alert.type in {"auth", "provider_unavailable"} and blocking_alert is None:
                    blocking_alert = alert

            if blocking_alert:
                if stop_on_alert:
                    raise StopRunError(
                        f"stop_on_alert triggered: {provider}/{role} {blocking_alert.type} - {blocking_alert.message}"
                    )
                if strict:
                    raise RuntimeError(
                        "provider runtime alert in strict mode: "
                        f"{provider}/{role} {blocking_alert.type} - {blocking_alert.message}"
                    )
                if len(providers) <= 1:
                    raise RuntimeError(
                        "provider runtime alert and no fallback providers: "
                        f"{provider}/{role} {blocking_alert.type} - {blocking_alert.message}"
                    )
                provider_messages.append(
                    f"fallback_runtime: dropped {provider} due {blocking_alert.type} ({blocking_alert.message})"
                )
                dropped_providers.add(provider)
                break

            if provider == "google" and run_raw.get("mode") == "fallback_local_review":
                reason = str(run_raw.get("note", "google provider runtime fallback triggered"))
                if strict:
                    raise RuntimeError(
                        "google provider runtime failure in strict mode: "
                        f"{reason}. Fix: run `gemini` and complete Login with Google, then retry."
                    )
                if len(providers) <= 1:
                    raise RuntimeError(
                        "google provider runtime failure and no fallback providers: "
                        f"{reason}. Fix: complete `gemini` login or include codex/local providers."
                    )
                provider_messages.append(f"fallback_runtime: dropped google due runtime failure ({reason})")
                dropped_providers.add(provider)
                break
            provider_runs.append(
                ProviderRun(
                    provider=provider,
                    role=role,
                    verdict=result.verdict,
                    issues=result.issues,
                    rationale=result.rationale,
                    improvement_proposals=result.improvement_proposals,
                    proposal_policy_hint=result.proposal_policy_hint,
                    raw=run_raw,
                )
            )

    review, conclusion = _aggregate_consensus(provider_runs=provider_runs, review_bundle=review_bundle)
    return provider_runs, review, conclusion


def run_phase3(args: argparse.Namespace, input_fn: Callable[[str], str] = input) -> int:
    repo = Path(args.repo).resolve()
    artifacts = build_artifact_paths(repo, args.task)
    trace = TraceWriter(artifacts.trace_path)
    trace.event("run_started", repo=str(repo), task=args.task)

    state = AgentState(
        task=TaskSpec(user_request=args.task),
        repo_root=str(repo),
        status="running",
        stopped_reason="",
        max_iters=max(1, args.max_iters),
        review_bundle=ReviewBundleConfig(providers=["codex"], roles=["reviewer_a", "reviewer_b"]),
        reviews=ReviewsState(provider_runs=[]),
        user_constraints=UserConstraints(
            approvals=[],
            rate_limit={"global_qps": max(0.0, args.global_qps)},
            forbidden_actions=[a.strip() for a in args.forbidden_action if a.strip()],
        ),
        policy_gate=PolicyGateState(status="not_checked", need_human=False, blocked_items=[], message=""),
    )

    final_verification = _build_empty_verification()
    final_review = _build_empty_review()
    critical_section_lines: list[str] | None = None
    runtime_error: str | None = None
    exit_code = 1
    touched_files_for_scan: list[str] = []

    try:
        adapter = AgentAdapter()
        provider_cfg_path, provider_cfg_messages = _resolve_provider_config_path(args.provider_config)
        for line in provider_cfg_messages:
            print(f"[WARN] {line}")
        if provider_cfg_path is None:
            raise RuntimeError(
                "provider config not found. Create a local file from example and retry: "
                + _provider_config_copy_hint()
            )
        provider_registry = load_provider_registry(provider_cfg_path)
        provider_registry = apply_provider_overrides(provider_registry, args.set_provider)
        trace.event("provider_registry_loaded", path=str(provider_cfg_path))

        requested_providers = _parse_csv(args.review_providers)
        effective_providers, provider_messages = _resolve_review_providers_with_runtime_checks(
            requested=requested_providers,
            strict=args.strict_review_providers,
            stop_on_alert=args.stop_on_alert,
            adapter=adapter,
            provider_registry=provider_registry,
            alerts=state.alerts,
            trace=trace,
        )
        trace.event(
            "review_providers_resolved",
            requested=requested_providers,
            effective=effective_providers,
            strict=args.strict_review_providers,
        )
        state.provider_messages = provider_messages

        state.review_bundle = ReviewBundleConfig(providers=effective_providers, roles=["reviewer_a", "reviewer_b"])

        should_continue = True
        if args.diff_file:
            diff_path = Path(args.diff_file).resolve()
            diff_text = diff_path.read_text(encoding="utf-8")
            touched_files_for_scan = extract_touched_files(diff_text)
            trace.event("diff_loaded", path=str(diff_path), bytes=len(diff_text))

            allowed, critical_section_lines = _handle_critical_gate(
                diff_text=diff_text,
                allow_critical=args.allow_critical,
                allow_critical_all=args.allow_critical_all,
                allow_critical_files_raw=args.allow_critical_files,
            )
            if not allowed:
                trace.event("critical_gate_blocked")
                should_continue = False
                final_review = ReviewResult(
                    verdict="reject",
                    issues=[],
                    rationale="Critical change gate blocked patch apply.",
                )
                state.reviews.aggregation_conclusion = "policy=critical_gate; decision=reject; reason=blocked"
            else:
                ok, message = apply_unified_diff(repo, diff_text)
                state.patch_applied = ok
                trace.event("patch_apply", ok=ok, message=message)
                if not ok:
                    should_continue = False
                    runtime_error = f"patch apply failed: {message}"
                    print(runtime_error)
                    final_review = ReviewResult(verdict="reject", issues=[], rationale=runtime_error)
                    state.reviews.aggregation_conclusion = "policy=apply_patch; decision=reject; reason=patch_apply_failed"

        if should_continue:
            base_verify_cmds = args.verify_cmd or _default_verify_commands()
            current_verify_cmds = list(base_verify_cmds)
            if args.hitl and args.approve_mid_high:
                state.user_constraints.hitl_confirmed = True
                state.user_constraints.mode = "normal"
                state.user_constraints.approved_ids = ["*"]
            if not touched_files_for_scan:
                try:
                    touched_files_for_scan = extract_touched_files(get_git_diff(repo))
                except Exception:
                    touched_files_for_scan = []

            for iter_idx in range(1, state.max_iters + 1):
                state.iter = iter_idx
                coder_input = build_coder_input(
                    state.task.user_request,
                    state.latest_issues,
                    state.latest_proposals,
                )
                state.coder_inputs.append(coder_input)
                trace.event(
                    "iter_started",
                    iter=iter_idx,
                    latest_issue_count=len(state.latest_issues),
                    latest_proposal_count=len(state.latest_proposals),
                )

                current_verify_cmds = revise_verify_commands(current_verify_cmds, state.latest_issues)
                network_findings = detect_network_indicators(
                    repo_root=repo,
                    touched_files=touched_files_for_scan,
                    extra_paths=[],
                )
                state.network_findings = [_finding_to_dict(item) for item in network_findings]
                trace.event(
                    "risk_scan",
                    iter=iter_idx,
                    findings_count=len(network_findings),
                    top_findings=[
                        {
                            "file": item.file,
                            "kind": item.kind,
                            "evidence": _short_message(item.evidence, 40),
                        }
                        for item in network_findings[:5]
                    ],
                )
                if network_findings:
                    summary = ", ".join(
                        [f"{item.file}:{item.kind}" for item in network_findings[:3]]
                    )
                    _append_alert(
                        state.alerts,
                        trace,
                        alert_type="risk_network_indicator",
                        provider="policy_gate",
                        role=None,
                        message=f"Network indicator detected; verify risk elevated to mid/high. {summary}",
                        severity="warn",
                    )

                state.test_plan = build_test_plan(
                    current_verify_cmds,
                    network_indicator_detected=bool(network_findings),
                )
                trace.event("test_plan_built", iter=iter_idx, item_count=len(state.test_plan))

                policy_state, gated_commands = apply_policy_gate(
                    test_plan=state.test_plan,
                    hitl=args.hitl,
                    approve_mid_high=args.approve_mid_high,
                    deny_mid_high=args.deny_mid_high,
                    user_constraints=state.user_constraints,
                )
                if (
                    args.hitl
                    and policy_state.status == "blocked"
                    and bool(policy_state.blocked_items)
                    and not args.approve_mid_high
                ):
                    decision = _interactive_hitl_session(
                        test_plan=state.test_plan,
                        constraints=state.user_constraints,
                        input_fn=input_fn,
                        trace=trace,
                    )
                    if decision == "abort":
                        _append_alert(
                            state.alerts,
                            trace,
                            alert_type="hitl_abort",
                            provider="policy_gate",
                            role=None,
                            message="HITL abort requested by user",
                            severity="warn",
                        )
                        raise StopRunError("HITL aborted by user")
                    policy_state, gated_commands = apply_policy_gate(
                        test_plan=state.test_plan,
                        hitl=True,
                        approve_mid_high=False,
                        deny_mid_high=False,
                        user_constraints=state.user_constraints,
                    )
                state.policy_gate = policy_state
                trace.event(
                    "policy_gate_evaluated",
                    iter=iter_idx,
                    status=policy_state.status,
                    blocked_items=policy_state.blocked_items,
                )

                if policy_state.status != "allowed":
                    final_review = ReviewResult(
                        verdict="reject",
                        issues=[],
                        rationale=policy_state.message,
                    )
                    state.reviews.aggregation_conclusion = "policy=policy_gate; decision=reject; reason=blocked"
                    print(f"loop_iter={iter_idx} reviewer_verdict=reject")
                    trace.event("iter_finished", iter=iter_idx, verdict="reject", reason="policy_gate_blocked")
                    break

                try:
                    final_verification = run_verification_commands(
                        repo=repo,
                        commands=gated_commands,
                        constraints={
                            "global_qps": state.user_constraints.rate_limit.get("global_qps", 1),
                            "forbidden_actions": state.user_constraints.forbidden_actions,
                        },
                    )
                except Exception as exc:
                    alert_type = _detect_alert_type_from_text(str(exc)) or "timeout"
                    _append_alert(
                        state.alerts,
                        trace,
                        alert_type=alert_type,
                        provider="verification",
                        role=None,
                        message=f"verification command execution failed: {exc}",
                        severity="error",
                    )
                    raise
                state.verification_history.append(final_verification)
                trace.event(
                    "verification_finished",
                    iter=iter_idx,
                    passed=final_verification.passed,
                    executed=len(final_verification.executed),
                )

                provider_runs, final_review, conclusion = _run_review_bundle(
                    adapter=adapter,
                    providers=state.review_bundle.providers,
                    roles=state.review_bundle.roles,
                    review_bundle=state.review_bundle,
                    provider_registry=provider_registry,
                    verification=final_verification,
                    iter_idx=iter_idx,
                    strict=args.strict_review_providers,
                    stop_on_alert=args.stop_on_alert,
                    provider_messages=state.provider_messages,
                    alerts=state.alerts,
                    trace=trace,
                )
                state.reviews.provider_runs.extend(provider_runs)
                state.reviews.aggregation_conclusion = conclusion
                trace.event(
                    "review_bundle_finished",
                    iter=iter_idx,
                    provider_runs=len(provider_runs),
                    verdict=final_review.verdict,
                    aggregation=conclusion,
                )

                state.review_history.append(final_review)
                state.latest_issues = final_review.issues
                dedup_proposals = _dedup_proposals(final_review.improvement_proposals)
                state.latest_proposals = []
                if dedup_proposals:
                    trace.event(
                        "proposal_detected",
                        iter=iter_idx,
                        count=len(dedup_proposals),
                        policy_hint=final_review.proposal_policy_hint,
                        accept_policy=args.accept_proposals,
                    )
                selected_proposals, skipped_proposals, decision_reason = _select_proposals_for_rework(
                    proposals=dedup_proposals,
                    policy_hint=final_review.proposal_policy_hint,
                    accept_policy=args.accept_proposals,
                )
                for proposal in selected_proposals:
                    state.proposal_decisions.append(
                        {"title": proposal.title, "action": "applied", "reason": decision_reason}
                    )
                for proposal in skipped_proposals:
                    state.proposal_decisions.append(
                        {"title": proposal.title, "action": "not_applied", "reason": decision_reason}
                    )

                print(f"loop_iter={iter_idx} reviewer_verdict={final_review.verdict}")
                if final_review.verdict == "approve":
                    if selected_proposals and iter_idx < state.max_iters:
                        state.latest_proposals = selected_proposals
                        trace.event(
                            "proposal_applied",
                            iter=iter_idx,
                            count=len(selected_proposals),
                            reason=decision_reason,
                        )
                        trace.event("iter_finished", iter=iter_idx, verdict="revise", reason="strong_proposal")
                        continue
                    trace.event("iter_finished", iter=iter_idx, verdict="approve")
                    break
                trace.event("iter_finished", iter=iter_idx, verdict="reject")

        if state.status != "stopped":
            state.status = "completed" if final_review.verdict == "approve" else "failed"
        exit_code = 0 if final_review.verdict == "approve" and state.status != "stopped" else 1

    except StopRunError as exc:
        runtime_error = str(exc)
        state.status = "stopped"
        state.stopped_reason = runtime_error
        print(f"STOPPED: {runtime_error}")
        trace.event("stopped", reason=runtime_error)
        final_review = ReviewResult(verdict="reject", issues=[], rationale=f"stopped: {runtime_error}")
        if not state.reviews.aggregation_conclusion:
            state.reviews.aggregation_conclusion = "policy=alert; decision=stopped; reason=stop_on_alert"
        exit_code = 1

    except Exception as exc:
        runtime_error = str(exc)
        print(f"runtime_error: {runtime_error}")
        trace.event("runtime_error", message=runtime_error)
        detected = _detect_alert_type_from_text(runtime_error)
        if detected:
            _append_alert(
                state.alerts,
                trace,
                alert_type=detected,
                provider="runtime",
                role=None,
                message=runtime_error,
                severity="error",
            )
        final_review = ReviewResult(verdict="reject", issues=[], rationale=f"runtime_error: {runtime_error}")
        if not state.reviews.aggregation_conclusion:
            state.reviews.aggregation_conclusion = "policy=runtime; decision=reject; reason=exception"
        if state.status != "stopped":
            state.status = "failed"
        exit_code = 1

    finally:
        final_diff = get_git_diff(repo)
        artifacts.diff_path.write_text(final_diff, encoding="utf-8")
        _write_state_json(artifacts.state_path, state)
        trace.event(
            "run_finalized",
            review_verdict=final_review.verdict,
            verification_passed=final_verification.passed,
            exit_code=exit_code,
            run_dir=artifacts.run_dir_rel,
        )
        _write_run_report(
            artifacts.report_path,
            artifacts,
            state,
            final_verification,
            final_review,
            final_diff_text=final_diff,
            critical_section_lines=critical_section_lines,
            runtime_error=runtime_error,
        )

        print(f"verification_passed={final_verification.passed}")
        print(f"review_verdict={final_review.verdict}")
        print(f"RUN_DIR: {artifacts.run_dir_rel}")
        print(f"REPORT: {artifacts.report_rel}")
        print(f"DIFF: {artifacts.diff_rel}")
        print(f"STATE: {artifacts.state_rel}")
        print(f"TRACE: {artifacts.trace_rel}")

    return exit_code


def run_doctor() -> int:
    min_major, min_minor = 3, 10
    py_ok = sys.version_info >= (min_major, min_minor)
    virtual_env = os.environ.get("VIRTUAL_ENV", "")
    is_active = bool(virtual_env) or getattr(sys, "prefix", "") != getattr(sys, "base_prefix", "")
    pip_path = shutil.which("pip") or ""
    pip_normalized = pip_path.replace("\\", "/")
    venv_normalized = virtual_env.replace("\\", "/") if virtual_env else ""
    pip_matches_venv = bool(venv_normalized) and pip_normalized.startswith(venv_normalized)
    pip_points_dotvenv = "/.venv/" in pip_normalized

    print("ssalmuk-agent doctor")
    print(f"Python: {sys.version.split()[0]}")

    print("")
    print("[Check] Python version")
    if py_ok:
        print(f"[OK] Python version is supported (>= {min_major}.{min_minor})")
    else:
        print(f"[FAIL] Python version is too low. Required: >= {min_major}.{min_minor}")
        print("  Fix: install newer Python, recreate .venv, then reinstall with `pip install -e .`")

    print("")
    print("[Check] Python venv")
    if is_active and (pip_matches_venv or pip_points_dotvenv):
        print("[OK] venv is active and pip points to .venv")
    else:
        print("[WARN] venv is not active or pip is outside .venv")
        print("  Fix: activate .venv and reinstall editable package")
        print("  Windows: py -m venv .venv && .\\.venv\\Scripts\\Activate.ps1")
        print("  macOS/Linux: python3 -m venv .venv && source .venv/bin/activate")

    print("")
    print("[Check] Provider config")
    registry: dict[str, Any] = {}
    cfg_path, cfg_messages = _resolve_provider_config_path(DEFAULT_PROVIDER_CONFIG_REL)
    if cfg_messages:
        for line in cfg_messages:
            print(f"[WARN] {line}")
    if cfg_path is None:
        print(f"[FAIL] providers config load failed: {Path(DEFAULT_PROVIDER_CONFIG_REL).resolve()}")
        print(f"  Fix: {_provider_config_copy_hint()}")
    else:
        try:
            registry = load_provider_registry(cfg_path)
            print(f"[OK] providers config loaded: {cfg_path}")
        except Exception as exc:
            print(f"[FAIL] providers config load failed: {cfg_path}")
            print(f"  Reason: {exc}")
            print("  Fix: validate JSON-compatible YAML syntax in your provider config")

    print("")
    print("[Check] Local config examples")
    local_example_pairs = [
        ("configs/examples/providers_example.yaml", "configs/local/providers.yaml"),
        ("configs/examples/risk_keywords_example.yaml", "configs/local/risk_keywords.yaml"),
        ("configs/examples/local_settings_example.yaml", "configs/local/local_settings.yaml"),
        (".env.example", ".env"),
    ]
    for example_rel, local_rel in local_example_pairs:
        example_path = Path(example_rel)
        local_path = Path(local_rel)
        if not example_path.exists():
            continue
        if local_path.exists():
            print(f"[OK] local file exists: {local_path}")
        else:
            print(f"[WARN] local file missing: {local_path}")
            print(f"  Fix: copy from example -> {example_rel}")

    print("")
    print("[Check] codex provider")
    codex_cfg = registry.get("codex", {}) if isinstance(registry, dict) else {}
    codex_auth_mode = str(codex_cfg.get("auth_mode", "chatgpt_login")).strip() or "chatgpt_login"
    codex_command = str(codex_cfg.get("command", "codex")).strip() or "codex"
    print(f"- configured auth_mode: {codex_auth_mode}")
    if codex_auth_mode == "chatgpt_login":
        codex_path = shutil.which(codex_command)
        if codex_path:
            print(f"[OK] codex CLI command found: {codex_command} -> {codex_path}")
        else:
            print(f"[FAIL] codex CLI command not found: {codex_command}")
            print(f"  Fix: install Codex CLI and verify with `{codex_command} --help`")
        print("[WARN] chatgpt_login session cannot be fully validated non-interactively")
        print("  Fix: run `codex login` in this shell/environment, then retry run command")
    elif codex_auth_mode == "api_key":
        codex_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if codex_key:
            print("[OK] OPENAI_API_KEY is set")
        else:
            print("[FAIL] OPENAI_API_KEY is missing")
            print("  Fix: set OPENAI_API_KEY in current shell before running codex provider")
    else:
        print(f"[FAIL] unsupported codex auth_mode in providers.yaml: {codex_auth_mode}")
        print("  Fix: use chatgpt_login or api_key")

    print("")
    print("[Check] google provider")
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    google_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    vertex_flag = _is_truthy_env(os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", ""))
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "").strip()
    creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    google_cfg = registry.get("google", {}) if isinstance(registry, dict) else {}
    auth_mode = str(google_cfg.get("auth_mode", "ai_studio_key")).strip() or "ai_studio_key"
    gemini_cmd = str(google_cfg.get("command", "gemini")).strip() or "gemini"
    gemini_path = shutil.which(gemini_cmd)
    print(f"- configured auth_mode: {auth_mode}")

    if gemini_path:
        print(f"[OK] google CLI command found: {gemini_cmd} -> {gemini_path}")
    else:
        print(f"[FAIL] google CLI command not found: {gemini_cmd}")
        print(f"  Fix: install Gemini CLI and verify with `{gemini_cmd} --help`")

    if auth_mode == "ai_studio_key":
        if gemini_key or google_key:
            which_key = "GEMINI_API_KEY" if gemini_key else "GOOGLE_API_KEY"
            print(f"[OK] google key auth ready via {which_key}")
        else:
            print("[FAIL] GEMINI_API_KEY/GOOGLE_API_KEY is missing")
            print("  Fix: set GEMINI_API_KEY (or GOOGLE_API_KEY)")
    elif auth_mode == "google_login":
        print("[WARN] google_login cannot be fully validated non-interactively")
        print("  Fix: 1) verify install: `gemini --help`")
        print("  Fix: 2) run `gemini` and complete Login with Google")
        print("  Fix: 3) retry your `my_opt_code_agent run` command")
    elif auth_mode == "vertex_api_key":
        if google_key and vertex_flag and project and location:
            print("[OK] vertex_api_key env is complete")
        else:
            print("[FAIL] vertex_api_key env is incomplete")
            print("  Fix: set GOOGLE_API_KEY, GOOGLE_GENAI_USE_VERTEXAI=true, GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION")
    elif auth_mode == "vertex_adc":
        has_adc = bool(creds) or bool(shutil.which("gcloud"))
        if vertex_flag and project and location and has_adc:
            print("[OK] vertex_adc baseline env is present")
            if gemini_key or google_key:
                print("[WARN] API key vars are set; unset them when testing vertex_adc to avoid auth precedence conflicts")
        else:
            print("[FAIL] vertex_adc env is incomplete")
            print("  Fix: set GOOGLE_GENAI_USE_VERTEXAI=true, GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION")
            print("  Fix: provide GOOGLE_APPLICATION_CREDENTIALS or run `gcloud auth application-default login`")
    else:
        print(f"[FAIL] unsupported auth_mode in providers.yaml: {auth_mode}")
        print("  Fix: use ai_studio_key | google_login | vertex_api_key | vertex_adc")

    print("")
    print("[Policy] Provider fallback summary")
    print("- stop-on-alert default: enabled (auth/quota/rate-limit/provider_unavailable -> immediate stop)")
    print("- non-strict: unavailable provider is dropped if another requested provider is runnable")
    print("- strict: fail fast if any requested provider is unavailable")
    print("- google-only: non-strict still fails when google setup is unavailable")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        return run_phase3(args)
    if args.command == "doctor":
        return run_doctor()

    parser.print_help()
    return 0

