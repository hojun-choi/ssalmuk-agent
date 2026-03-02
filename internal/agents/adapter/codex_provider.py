from __future__ import annotations

import os
import shutil
from typing import Any

from internal.agents.adapter.provider_client import ProviderClient
from internal.agents.reviewer import review_verification
from internal.schemas.state import ReviewResult
from internal.tools.shell import run_cli


class CodexProviderClient(ProviderClient):
    def _real_provider_enabled(self) -> bool:
        return os.environ.get("MYOPT_ENABLE_REAL_PROVIDERS", "").strip() == "1"

    def _check_chatgpt_login(
        self, command: str, timeout_sec: int
    ) -> tuple[bool, bool, str, str, str]:
        if not self._real_provider_enabled():
            return True, False, "real provider disabled by MYOPT_ENABLE_REAL_PROVIDERS=0", "", ""
        if os.environ.get("MYOPT_MOCK_CODEX_LOGIN_REQUIRED", "").strip() == "1":
            return False, True, "Codex CLI login is required (mocked). Run `codex login`.", "", ""
        command_path = shutil.which(command)
        if not command_path:
            return (
                False,
                False,
                f"Codex CLI command not found: {command}. Install Codex CLI and run `codex login`.",
                "",
                "",
            )
        check_cmd = [command, "exec", "--help"]
        try:
            rc, stdout, stderr = run_cli(check_cmd, timeout_sec=max(1, min(timeout_sec, 10)))
        except Exception as exc:
            return False, False, f"Codex CLI preflight failed: {exc}.", "", ""

        combined = f"{stdout}\n{stderr}".lower()
        stdout_tail = (stdout or "")[-300:]
        stderr_tail = (stderr or "")[-300:]
        auth_tokens = {"login", "unauthorized", "forbidden", "expired"}
        if rc == 0:
            return True, False, "chatgpt_login ready", stdout_tail, stderr_tail
        if any(token in combined for token in auth_tokens):
            return (
                False,
                True,
                "Codex CLI login session missing/expired. Run `codex login` and retry.",
                stdout_tail,
                stderr_tail,
            )
        # Non-auth failures are not treated as auth blockers.
        return True, False, f"Codex CLI preflight returned non-zero (rc={rc}) without auth indicators.", stdout_tail, stderr_tail

    def run_review(
        self,
        role: str,
        context: dict[str, Any],
        provider_cfg: dict[str, Any],
    ) -> tuple[ReviewResult, dict[str, Any]]:
        verification = context["verification"]
        result: ReviewResult = review_verification(verification)
        auth_mode = str(provider_cfg.get("auth_mode", "chatgpt_login")).strip() or "chatgpt_login"
        timeout_sec = int(provider_cfg.get("timeout_sec", 60))
        command = str(provider_cfg.get("command", "codex")).strip() or "codex"
        if auth_mode == "chatgpt_login":
            ok, is_auth, message, stdout_tail, stderr_tail = self._check_chatgpt_login(
                command=command,
                timeout_sec=timeout_sec,
            )
            if not ok:
                return result, {
                    "adapter": "codex",
                    "role": role,
                    "model": provider_cfg.get("model", ""),
                    "provider_type": provider_cfg.get("type", ""),
                    "auth_mode": auth_mode,
                    "command": command,
                    "mode": "auth_required" if is_auth else "fallback_local_review",
                    "error": message if is_auth else "",
                    "note": message if not is_auth else "",
                    "stdout_tail": stdout_tail,
                    "stderr_tail": stderr_tail,
                }
            preflight_note = "" if message == "chatgpt_login ready" else message
        else:
            preflight_note = ""

        raw = {
            "adapter": "codex",
            "role": role,
            "model": provider_cfg.get("model", ""),
            "provider_type": provider_cfg.get("type", ""),
            "auth_mode": auth_mode,
            "command": command,
            "mode": "chatgpt_login_session" if auth_mode == "chatgpt_login" else "api_key",
            "warning": preflight_note,
        }
        return result, raw
