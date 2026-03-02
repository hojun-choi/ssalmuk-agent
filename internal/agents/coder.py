from __future__ import annotations

from typing import Any

from internal.schemas.state import ImprovementProposal, ReviewIssue


def build_coder_input(
    task: str,
    previous_issues: list[ReviewIssue],
    previous_proposals: list[ImprovementProposal] | None = None,
) -> dict[str, Any]:
    return {
        "task": task,
        "issues": [issue_to_dict(issue) for issue in previous_issues],
        "improvement_proposals": [proposal_to_dict(item) for item in (previous_proposals or [])],
    }


def revise_verify_commands(initial_commands: list[str], previous_issues: list[ReviewIssue]) -> list[str]:
    commands = list(initial_commands)
    if not previous_issues:
        return commands

    filtered: list[str] = []
    blocked_cmds: set[str] = set()
    for issue in previous_issues:
        if issue.code in {"mid_or_high_verify_command", "verify_command_failed"}:
            cmd = issue.meta.get("cmd", "")
            if cmd:
                blocked_cmds.add(cmd)

    for cmd in commands:
        if cmd not in blocked_cmds:
            filtered.append(cmd)

    if not filtered:
        filtered = ["python -m compileall ."]

    if "python -m compileall ." not in filtered:
        filtered.insert(0, "python -m compileall .")

    return filtered


def issue_to_dict(issue: ReviewIssue) -> dict[str, Any]:
    return {
        "severity": issue.severity,
        "file": issue.file,
        "location": issue.location,
        "description": issue.description,
        "suggested_fix": issue.suggested_fix,
        "code": issue.code,
        "meta": issue.meta,
    }


def proposal_to_dict(proposal: ImprovementProposal) -> dict[str, Any]:
    return {
        "title": proposal.title,
        "description": proposal.description,
        "motivation": proposal.motivation,
        "suggested_steps": list(proposal.suggested_steps),
        "affected_files": list(proposal.affected_files),
        "expected_benefit": proposal.expected_benefit,
        "risk_level": proposal.risk_level,
    }
