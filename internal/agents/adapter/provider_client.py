from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from internal.schemas.state import ReviewResult


class ProviderClient(ABC):
    @abstractmethod
    def run_review(
        self,
        role: str,
        context: dict[str, Any],
        provider_cfg: dict[str, Any],
    ) -> tuple[ReviewResult, dict[str, Any]]:
        raise NotImplementedError
