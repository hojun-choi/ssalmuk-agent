from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class NetworkFinding:
    file: str
    kind: str
    evidence: str
    line_no: int | None = None
    snippet: str | None = None


HTTP_PATTERN = re.compile(r"https?://", re.IGNORECASE)
WS_PATTERN = re.compile(r"wss?://", re.IGNORECASE)

KEYWORD_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bwebsocket\b", re.IGNORECASE), "websocket_keyword"),
    (re.compile(r"\bws\.", re.IGNORECASE), "websocket_keyword"),
    (re.compile(r"\bapi\.", re.IGNORECASE), "api_keyword"),
    (re.compile(r"/v[12]/", re.IGNORECASE), "api_keyword"),
    (re.compile(r"\bbinance\b", re.IGNORECASE), "api_keyword"),
    (re.compile(r"\bupbit\b", re.IGNORECASE), "api_keyword"),
    (re.compile(r"\bbithumb\b", re.IGNORECASE), "api_keyword"),
    (re.compile(r"\border\b", re.IGNORECASE), "api_keyword"),
    (re.compile(r"\bwithdraw\b", re.IGNORECASE), "api_keyword"),
]


def _normalize(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except Exception:
        return path.as_posix()


def _always_scan_paths(repo_root: Path) -> list[Path]:
    items: list[Path] = []
    tests_dir = repo_root / "tests"
    if tests_dir.exists():
        items.extend([p for p in tests_dir.rglob("*") if p.is_file()])

    for fixed in ["conftest.py", "pytest.ini"]:
        p = repo_root / fixed
        if p.exists() and p.is_file():
            items.append(p)

    for pattern in [".env*", "settings*.py", "config/*.yml", "config/*.yaml", "config/*.json"]:
        items.extend([p for p in repo_root.glob(pattern) if p.is_file()])
    return items


def _iter_scan_targets(repo_root: Path, touched_files: list[str], extra_paths: list[str]) -> list[Path]:
    targets: list[Path] = []
    seen: set[str] = set()

    def add_path(p: Path) -> None:
        if not p.exists():
            return
        if p.is_dir():
            for child in p.rglob("*"):
                if child.is_file():
                    key = str(child.resolve())
                    if key not in seen:
                        seen.add(key)
                        targets.append(child)
            return
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            targets.append(p)

    for rel in touched_files:
        clean = rel.strip().replace("\\", "/")
        if not clean:
            continue
        add_path(repo_root / clean)

    for rel in extra_paths:
        clean = rel.strip().replace("\\", "/")
        if not clean:
            continue
        add_path(repo_root / clean)

    for p in _always_scan_paths(repo_root):
        add_path(p)

    return targets


def _scan_file(path: Path, repo_root: Path) -> list[NetworkFinding]:
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    findings: list[NetworkFinding] = []
    for idx, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        if HTTP_PATTERN.search(line):
            findings.append(
                NetworkFinding(
                    file=_normalize(path, repo_root),
                    kind="http_url",
                    evidence="http(s)://",
                    line_no=idx,
                    snippet=line[:200],
                )
            )
        if WS_PATTERN.search(line):
            findings.append(
                NetworkFinding(
                    file=_normalize(path, repo_root),
                    kind="ws_url",
                    evidence="ws(s)://",
                    line_no=idx,
                    snippet=line[:200],
                )
            )
        for pattern, kind in KEYWORD_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            findings.append(
                NetworkFinding(
                    file=_normalize(path, repo_root),
                    kind=kind,
                    evidence=match.group(0),
                    line_no=idx,
                    snippet=line[:200],
                )
            )
    return findings


def detect_network_indicators(
    repo_root: Path,
    touched_files: list[str] | None = None,
    extra_paths: list[str] | None = None,
) -> list[NetworkFinding]:
    touched = touched_files or []
    extra = extra_paths or []
    if not repo_root.exists():
        return []

    findings: list[NetworkFinding] = []
    seen: set[tuple[str, str, str, int | None]] = set()
    for target in _iter_scan_targets(repo_root, touched, extra):
        for finding in _scan_file(target, repo_root):
            key = (finding.file, finding.kind, finding.evidence, finding.line_no)
            if key in seen:
                continue
            seen.add(key)
            findings.append(finding)
            if len(findings) >= 200:
                return findings
    return findings
