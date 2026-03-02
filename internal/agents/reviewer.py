from __future__ import annotations

from internal.schemas.state import ReviewIssue, ReviewResult, VerificationResult


def review_verification(verification: VerificationResult) -> ReviewResult:
    issues: list[ReviewIssue] = []
    for item in verification.executed:
        if item.risk in {"mid", "high"}:
            issues.append(
                ReviewIssue(
                    severity="blocker",
                    file="verification",
                    location=item.id,
                    description=f"Verification command risk is {item.risk}: {item.cmd}",
                    suggested_fix="Replace with low-risk local verification command.",
                    code="mid_or_high_verify_command",
                    meta={"cmd": item.cmd, "risk": item.risk},
                )
            )
        if item.exit_code != 0:
            issues.append(
                ReviewIssue(
                    severity="major",
                    file="verification",
                    location=item.id,
                    description=f"Verification command failed with exit={item.exit_code}: {item.cmd}",
                    suggested_fix="Fix failing command or replace with valid low-risk check.",
                    code="verify_command_failed",
                    meta={"cmd": item.cmd, "exit_code": item.exit_code},
                )
            )

    verdict = "approve" if verification.passed and not issues else "reject"
    rationale = "All verification checks passed." if verdict == "approve" else "Issues found by reviewer."
    return ReviewResult(verdict=verdict, issues=issues, rationale=rationale)
