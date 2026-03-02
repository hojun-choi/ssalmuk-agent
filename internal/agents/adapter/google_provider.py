from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any

from internal.agents.adapter.provider_client import ProviderClient
from internal.agents.reviewer import review_verification
from internal.schemas.state import ImprovementProposal, ReviewIssue, ReviewResult, VerificationResult


def _extract_json_block(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        value = json.loads(stripped)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        block = match.group(1)
        try:
            value = json.loads(block)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            return None
    return None


def _supports_option(help_text: str, option_name: str) -> bool:
    return option_name in help_text


def _run_help(command: str) -> str:
    path = shutil.which(command)
    if not path:
        return ""
    try:
        proc = subprocess.run(
            [command, "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return ""
    return (proc.stdout or "") + "\n" + (proc.stderr or "")


def _build_prompt(verification: VerificationResult, role: str) -> str:
    lines = [
        "You are a software review agent.",
        f"Role: {role}",
        "Review verification results and return strict JSON only.",
        "JSON schema:",
        '{"verdict":"approve|reject","issues":[{"severity":"blocker|major|minor","file":"string","location":"string","description":"string","suggested_fix":"string","code":"string"}],"rationale":"string"}',
        "Verification entries:",
    ]
    for item in verification.executed:
        lines.append(
            f"- id={item.id} cmd={item.cmd} risk={item.risk} exit={item.exit_code} passed={item.passed}"
        )
    lines.append(f"- verification_passed={verification.passed}")
    return "\n".join(lines)


def _parse_review_from_payload(payload: dict[str, Any]) -> ReviewResult | None:
    verdict = str(payload.get("verdict", "")).strip().lower()
    if verdict not in {"approve", "reject"}:
        return None

    issues_raw = payload.get("issues", [])
    issues: list[ReviewIssue] = []
    if isinstance(issues_raw, list):
        for item in issues_raw:
            if not isinstance(item, dict):
                continue
            severity = str(item.get("severity", "minor")).strip().lower()
            if severity not in {"blocker", "major", "minor"}:
                severity = "minor"
            issues.append(
                ReviewIssue(
                    severity=severity,
                    file=str(item.get("file", "verification")),
                    location=str(item.get("location", "unknown")),
                    description=str(item.get("description", "Issue reported by google provider")),
                    suggested_fix=str(item.get("suggested_fix", "Apply the suggested review fix.")),
                    code=str(item.get("code", "google_provider_issue")),
                    meta={"source": "google_cli"},
                )
            )

    rationale = str(payload.get("rationale", "Google provider response parsed."))
    proposals_raw = payload.get("improvement_proposals", [])
    proposals: list[ImprovementProposal] = []
    if isinstance(proposals_raw, list):
        for item in proposals_raw:
            if not isinstance(item, dict):
                continue
            risk_level = str(item.get("risk_level", "low")).strip().lower()
            if risk_level not in {"low", "mid", "high"}:
                risk_level = "low"
            steps = item.get("suggested_steps", [])
            affected = item.get("affected_files", [])
            proposals.append(
                ImprovementProposal(
                    title=str(item.get("title", "Improvement proposal")),
                    description=str(item.get("description", "")),
                    motivation=str(item.get("motivation", "")),
                    suggested_steps=[str(v) for v in steps] if isinstance(steps, list) else [],
                    affected_files=[str(v) for v in affected] if isinstance(affected, list) else [],
                    expected_benefit=str(item.get("expected_benefit", "")),
                    risk_level=risk_level,
                )
            )
    hint = str(payload.get("proposal_policy_hint", "optional")).strip().lower()
    if hint not in {"optional", "recommended", "strong"}:
        hint = "optional"
    return ReviewResult(
        verdict=verdict,
        issues=issues,
        rationale=rationale,
        improvement_proposals=proposals,
        proposal_policy_hint=hint,
    )


class GoogleProviderClient(ProviderClient):
    def run_review(
        self,
        role: str,
        context: dict[str, Any],
        provider_cfg: dict[str, Any],
    ) -> tuple[ReviewResult, dict[str, Any]]:
        verification = context["verification"]
        default_review = review_verification(verification)

        command = str(provider_cfg.get("command", "gemini")).strip() or "gemini"
        command_path = shutil.which(command)
        if not command_path:
            return default_review, {
                "adapter": "google",
                "role": role,
                "provider_type": provider_cfg.get("type", "cli"),
                "model": provider_cfg.get("model", ""),
                "command": command,
                "command_available": False,
                "mode": "fallback_local_review",
                "note": "google CLI command not found. Used local review fallback.",
            }

        help_text = _run_help(command)
        supports_output_format = _supports_option(help_text, "--output-format")
        supports_prompt_long = _supports_option(help_text, "--prompt")
        supports_prompt_short = _supports_option(help_text, "-p")
        supports_model_long = _supports_option(help_text, "--model")
        supports_model_short = _supports_option(help_text, "-m")

        prompt = _build_prompt(verification=verification, role=role)
        cmd: list[str] = [command]
        model = str(provider_cfg.get("model", "")).strip()
        options = provider_cfg.get("options", {})
        ignored_options = sorted(list(options.keys())) if isinstance(options, dict) else []
        if model:
            if supports_model_long:
                cmd += ["--model", model]
            elif supports_model_short:
                cmd += ["-m", model]

        if supports_prompt_long:
            cmd += ["--prompt", prompt]
        elif supports_prompt_short:
            cmd += ["-p", prompt]
        else:
            return default_review, {
                "adapter": "google",
                "role": role,
                "provider_type": provider_cfg.get("type", "cli"),
                "model": model,
                "command": command,
                "command_available": True,
                "mode": "fallback_local_review",
                "note": "Prompt option not supported by installed gemini CLI. Used local review fallback.",
                "ignored_options": ignored_options,
            }

        selected_output_format = "text"
        if supports_output_format:
            cmd += ["--output-format", "json"]
            selected_output_format = "json"

        timeout_sec = int(provider_cfg.get("timeout_sec", 60))
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=max(1, timeout_sec),
            )
        except Exception as exc:
            return default_review, {
                "adapter": "google",
                "role": role,
                "provider_type": provider_cfg.get("type", "cli"),
                "model": model,
                "command": command,
                "command_available": True,
                "mode": "fallback_local_review",
                "note": f"google CLI execution failed: {exc}",
                "ignored_options": ignored_options,
            }

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        if proc.returncode != 0:
            return default_review, {
                "adapter": "google",
                "role": role,
                "provider_type": provider_cfg.get("type", "cli"),
                "model": model,
                "command": command,
                "command_available": True,
                "mode": "fallback_local_review",
                "exit_code": proc.returncode,
                "stderr_tail": stderr[-300:],
                "note": "google CLI returned non-zero exit code. Used local review fallback.",
                "ignored_options": ignored_options,
            }

        top_payload = _extract_json_block(stdout)
        parsed_payload: dict[str, Any] | None = None
        if top_payload:
            response_text = top_payload.get("response")
            if isinstance(response_text, str):
                parsed_payload = _extract_json_block(response_text)
            if not parsed_payload and any(k in top_payload for k in {"verdict", "issues", "rationale"}):
                parsed_payload = top_payload
        else:
            parsed_payload = _extract_json_block(stdout)

        parsed_review = _parse_review_from_payload(parsed_payload) if parsed_payload else None
        if parsed_review:
            return parsed_review, {
                "adapter": "google",
                "role": role,
                "provider_type": provider_cfg.get("type", "cli"),
                "model": model,
                "command": command,
                "command_available": True,
                "mode": "gemini_cli_json",
                "output_format": selected_output_format,
                "ignored_options": ignored_options,
                "note": "provider options are not directly applied via CLI flags; configure CLI settings separately if needed.",
            }

        return default_review, {
            "adapter": "google",
            "role": role,
            "provider_type": provider_cfg.get("type", "cli"),
            "model": model,
            "command": command,
            "command_available": True,
            "mode": "fallback_local_review",
            "output_format": selected_output_format,
            "stdout_tail": stdout[-300:],
            "note": "google CLI response could not be parsed to review JSON. Used local review fallback.",
            "ignored_options": ignored_options,
        }
