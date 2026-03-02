from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from internal.agents.adapter.codex_provider import CodexProviderClient
from internal.agents.adapter.google_provider import GoogleProviderClient
from internal.agents.adapter.local_provider import LocalProviderClient
from internal.agents.adapter.provider_client import ProviderClient
from internal.schemas.state import ReviewResult


def load_provider_registry(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"provider config parsing failed. Use JSON-compatible YAML (path: {path})"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError("provider config root must be an object")
    return data


def apply_provider_overrides(registry: dict[str, Any], overrides: list[str]) -> dict[str, Any]:
    merged = copy.deepcopy(registry)
    for item in overrides:
        if "=" not in item or "." not in item:
            raise ValueError(f"invalid override format: {item}")
        key, raw_value = item.split("=", 1)
        provider, field_path = key.split(".", 1)
        if provider not in merged:
            raise ValueError(f"unknown provider in override: {provider}")

        value: Any
        lowered = raw_value.lower()
        if lowered == "true":
            value = True
        elif lowered == "false":
            value = False
        else:
            try:
                value = int(raw_value)
            except ValueError:
                try:
                    value = float(raw_value)
                except ValueError:
                    value = raw_value

        target = merged[provider]
        parts = field_path.split(".")
        for part in parts[:-1]:
            if part not in target or not isinstance(target[part], dict):
                target[part] = {}
            target = target[part]
        target[parts[-1]] = value
    return merged


class AgentAdapter:
    def __init__(self) -> None:
        self._clients: dict[str, ProviderClient] = {
            "codex": CodexProviderClient(),
            "google": GoogleProviderClient(),
            "local": LocalProviderClient(),
        }

    def supports(self, provider: str) -> bool:
        return provider in self._clients

    def run_review(
        self,
        provider: str,
        role: str,
        context: dict[str, Any],
        provider_cfg: dict[str, Any],
    ) -> tuple[ReviewResult, dict[str, Any]]:
        client = self._clients[provider]
        return client.run_review(role=role, context=context, provider_cfg=provider_cfg)
