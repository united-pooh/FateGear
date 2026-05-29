"""JSON-backed persistence for scenario runtime state."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..session.state import SessionMapState

if TYPE_CHECKING:
    from ..runtime.contracts import TurnResolution


class JsonScenarioStateStore:
    """Persist sessions and turn resolutions as plain JSON files.

    The store is intentionally small and local-first: it gives the runtime a
    restart-safe recovery path without introducing a database dependency.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._sessions_dir = self._root / "sessions"
        self._turns_dir = self._root / "turns"

    def save_session(self, session: SessionMapState) -> None:
        payload = session.model_dump(mode="json")
        self._restore_excluded_investigator_state_limits(payload)
        self._write_json(self._session_path(session.session_id), payload)

    def load_sessions(self) -> dict[str, SessionMapState]:
        if not self._sessions_dir.exists():
            return {}
        sessions: dict[str, SessionMapState] = {}
        for path in sorted(self._sessions_dir.glob("*.json")):
            session = SessionMapState.model_validate(self._read_json(path))
            sessions[session.session_id] = session
        return sessions

    def delete_session(self, session_id: str) -> None:
        self._session_path(session_id).unlink(missing_ok=True)
        shutil.rmtree(self._turn_session_dir(session_id), ignore_errors=True)

    def save_turn(self, resolution: "TurnResolution") -> None:
        payload = resolution.model_dump(mode="json")
        self._write_json(
            self._turn_path(resolution.session_id, resolution.turn_no),
            payload,
        )

    def load_turns(self, session_id: str) -> dict[int, "TurnResolution"]:
        from ..runtime.contracts import TurnResolution

        turn_dir = self._turn_session_dir(session_id)
        if not turn_dir.exists():
            return {}
        turns: dict[int, TurnResolution] = {}
        for path in sorted(turn_dir.glob("*.json")):
            resolution = TurnResolution.model_validate(self._read_json(path))
            turns[resolution.turn_no] = resolution
        return turns

    def list_session_ids(self) -> list[str]:
        if not self._sessions_dir.exists():
            return []
        return sorted(path.stem for path in self._sessions_dir.glob("*.json"))

    def _session_path(self, session_id: str) -> Path:
        return self._sessions_dir / f"{session_id}.json"

    def _turn_session_dir(self, session_id: str) -> Path:
        return self._turns_dir / session_id

    def _turn_path(self, session_id: str, turn_no: int) -> Path:
        return self._turn_session_dir(session_id) / f"{turn_no}.json"

    def _read_json(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(path)

    def _restore_excluded_investigator_state_limits(
        self,
        payload: dict[str, Any],
    ) -> None:
        for player_state in payload.get("player_states", {}).values():
            if not isinstance(player_state, dict):
                continue
            investigator = player_state.get("investigator")
            if not isinstance(investigator, dict):
                continue
            derived = investigator.get("derived")
            state = investigator.get("state")
            if not isinstance(derived, dict) or not isinstance(state, dict):
                continue
            state.setdefault("hit_points_max", derived.get("hit_points_max"))
            state.setdefault("magic_points_max", derived.get("magic_points_max"))
            state.setdefault("sanity_max", derived.get("sanity_max"))
