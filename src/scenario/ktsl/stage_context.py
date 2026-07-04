"""TurnStage protocol and shared context types."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class KTSLIntervention(Enum):
    """Three levels of KTSL intervention on a player action."""

    ALLOW = "allow"
    REDACT = "redact"
    BLOCK = "block"


class StageResult(BaseModel):
    """Output of one pipeline stage."""

    status: Literal["continue", "blocked", "wait"] = "continue"
    interventions: list[Any] = Field(default_factory=list)

    def to_events(self) -> list[Any]:
        """Convert interventions to RuntimeEvents (override in subclasses)."""
        return []


class StageContext:
    """Mutable context running through one resolution turn.

    Stages communicate via `scratch` — a key-value dict. Only keys prefixed
    with `commit_` are persisted to the ledger by the pipeline driver.
    """

    def __init__(self, snapshot: Any, ledger: Any, event_log: list[Any]) -> None:
        self.snapshot = snapshot
        self.ledger = ledger
        self.event_log = event_log
        self.scene: Any = None
        self.intents: list[tuple[str, dict[str, object]]] = []
        self.scratch: dict[str, Any] = {}

    def commit_scratch_to_ledger(self) -> None:
        """Write scratch-prefixed keys into ledger."""
        for key, value in self.scratch.items():
            if key.startswith("commit_"):
                target = key[len("commit_"):]
                if target == "events" and isinstance(value, list):
                    for event in value:
                        if hasattr(self.ledger, "commit_event"):
                            self.ledger.commit_event(event)

    def mark_blocked(self, interventions: list[Any]) -> None:
        self.scratch.setdefault("blocked_interventions", []).extend(interventions)
