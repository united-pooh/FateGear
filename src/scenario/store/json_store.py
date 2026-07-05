"""JSON-backed persistence for scenario runtime state."""

from __future__ import annotations

from collections import Counter, deque
from contextlib import contextmanager
import errno
import json
import os
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

from pydantic import ValidationError

from .protocols import (
    ScenarioStateStoreDataError,
    ScenarioStateStoreLockError,
    StoreHealthSnapshot,
    StoreObservabilityEvent,
    StoreOperationSnapshot,
)
from ..session.state import SessionMapState

if TYPE_CHECKING:
    from ..runtime.contracts import TurnResolution

try:  # pragma: no cover - platform dependent import
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback path
    fcntl = None

try:  # pragma: no cover - platform dependent import
    import msvcrt
except ImportError:  # pragma: no cover - POSIX path
    msvcrt = None

_QUARANTINED = object()


class JsonScenarioStateStore:
    """Persist sessions and turn resolutions as plain JSON files.

    The store is intentionally small and local-first: it gives the runtime a
    restart-safe recovery path without introducing a database dependency.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        use_file_lock: bool = True,
        quarantine_corrupt: bool = True,
        recent_event_limit: int = 20,
    ) -> None:
        self._root = Path(root)
        self._sessions_dir = self._root / "sessions"
        self._turns_dir = self._root / "turns"
        self._quarantine_dir = self._root / "quarantine"
        self._lock_path = self._root / ".scenario-state.lock"
        self._use_file_lock = use_file_lock
        self._quarantine_corrupt = quarantine_corrupt
        self._operation_counts: Counter[str] = Counter()
        self._operation_failures: Counter[str] = Counter()
        self._operation_total_latency_ms: Counter[str] = Counter()
        self._operation_last_latency_ms: dict[str, float] = {}
        self._last_error: str | None = None
        self._recent_events: deque[StoreObservabilityEvent] = deque(
            maxlen=recent_event_limit
        )

    def save_session(self, session: SessionMapState) -> None:
        with self._record_operation("save_session"):
            with self._file_lock():
                payload = session.model_dump(mode="json")
                self._restore_excluded_investigator_state_limits(payload)
                self._write_json(self._session_path(session.session_id), payload)

    def load_sessions(self) -> dict[str, SessionMapState]:
        with self._record_operation("load_sessions"):
            with self._file_lock():
                if not self._sessions_dir.exists():
                    return {}
                sessions: dict[str, SessionMapState] = {}
                for path in sorted(self._sessions_dir.glob("*.json")):
                    payload = self._read_json(path, category="sessions")
                    if payload is _QUARANTINED:
                        continue
                    try:
                        session = SessionMapState.model_validate(payload)
                    except ValidationError as exc:
                        if self._quarantine_corrupt:
                            self._quarantine_file(
                                path,
                                "sessions",
                                f"schema validation failed: {exc}",
                            )
                            continue
                        raise ScenarioStateStoreDataError(
                            f"Invalid session state file {path}: {exc}"
                        ) from exc
                    sessions[session.session_id] = session
                return sessions

    def delete_session(self, session_id: str) -> None:
        with self._record_operation("delete_session"):
            with self._file_lock():
                self._session_path(session_id).unlink(missing_ok=True)
                shutil.rmtree(self._turn_session_dir(session_id), ignore_errors=True)

    def save_turn(self, resolution: "TurnResolution") -> None:
        with self._record_operation("save_turn"):
            with self._file_lock():
                payload = resolution.model_dump(mode="json")
                self._write_json(
                    self._turn_path(resolution.session_id, resolution.turn_no),
                    payload,
                )

    def load_turns(self, session_id: str) -> dict[int, "TurnResolution"]:
        from ..runtime.contracts import TurnResolution

        with self._record_operation("load_turns"):
            with self._file_lock():
                turn_dir = self._turn_session_dir(session_id)
                if not turn_dir.exists():
                    return {}
                turns: dict[int, TurnResolution] = {}
                for path in sorted(turn_dir.glob("*.json")):
                    payload = self._read_json(path, category="turns")
                    if payload is _QUARANTINED:
                        continue
                    try:
                        resolution = TurnResolution.model_validate(payload)
                    except ValidationError as exc:
                        if self._quarantine_corrupt:
                            self._quarantine_file(
                                path,
                                "turns",
                                f"schema validation failed: {exc}",
                            )
                            continue
                        raise ScenarioStateStoreDataError(
                            f"Invalid turn state file {path}: {exc}"
                        ) from exc
                    turns[resolution.turn_no] = resolution
                return turns

    def list_session_ids(self) -> list[str]:
        with self._record_operation("list_session_ids"):
            with self._file_lock():
                if not self._sessions_dir.exists():
                    return []
                session_ids: list[str] = []
                for path in sorted(self._sessions_dir.glob("*.json")):
                    payload = self._read_json(path, category="sessions")
                    if payload is _QUARANTINED:
                        continue
                    if isinstance(payload, dict) and isinstance(
                        payload.get("session_id"), str
                    ):
                        session_ids.append(payload["session_id"])
                        continue
                    if self._quarantine_corrupt:
                        self._quarantine_file(
                            path,
                            "sessions",
                            "missing string session_id",
                        )
                        continue
                    raise ScenarioStateStoreDataError(
                        f"Invalid session state file {path}: missing session_id"
                    )
                return sorted(session_ids)

    def health_snapshot(self) -> StoreHealthSnapshot:
        """Return a small diagnostics snapshot without taking the write lock."""

        counts = self._count_files()
        operations: dict[str, StoreOperationSnapshot] = {}
        for operation in sorted(self._operation_counts):
            count = self._operation_counts[operation]
            total_latency = self._operation_total_latency_ms[operation]
            operations[operation] = StoreOperationSnapshot(
                count=count,
                failures=self._operation_failures[operation],
                last_latency_ms=self._round_latency(
                    self._operation_last_latency_ms.get(operation)
                ),
                average_latency_ms=self._round_latency(
                    total_latency / count if count else None
                ),
            )
        return StoreHealthSnapshot(
            store_type="json",
            healthy=self._last_error is None,
            paths={
                "root": str(self._root),
                "sessions": str(self._sessions_dir),
                "turns": str(self._turns_dir),
                "quarantine": str(self._quarantine_dir),
                "lock": str(self._lock_path),
            },
            counts=counts,
            operations=operations,
            last_error=self._last_error,
            recent_events=tuple(self._recent_events),
        )

    def _session_path(self, session_id: str) -> Path:
        return self._sessions_dir / f"{session_id}.json"

    def _turn_session_dir(self, session_id: str) -> Path:
        return self._turns_dir / session_id

    def _turn_path(self, session_id: str, turn_no: int) -> Path:
        return self._turn_session_dir(session_id) / f"{turn_no}.json"

    def _read_json(self, path: Path, *, category: str) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            if self._quarantine_corrupt:
                self._quarantine_file(path, category, f"invalid JSON: {exc}")
                return _QUARANTINED
            raise ScenarioStateStoreDataError(
                f"Invalid JSON in {path}: {exc}"
            ) from exc

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        )
        tmp_path = path.with_name(
            f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
        )
        try:
            with tmp_path.open("w", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
            self._fsync_dir(path.parent)
        finally:
            tmp_path.unlink(missing_ok=True)

    @contextmanager
    def _file_lock(self) -> Iterator[None]:
        if not self._use_file_lock:
            yield
            return
        if fcntl is None and msvcrt is None:
            raise ScenarioStateStoreLockError(
                "Scenario state store file locking is not supported on this platform"
            )

        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+", encoding="utf-8") as lock_file:
            try:
                if fcntl is not None:
                    fcntl.flock(
                        lock_file.fileno(),
                        fcntl.LOCK_EX | fcntl.LOCK_NB,
                    )
                else:
                    lock_file.seek(0)
                    lock_file.write("0")
                    lock_file.flush()
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            except BlockingIOError as exc:
                raise ScenarioStateStoreLockError(
                    f"Scenario state store lock is already held: {self._lock_path}"
                ) from exc
            except OSError as exc:
                if exc.errno in {errno.EACCES, errno.EAGAIN}:
                    raise ScenarioStateStoreLockError(
                        f"Scenario state store lock is already held: {self._lock_path}"
                    ) from exc
                raise
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                else:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)

    @contextmanager
    def _record_operation(self, operation: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._finish_operation(operation, elapsed_ms, error=exc)
            raise
        else:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._finish_operation(operation, elapsed_ms)

    def _finish_operation(
        self,
        operation: str,
        elapsed_ms: float,
        *,
        error: Exception | None = None,
    ) -> None:
        self._operation_counts[operation] += 1
        self._operation_total_latency_ms[operation] += elapsed_ms
        self._operation_last_latency_ms[operation] = elapsed_ms
        if error is None:
            self._record_event(
                operation,
                "ok",
                latency_ms=self._round_latency(elapsed_ms),
            )
            return
        self._operation_failures[operation] += 1
        self._last_error = f"{error.__class__.__name__}: {error}"
        self._record_event(
            operation,
            "error",
            message=self._last_error,
            latency_ms=self._round_latency(elapsed_ms),
        )

    def _quarantine_file(self, path: Path, category: str, reason: str) -> Path | None:
        if not path.exists():
            return None
        quarantine_dir = self._quarantine_dir / category
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        destination = quarantine_dir / (
            f"{time.strftime('%Y%m%dT%H%M%S')}-{time.time_ns()}-{path.name}"
        )
        shutil.move(str(path), destination)
        message = f"quarantined {category} file {path}: {reason}"
        self._last_error = message
        self._record_event(
            "quarantine",
            "warning",
            message=message,
            path=str(destination),
        )
        return destination

    def _count_files(self) -> dict[str, int]:
        return {
            "sessions": self._count_glob(self._sessions_dir, "*.json"),
            "turns": self._count_glob(self._turns_dir, "*/*.json"),
            "quarantined_files": self._count_glob(self._quarantine_dir, "**/*"),
            "temp_files": self._count_glob(self._root, "**/*.tmp"),
        }

    def _count_glob(self, root: Path, pattern: str) -> int:
        if not root.exists():
            return 0
        return sum(1 for path in root.glob(pattern) if path.is_file())

    def _record_event(
        self,
        operation: str,
        status: str,
        *,
        message: str = "",
        path: str | None = None,
        latency_ms: float | None = None,
    ) -> None:
        self._recent_events.append(
            StoreObservabilityEvent(
                operation=operation,
                status=status,
                message=message,
                path=path,
                latency_ms=latency_ms,
            )
        )

    def _round_latency(self, value: float | None) -> float | None:
        if value is None:
            return None
        return round(value, 3)

    def _fsync_dir(self, path: Path) -> None:
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        try:
            fd = os.open(path, flags)
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

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
