from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

KST = timezone(timedelta(hours=9))
SENSITIVE_KEYS = {"api_key", "token", "secret", "password", "passwd", "key"}
MAX_STR_LEN = 400
MAX_LIST_ITEMS = 20


def _safe_value(value: Any) -> Any:
    if isinstance(value, str):
        if len(value) <= MAX_STR_LEN:
            return value
        return value[:MAX_STR_LEN] + "...(truncated)"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, inner in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in SENSITIVE_KEYS):
                out[key] = "***"
            else:
                out[key] = _safe_value(inner)
        return out
    if isinstance(value, list):
        capped = value[:MAX_LIST_ITEMS]
        out = [_safe_value(item) for item in capped]
        if len(value) > MAX_LIST_ITEMS:
            out.append(f"...({len(value) - MAX_LIST_ITEMS} more)")
        return out
    return value


@dataclass
class TraceWriter:
    path: Path

    def event(self, name: str, **fields: Any) -> None:
        payload = {
            "ts": datetime.now(KST).isoformat(timespec="seconds"),
            "event": name,
            **_safe_value(fields),
        }
        with self.path.open("a", encoding="utf-8", errors="replace") as fp:
            fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
