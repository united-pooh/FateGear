"""Persistence protocol for scenario runtime state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from ..session.state import SessionMapState

if TYPE_CHECKING:
    from ..runtime.contracts import TurnResolution


class ScenarioStateStoreError(RuntimeError):
    """Base error for durable state store failures."""


class ScenarioStateStoreLockError(ScenarioStateStoreError):
    """Raised when the store cannot acquire its local consistency lock."""


class ScenarioStateStoreDataError(ScenarioStateStoreError):
    """Raised when persisted state cannot be decoded or validated."""


@dataclass(frozen=True)
class StoreOperationSnapshot:
    """Small latency/count sample for one store operation."""

    count: int = 0
    failures: int = 0
    last_latency_ms: float | None = None
    average_latency_ms: float | None = None


@dataclass(frozen=True)
class StoreObservabilityEvent:
    """Recent store event for local diagnostics."""

    operation: str
    status: str
    message: str = ""
    path: str | None = None
    latency_ms: float | None = None


@dataclass(frozen=True)
class StoreHealthSnapshot:
    """Point-in-time health and observability view for a state store."""

    store_type: str
    healthy: bool
    paths: dict[str, str]
    counts: dict[str, int]
    operations: dict[str, StoreOperationSnapshot] = field(default_factory=dict)
    last_error: str | None = None
    recent_events: tuple[StoreObservabilityEvent, ...] = ()


class ScenarioStateStore(Protocol):
    """Minimal durable state boundary used by ``SceneRuntime``."""

    def save_session(self, session: SessionMapState) -> None:
        """Persist the latest authoritative session snapshot."""

    def load_sessions(self) -> dict[str, SessionMapState]:
        """Load all persisted session snapshots keyed by session id."""

    def delete_session(self, session_id: str) -> None:
        """Delete a session snapshot and its related turn records."""

    def save_turn(self, resolution: "TurnResolution") -> None:
        """Persist an authoritative turn resolution for replay."""

    def load_turns(self, session_id: str) -> dict[int, "TurnResolution"]:
        """Load persisted turn resolutions for a session keyed by turn number."""

    def list_session_ids(self) -> list[str]:
        """List session ids known to the durable store."""


class ScenarioStateStoreHealth(Protocol):
    """Optional diagnostics surface implemented by observable stores."""

    def health_snapshot(self) -> StoreHealthSnapshot:
        """Return local health, path, count, and operation-latency details."""
