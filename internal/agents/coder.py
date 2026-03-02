from __future__ import annotations

import difflib
import subprocess
from pathlib import Path
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


def generate_coder_output(repo: Path, coder_input: dict[str, Any], iter_idx: int) -> dict[str, Any]:
    task = str(coder_input.get("task", "")).strip()
    target_rel = _select_target_file(repo=repo, task=task)
    target_path = repo / target_rel
    old_text = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
    new_text = _build_updated_text(old_text=old_text, task=task, iter_idx=iter_idx)
    diff_text = _build_unified_diff(old_text=old_text, new_text=new_text, rel_path=target_rel)
    touched = [target_rel] if diff_text.strip() else []
    rationale = {target_rel: "Update run artifact notes for the requested task."} if touched else {}
    return {
        "diff": diff_text,
        "touched_files": touched,
        "rationale_by_file": rationale,
    }


def validate_coder_output(output: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(output, dict):
        return False, "coder output must be an object"
    required = ("diff", "touched_files", "rationale_by_file")
    for key in required:
        if key not in output:
            return False, f"coder output missing required field: {key}"

    diff = output.get("diff")
    if not isinstance(diff, str) or not diff.strip():
        return False, "coder output diff must be a non-empty unified diff string"

    touched_files = output.get("touched_files")
    if not isinstance(touched_files, list) or not touched_files:
        return False, "coder output touched_files must be a non-empty list"
    if not all(isinstance(item, str) and item.strip() for item in touched_files):
        return False, "coder output touched_files must only contain non-empty paths"

    rationale = output.get("rationale_by_file")
    if not isinstance(rationale, dict):
        return False, "coder output rationale_by_file must be an object"
    for path in touched_files:
        if path not in rationale or not str(rationale.get(path, "")).strip():
            return False, f"coder output rationale_by_file missing entry for: {path}"
    return True, "ok"


def _select_target_file(repo: Path, task: str) -> str:
    tracked = _git_tracked_files(repo)
    preferred = ["README.md", "README_ko.md"]
    for rel in preferred:
        if rel in tracked:
            return rel
    for rel in tracked:
        if rel.lower().endswith(".md"):
            return rel
    for rel in tracked:
        return rel
    for rel in preferred:
        if (repo / rel).exists():
            return rel
    if "readme" in task.lower():
        return "README.md"
    return "README.md"


def _build_updated_text(old_text: str, task: str, iter_idx: int) -> str:
    line = f"- iter {iter_idx}: {task or 'task update'}"
    if not old_text:
        return "# Project Notes\n\n## Agent Updates\n" + line + "\n"
    out = old_text
    if not out.endswith("\n"):
        out += "\n"
    if "## Agent Updates\n" not in out:
        out += "\n## Agent Updates\n"
    out += line + "\n"
    return out


def _build_unified_diff(old_text: str, new_text: str, rel_path: str) -> str:
    if old_text == new_text:
        return ""
    diff_lines = difflib.unified_diff(
        old_text.splitlines(),
        new_text.splitlines(),
        fromfile=f"a/{rel_path}",
        tofile=f"b/{rel_path}",
        lineterm="",
    )
    return "\n".join(diff_lines) + "\n"


def _git_tracked_files(repo: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files"],
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=repo,
        capture_output=True,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
