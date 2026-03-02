from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from internal.agents.adapter.provider_client import ProviderClient
from internal.agents.reviewer import review_verification
from internal.schemas.state import ReviewResult


class CodexProviderClient(ProviderClient):
    def _check_chatgpt_login(self, command: str, timeout_sec: int) -> tuple[bool, str]:
        if os.environ.get("MYOPT_MOCK_CODEX_LOGIN_REQUIRED", "").strip() == "1":
            return False, "Codex CLI login is required (mocked). Run `codex login`."
        command_path = shutil.which(command)
        if not command_path:
            return False, f"Codex CLI command not found: {command}. Install Codex CLI and run `codex login`."
        check_cmd = [command, "auth", "status"]
        try:
            proc = subprocess.run(
                check_cmd,
                capture_output=True,
                text=True,
                timeout=max(1, min(timeout_sec, 10)),
            )
        except Exception as exc:
            return False, f"Codex CLI auth check failed: {exc}. Run `codex login`."

        combined = f"{proc.stdout}\n{proc.stderr}".lower()
        if proc.returncode == 0 and all(token not in combined for token in {"login", "unauthorized", "expired"}):
            return True, "chatgpt_login ready"
        return False, "Codex CLI login session missing/expired. Run `codex login` and retry."

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
            ok, message = self._check_chatgpt_login(command=command, timeout_sec=timeout_sec)
            if not ok:
                return result, {
                    "adapter": "codex",
                    "role": role,
                    "model": provider_cfg.get("model", ""),
                    "provider_type": provider_cfg.get("type", ""),
                    "auth_mode": auth_mode,
                    "command": command,
                    "mode": "auth_required",
                    "error": message,
                }

        raw = {
            "adapter": "codex",
            "role": role,
            "model": provider_cfg.get("model", ""),
            "provider_type": provider_cfg.get("type", ""),
            "auth_mode": auth_mode,
            "command": command,
            "mode": "chatgpt_login_session" if auth_mode == "chatgpt_login" else "api_key",
        }
        return result, raw
