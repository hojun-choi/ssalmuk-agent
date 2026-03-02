from __future__ import annotations

import subprocess
import time
from pathlib import Path

from internal.schemas.state import VerificationItem, VerificationResult


HIGH_RISK_KEYWORDS = {
    "withdraw",
    "transfer",
    "send",
    "loan",
    "borrow",
    "repay",
    "order",
    "market_buy",
    "market_sell",
    "limit_buy",
    "limit_sell",
}

LOW_RISK_PREFIXES = (
    "python -m compileall",
    "pytest",
    "python -m my_opt_code_agent --help",
    "git status",
    "git diff",
)


def classify_risk(cmd: str) -> str:
    lowered = cmd.lower()
    if any(k in lowered for k in HIGH_RISK_KEYWORDS):
        return "high"
    if lowered.startswith(LOW_RISK_PREFIXES):
        return "low"
    return "mid"


def _tail(text: str, max_chars: int = 400) -> str:
    return text[-max_chars:]


def run_verification_commands(
    repo: Path,
    commands: list[str],
    timeout_sec: int = 120,
    constraints: dict | None = None,
) -> VerificationResult:
    items: list[VerificationItem] = []
    constraints = constraints or {}
    forbidden_actions = [a.lower() for a in constraints.get("forbidden_actions", [])]
    qps = max(0.0, float(constraints.get("global_qps", 1) or 0))

    for idx, cmd in enumerate(commands, start=1):
        risk = classify_risk(cmd)

        lowered = cmd.lower()
        if any(a and a in lowered for a in forbidden_actions):
            item = VerificationItem(
                id=f"verify-{idx}",
                cmd=cmd,
                risk=risk,
                exit_code=3,
                stdout_tail="",
                stderr_tail="blocked by forbidden_actions constraint",
                passed=False,
            )
            items.append(item)
            return VerificationResult(executed=items, passed=False)

        proc = subprocess.run(
            cmd,
            cwd=repo,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        item = VerificationItem(
            id=f"verify-{idx}",
            cmd=cmd,
            risk=risk,
            exit_code=proc.returncode,
            stdout_tail=_tail(proc.stdout),
            stderr_tail=_tail(proc.stderr),
            passed=proc.returncode == 0,
        )
        items.append(item)
        if proc.returncode != 0:
            return VerificationResult(executed=items, passed=False)

        if qps > 0:
            time.sleep(1.0 / qps)

    return VerificationResult(executed=items, passed=True)
