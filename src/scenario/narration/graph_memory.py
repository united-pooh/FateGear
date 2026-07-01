"""Local temporal graph memory database for narration continuity."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .contracts import KeeperNarrationRecord, NarrationPatchProposal
from .patches import is_allowed_narrative_path, is_authoritative_path


SCHEMA_VERSION = "2"
ACTIVE_STATUS = "active"
SUPERSEDED_STATUS = "superseded"


class SQLiteNarrationGraphMemory:
    """SQLite-backed temporal fact graph derived from accepted narration records."""

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._connection: sqlite3.Connection | None = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._initialize()

    def __enter__(self) -> SQLiteNarrationGraphMemory:
        self._ensure_open()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        if self._connection is None:
            return
        self._connection.close()
        self._connection = None

    def ingest_record(self, record: KeeperNarrationRecord) -> list[dict[str, Any]]:
        """Ingest accepted NarrativeState patches as scoped temporal facts."""

        connection = self._ensure_open()
        session_id = record.session_id
        module_id = _record_module_id(record)
        _ensure_graph_scope(session_id=session_id, module_id=module_id)
        now = self._now()
        inserted: list[dict[str, Any]] = []
        with connection:
            cited_memory_ids = list(dict.fromkeys(record.cited_memory_ids))
            for memory_id in cited_memory_ids:
                self._upsert_entity(
                    session_id=session_id,
                    module_id=module_id,
                    entity_id=f"memory:{memory_id}",
                    entity_type="memory",
                    label=memory_id,
                    now=now,
                )

            for patch in record.accepted_patches:
                _ensure_ingestable_patch_path(patch)
                fact = self._insert_patch_fact(
                    record=record,
                    patch=patch,
                    session_id=session_id,
                    module_id=module_id,
                    now=now,
                )
                inserted.append(fact)
                for memory_id in cited_memory_ids:
                    self._insert_edge(
                        session_id=session_id,
                        module_id=module_id,
                        source_entity_id=fact["entity_id"],
                        relation="cites_memory",
                        target_entity_id=f"memory:{memory_id}",
                        source_fact_id=fact["fact_id"],
                        source_record_id=record.record_id,
                        now=now,
                    )
        return inserted

    def facts_for_entity(
        self,
        entity_id: str,
        *,
        session_id: str,
        module_id: str,
        include_inactive: bool = False,
        as_of_turn: int | None = None,
    ) -> list[dict[str, Any]]:
        connection = self._ensure_open()
        where = "entity_id = ? AND session_id = ? AND module_id = ?"
        params: list[Any] = [entity_id, session_id, module_id]
        if as_of_turn is not None:
            where += """
                AND valid_from_turn <= ?
                AND (valid_to_turn IS NULL OR ? < valid_to_turn)
            """
            params.extend([as_of_turn, as_of_turn])
        elif not include_inactive:
            where += " AND status = ?"
            params.append(ACTIVE_STATUS)
        rows = connection.execute(
            f"""
            SELECT *
            FROM facts
            WHERE {where}
            ORDER BY valid_from_turn DESC, fact_id ASC
            """,
            params,
        ).fetchall()
        return [_fact_row(row) for row in rows]

    def facts_as_of(
        self,
        entity_id: str,
        turn_no: int,
        *,
        session_id: str,
        module_id: str,
    ) -> list[dict[str, Any]]:
        return self.facts_for_entity(
            entity_id,
            session_id=session_id,
            module_id=module_id,
            as_of_turn=turn_no,
        )

    def search_facts(
        self,
        query: str,
        *,
        session_id: str,
        module_id: str,
        include_inactive: bool = False,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        connection = self._ensure_open()
        needle = f"%{query}%"
        params: list[Any] = [session_id, module_id, needle, needle, needle, needle]
        status_clause = ""
        if not include_inactive:
            status_clause = "AND status = ?"
            params.append(ACTIVE_STATUS)
        params.append(limit)
        rows = connection.execute(
            f"""
            SELECT *
            FROM facts
            WHERE session_id = ?
                AND module_id = ?
                AND (
                    entity_id LIKE ?
                    OR relation LIKE ?
                    OR value LIKE ?
                    OR summary_text LIKE ?
                )
            {status_clause}
            ORDER BY valid_from_turn DESC, fact_id ASC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [_fact_row(row) for row in rows]

    def export_audit(self) -> dict[str, Any]:
        connection = self._ensure_open()
        schema_meta = {
            row["key"]: row["value"]
            for row in connection.execute(
                "SELECT key, value FROM schema_meta ORDER BY key ASC"
            ).fetchall()
        }
        entities = [
            dict(row)
            for row in connection.execute(
                """
                SELECT *
                FROM entities
                ORDER BY session_id ASC, module_id ASC, entity_id ASC
                """
            ).fetchall()
        ]
        facts = [
            _fact_row(row)
            for row in connection.execute(
                """
                SELECT *
                FROM facts
                ORDER BY session_id ASC, module_id ASC, entity_id ASC, valid_from_turn ASC
                """
            ).fetchall()
        ]
        edges = [
            dict(row)
            for row in connection.execute(
                """
                SELECT *
                FROM edges
                ORDER BY session_id ASC, module_id ASC, edge_id ASC
                """
            ).fetchall()
        ]
        return {
            "path": str(self.path),
            "schema_version": schema_meta.get("schema_version", ""),
            "schema_meta": schema_meta,
            "entity_count": len(entities),
            "fact_count": len(facts),
            "edge_count": len(edges),
            "entities": entities,
            "facts": facts,
            "edges": edges,
        }

    def _initialize(self) -> None:
        connection = self._ensure_open()
        with connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY CHECK (length(key) > 0),
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS entities (
                    entity_uid TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL CHECK (length(session_id) > 0),
                    module_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL CHECK (length(entity_id) > 0),
                    entity_type TEXT NOT NULL CHECK (length(entity_type) > 0),
                    label TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (session_id, module_id, entity_id)
                );

                CREATE TABLE IF NOT EXISTS facts (
                    fact_id TEXT PRIMARY KEY,
                    entity_uid TEXT NOT NULL,
                    session_id TEXT NOT NULL CHECK (length(session_id) > 0),
                    module_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL CHECK (length(entity_id) > 0),
                    relation TEXT NOT NULL CHECK (length(relation) > 0),
                    value TEXT NOT NULL,
                    summary_text TEXT NOT NULL,
                    source_record_id TEXT NOT NULL CHECK (length(source_record_id) > 0),
                    source_event_ids_json TEXT NOT NULL,
                    valid_from_turn INTEGER NOT NULL CHECK (valid_from_turn >= 1),
                    valid_to_turn INTEGER CHECK (
                        valid_to_turn IS NULL OR valid_to_turn >= valid_from_turn
                    ),
                    status TEXT NOT NULL CHECK (status IN ('active', 'superseded')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (entity_uid) REFERENCES entities(entity_uid)
                        ON UPDATE CASCADE ON DELETE CASCADE,
                    FOREIGN KEY (session_id, module_id, entity_id)
                        REFERENCES entities(session_id, module_id, entity_id)
                        ON UPDATE CASCADE ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS edges (
                    edge_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL CHECK (length(session_id) > 0),
                    module_id TEXT NOT NULL,
                    source_entity_uid TEXT NOT NULL,
                    source_entity_id TEXT NOT NULL CHECK (length(source_entity_id) > 0),
                    relation TEXT NOT NULL CHECK (length(relation) > 0),
                    target_entity_uid TEXT NOT NULL,
                    target_entity_id TEXT NOT NULL CHECK (length(target_entity_id) > 0),
                    source_fact_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (source_entity_uid) REFERENCES entities(entity_uid)
                        ON UPDATE CASCADE ON DELETE CASCADE,
                    FOREIGN KEY (target_entity_uid) REFERENCES entities(entity_uid)
                        ON UPDATE CASCADE ON DELETE CASCADE,
                    FOREIGN KEY (source_fact_id) REFERENCES facts(fact_id)
                        ON UPDATE CASCADE ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_entities_scope_entity
                    ON entities(session_id, module_id, entity_id);
                CREATE INDEX IF NOT EXISTS idx_facts_scope_entity_status
                    ON facts(session_id, module_id, entity_id, status);
                CREATE INDEX IF NOT EXISTS idx_facts_scope_validity
                    ON facts(session_id, module_id, entity_id, valid_from_turn, valid_to_turn);
                CREATE INDEX IF NOT EXISTS idx_edges_scope_source
                    ON edges(session_id, module_id, source_entity_id);
                CREATE INDEX IF NOT EXISTS idx_edges_scope_target
                    ON edges(session_id, module_id, target_entity_id);
                """
            )
            connection.execute(
                """
                INSERT INTO schema_meta (key, value)
                VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (SCHEMA_VERSION,),
            )

    def _insert_patch_fact(
        self,
        *,
        record: KeeperNarrationRecord,
        patch: NarrationPatchProposal,
        session_id: str,
        module_id: str,
        now: str,
    ) -> dict[str, Any]:
        connection = self._ensure_open()
        entity_id = f"path:{patch.path}"
        entity_uid = _entity_uid(session_id, module_id, entity_id)
        relation = "narrative_state"
        value = _value_text(patch.new_value)
        source_event_ids = list(dict.fromkeys(patch.source_event_ids))
        fact_id = _stable_id(
            "fact",
            session_id,
            module_id,
            record.record_id,
            patch.path,
            value,
            str(record.turn_no),
        )
        self._upsert_entity(
            session_id=session_id,
            module_id=module_id,
            entity_id=entity_id,
            entity_type=patch.path.split(".", 1)[0],
            label=patch.path,
            now=now,
        )
        connection.execute(
            """
            UPDATE facts
            SET status = ?, valid_to_turn = ?, updated_at = ?
            WHERE session_id = ?
                AND module_id = ?
                AND entity_id = ?
                AND relation = ?
                AND status = ?
            """,
            (
                SUPERSEDED_STATUS,
                record.turn_no,
                now,
                session_id,
                module_id,
                entity_id,
                relation,
                ACTIVE_STATUS,
            ),
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO facts (
                fact_id,
                entity_uid,
                session_id,
                module_id,
                entity_id,
                relation,
                value,
                summary_text,
                source_record_id,
                source_event_ids_json,
                valid_from_turn,
                valid_to_turn,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            """,
            (
                fact_id,
                entity_uid,
                session_id,
                module_id,
                entity_id,
                relation,
                value,
                f"{patch.path} -> {value}",
                record.record_id,
                json.dumps(source_event_ids, ensure_ascii=False),
                record.turn_no,
                ACTIVE_STATUS,
                now,
                now,
            ),
        )
        return _fact_row(
            connection.execute(
                "SELECT * FROM facts WHERE fact_id = ?",
                (fact_id,),
            ).fetchone()
        )

    def _upsert_entity(
        self,
        *,
        session_id: str,
        module_id: str,
        entity_id: str,
        entity_type: str,
        label: str,
        now: str,
    ) -> None:
        connection = self._ensure_open()
        entity_uid = _entity_uid(session_id, module_id, entity_id)
        connection.execute(
            """
            INSERT INTO entities (
                entity_uid,
                session_id,
                module_id,
                entity_id,
                entity_type,
                label,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_uid) DO UPDATE SET
                entity_type = excluded.entity_type,
                label = excluded.label,
                updated_at = excluded.updated_at
            """,
            (
                entity_uid,
                session_id,
                module_id,
                entity_id,
                entity_type,
                label,
                now,
                now,
            ),
        )

    def _insert_edge(
        self,
        *,
        session_id: str,
        module_id: str,
        source_entity_id: str,
        relation: str,
        target_entity_id: str,
        source_fact_id: str,
        source_record_id: str,
        now: str,
    ) -> None:
        connection = self._ensure_open()
        source_entity_uid = _entity_uid(session_id, module_id, source_entity_id)
        target_entity_uid = _entity_uid(session_id, module_id, target_entity_id)
        edge_id = _stable_id(
            "edge",
            session_id,
            module_id,
            source_record_id,
            source_entity_id,
            relation,
            target_entity_id,
            source_fact_id,
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO edges (
                edge_id,
                session_id,
                module_id,
                source_entity_uid,
                source_entity_id,
                relation,
                target_entity_uid,
                target_entity_id,
                source_fact_id,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edge_id,
                session_id,
                module_id,
                source_entity_uid,
                source_entity_id,
                relation,
                target_entity_uid,
                target_entity_id,
                source_fact_id,
                now,
            ),
        )

    def _now(self) -> str:
        return self._clock().astimezone(UTC).isoformat()

    def _ensure_open(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("SQLiteNarrationGraphMemory is closed")
        return self._connection


def _ensure_ingestable_patch_path(patch: NarrationPatchProposal) -> None:
    if is_authoritative_path(patch.path):
        raise ValueError(f"cannot ingest authoritative narration path: {patch.path}")
    if not is_allowed_narrative_path(patch.path):
        raise ValueError(f"cannot ingest non-NarrativeState path: {patch.path}")


def _ensure_graph_scope(*, session_id: str, module_id: str) -> None:
    if not session_id or not module_id:
        raise ValueError("graph memory requires non-empty session_id and module_id")


def _record_module_id(record: KeeperNarrationRecord) -> str:
    packet = record.replay_input.get("packet") if isinstance(record.replay_input, dict) else None
    if isinstance(packet, dict):
        module_id = packet.get("module_id")
        return str(module_id) if module_id is not None else ""
    return ""


def _fact_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["source_event_ids"] = json.loads(data.pop("source_event_ids_json"))
    return data


def _value_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _entity_uid(session_id: str, module_id: str, entity_id: str) -> str:
    return _stable_id("entity", session_id, module_id, entity_id)


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:16]}"
