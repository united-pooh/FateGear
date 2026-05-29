"""Persistence protocol for scenario runtime state."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ..session.state import SessionMapState

if TYPE_CHECKING:
    from ..runtime.contracts import TurnResolution


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
