from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

KST = timezone(timedelta(hours=9))
SENSITIVE_KEYS = {"api_key", "token", "secret", "password", "passwd", "key"}


@dataclass
class ArtifactPaths:
    repo_root: Path
    reports_root: Path
    display_root: Path
    repo_slug: str
    timestamp_id: str
    task_slug: str
    run_dir: Path
    report_path: Path
    diff_path: Path
    state_path: Path
    trace_path: Path
    run_dir_rel: str
    report_rel: str
    diff_rel: str
    state_rel: str
    trace_rel: str
    kst_display: str


def slugify(value: str, max_len: int = 64) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if not text:
        text = "item"
    return text[:max_len].strip("-") or "item"


def build_artifact_paths(
    repo_root: Path,
    task_text: str,
    reports_root: Path | None = None,
    display_root: Path | None = None,
) -> ArtifactPaths:
    now = datetime.now(KST)
    timestamp_id = now.strftime("%Y%m%d_%H%M%S")
    kst_display = now.strftime("%Y-%m-%d %H:%M KST")

    repo_slug = slugify(repo_root.name, max_len=50)
    task_slug = slugify(task_text, max_len=50)

    effective_reports_root = (reports_root or (repo_root / "reports")).resolve()
    effective_display_root = (display_root or repo_root).resolve()
    run_dir = effective_reports_root / repo_slug / f"{timestamp_id}__{task_slug}"
    run_dir.mkdir(parents=True, exist_ok=False)

    report_path = run_dir / "report.md"
    diff_path = run_dir / "final.diff"
    state_path = run_dir / "state.json"
    trace_path = run_dir / "trace.jsonl"

    try:
        run_dir_rel = run_dir.relative_to(effective_display_root).as_posix() + "/"
        report_rel = report_path.relative_to(effective_display_root).as_posix()
        diff_rel = diff_path.relative_to(effective_display_root).as_posix()
        state_rel = state_path.relative_to(effective_display_root).as_posix()
        trace_rel = trace_path.relative_to(effective_display_root).as_posix()
    except ValueError:
        run_dir_rel = run_dir.as_posix() + "/"
        report_rel = report_path.as_posix()
        diff_rel = diff_path.as_posix()
        state_rel = state_path.as_posix()
        trace_rel = trace_path.as_posix()

    return ArtifactPaths(
        repo_root=repo_root,
        reports_root=effective_reports_root,
        display_root=effective_display_root,
        repo_slug=repo_slug,
        timestamp_id=timestamp_id,
        task_slug=task_slug,
        run_dir=run_dir,
        report_path=report_path,
        diff_path=diff_path,
        state_path=state_path,
        trace_path=trace_path,
        run_dir_rel=run_dir_rel,
        report_rel=report_rel,
        diff_rel=diff_rel,
        state_rel=state_rel,
        trace_rel=trace_rel,
        kst_display=kst_display,
    )


def mask_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        masked: dict[str, Any] = {}
        for key, inner in value.items():
            key_lower = str(key).lower()
            if any(token in key_lower for token in SENSITIVE_KEYS):
                masked[key] = "***"
            else:
                masked[key] = mask_sensitive(inner)
        return masked
    if isinstance(value, list):
        return [mask_sensitive(v) for v in value]
    return value


def report_header_lines(paths: ArtifactPaths, task_title: str) -> list[str]:
    title = task_title.strip() or paths.task_slug
    return [
        f"# [{paths.repo_slug}] {title}  {paths.kst_display}",
        "",
        "## Artifacts",
        f"- Run folder: {paths.run_dir_rel}",
        f"- report.md: {paths.report_rel}",
        f"- final.diff: {paths.diff_rel}",
        f"- state.json: {paths.state_rel}",
        f"- trace.jsonl: {paths.trace_rel}",
        "",
    ]
