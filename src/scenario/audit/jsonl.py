"""JSONL audit writer for KP review."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any


class JsonlKPAuditLogger:
    """Append one KP-visible audit event per JSONL line."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = Lock()

    @property
    def path(self) -> Path:
        return self._path

    def append(
        self,
        event_type: str,
        *,
        session_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "schema_version": 1,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "event_type": event_type,
        }
        if session_id:
            entry["session_id"] = session_id
        if payload:
            entry.update(payload)

        encoded = json.dumps(entry, ensure_ascii=False, default=str)
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
                stream.write("\n")
