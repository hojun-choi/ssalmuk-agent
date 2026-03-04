from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path
from typing import Any

CRITICAL_FILE_PATTERNS = [
    "pyproject.toml",
    "requirements*.txt",
    "poetry.lock",
    "uv.lock",
    "Pipfile",
    "Pipfile.*",
    ".python-version",
    "runtime.txt",
    "go.mod",
    "go.sum",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "Dockerfile*",
    "docker-compose*.yml",
    "Makefile",
    ".github/workflows/*.yml",
    ".tool-versions",
]


def apply_unified_diff(repo: Path, diff_text: str) -> tuple[bool, str, list[dict[str, Any]]]:
    attempts: list[list[str]] = [
        ["git", "apply", "--3way", "--recount", "--whitespace=nowarn", "-"],
        ["git", "apply", "--recount", "--ignore-space-change", "--whitespace=nowarn", "-"],
        ["git", "apply", "--recount", "--ignore-whitespace", "--whitespace=nowarn", "-"],
    ]
    logs: list[dict[str, Any]] = []
    for cmd in attempts:
        proc = subprocess.run(
            cmd,
            input=diff_text.encode("utf-8", errors="replace"),
            text=False,
            cwd=repo,
            capture_output=True,
        )
        stderr_raw = proc.stderr or b""
        stdout_raw = proc.stdout or b""
        stderr = stderr_raw.decode("utf-8", errors="replace").strip()
        stdout = stdout_raw.decode("utf-8", errors="replace").strip()
        logs.append(
            {
                "cmd": " ".join(cmd),
                "ok": proc.returncode == 0,
                "stderr_tail": stderr[-400:],
                "stdout_tail": stdout[-400:],
            }
        )
        if proc.returncode == 0:
            return True, "ok", logs
    last = logs[-1] if logs else {}
    return False, str(last.get("stderr_tail") or last.get("stdout_tail") or "git apply failed"), logs


def write_files_with_preserved_eol(repo: Path, final_file_contents: dict[str, str]) -> tuple[bool, str]:
    try:
        for rel_path, content in final_file_contents.items():
            path = repo / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
            eol = _detect_existing_eol(path)
            normalized = _normalize_eol(content, eol)
            path.write_text(normalized, encoding="utf-8")
    except Exception as exc:
        return False, str(exc)
    return True, "ok"


def _detect_existing_eol(path: Path) -> str:
    if not path.exists():
        return "\n"
    data = path.read_bytes()
    if b"\r\n" in data:
        return "\r\n"
    return "\n"


def _normalize_eol(content: str, eol: str) -> str:
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\n", eol)


def extract_touched_files(diff_text: str) -> list[str]:
    touched: list[str] = []
    seen: set[str] = set()
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                path = _normalize_diff_path(parts[3])
                if path and path not in seen:
                    seen.add(path)
                    touched.append(path)
        elif line.startswith("+++ "):
            part = line[4:].strip()
            if part != "/dev/null":
                path = _normalize_diff_path(part)
                if path and path not in seen:
                    seen.add(path)
                    touched.append(path)
    return touched


def summarize_diff(diff_text: str) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    current_file: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            current_file = _normalize_diff_path(parts[3]) if len(parts) >= 4 else None
            if current_file and current_file not in summary:
                summary[current_file] = {"added": 0, "removed": 0}
            continue
        if not current_file:
            continue
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("+"):
            summary[current_file]["added"] += 1
        elif line.startswith("-"):
            summary[current_file]["removed"] += 1
    return summary


def get_critical_touched_files(
    touched_files: list[str],
    allow_critical: bool = False,
    allow_critical_all: bool = False,
    allow_critical_patterns: list[str] | None = None,
) -> list[str]:
    if allow_critical or allow_critical_all:
        return []

    allowed_patterns = allow_critical_patterns or []
    blocked: list[str] = []
    for path in touched_files:
        if not is_critical_file(path):
            continue
        if any(fnmatch.fnmatch(path, p) for p in allowed_patterns):
            continue
        blocked.append(path)
    return blocked


def is_critical_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in CRITICAL_FILE_PATTERNS)


def _normalize_diff_path(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    if normalized.startswith("a/") or normalized.startswith("b/"):
        normalized = normalized[2:]
    return normalized


def get_git_diff(repo: Path) -> str:
    proc = subprocess.run(
        ["git", "diff"],
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=repo,
        capture_output=True,
    )
    if proc.returncode != 0:
        return ""
    worktree = proc.stdout or ""
    proc_cached = subprocess.run(
        ["git", "diff", "--cached"],
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=repo,
        capture_output=True,
    )
    cached = proc_cached.stdout or "" if proc_cached.returncode == 0 else ""
    if worktree and cached:
        return worktree + "\n" + cached
    return worktree or cached


def get_git_status(repo: Path) -> str:
    proc = subprocess.run(
        ["git", "status", "--short"],
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=repo,
        capture_output=True,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout or ""
