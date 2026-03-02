from __future__ import annotations

from typing import Any

from internal.agents.adapter.provider_client import ProviderClient
from internal.agents.reviewer import review_verification
from internal.schemas.state import ReviewResult


class LocalProviderClient(ProviderClient):
    def run_review(
        self,
        role: str,
        context: dict[str, Any],
        provider_cfg: dict[str, Any],
    ) -> tuple[ReviewResult, dict[str, Any]]:
        verification = context["verification"]
        result: ReviewResult = review_verification(verification)
        raw = {
            "adapter": "local",
            "role": role,
            "model": provider_cfg.get("model", "rule-based"),
            "provider_type": provider_cfg.get("type", "local"),
            "mode": "inprocess",
        }
        return result, raw
