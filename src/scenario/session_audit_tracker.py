"""Streaming session audit tracker for KTSL KP workflow.

Maintains a runtime world state snapshot as KP submits actions, runs the
three-layer (schedule / filter / coupling) incremental check, and accumulates
metrics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .ktsl.filter import SENSITIVE_LEVELS, decide_info_access
from .ktsl.models import (
    ActorKnowledgeState,
    AuditEntry,
    AuditResult,
    BarrierState,
    CommitStatus,
    CouplingState,
    EventRecord,
    InfoLabel,
    KTSLFixture,
    KnowledgeItem,
    ManualOverrides,
    MetricSummary,
    SessionConfig,
    SessionSummary,
    Visibility,
)
from .runtime_event import RuntimeEventAdapter


# Lightweight knowledge tracking for an actor inside a session
@dataclass
class _ActorState:
    character_id: str
    known_info_ids: set[str] = field(default_factory=set)
    observed_info_ids: set[str] = field(default_factory=set)
    authorized_info_ids: set[str] = field(default_factory=set)
    acquired: list[KnowledgeItem] = field(default_factory=list)


@dataclass
class SessionState:
    """Serializable snapshot of a running / completed session."""

    fixture: KTSLFixture
    committed_event_ids: set[str] = field(default_factory=set)
    knowledge_state: dict[str, _ActorState] = field(default_factory=dict)
    event_log: list[EventRecord] = field(default_factory=list)
    violations: list[AuditEntry] = field(default_factory=list)
    metrics: MetricSummary = field(default_factory=MetricSummary)
    config: SessionConfig = field(
        default_factory=lambda: SessionConfig(fixture_id="")
    )
    event_counter: int = 0


class SessionAuditTracker:
    """Submit actions, audit, accumulate metrics, save/load state."""

    def __init__(
        self,
        fixture: KTSLFixture,
        config: SessionConfig | None = None,
    ) -> None:
        self._fixture = fixture
        self._adapter = RuntimeEventAdapter(fixture)

        if config is None:
            config = SessionConfig(
                fixture_id=fixture.id,
                started_at=datetime.now(timezone.utc).isoformat(),
            )
        self._state = SessionState(
            fixture=fixture,
            config=config,
            metrics=MetricSummary(
                committed_event_count=0,
                blocked_event_count=0,
                declassification_completeness=1.0,
            ),
        )
        # build knowledge_state from initial_knowledge
        for ak in fixture.initial_knowledge:
            self._state.knowledge_state[ak.character_id] = _ActorState(
                character_id=ak.character_id,
                known_info_ids=set(ak.known_info_ids),
                observed_info_ids=set(ak.observed_info_ids),
                authorized_info_ids=set(ak.authorized_info_ids),
            )
        # pre-seed committed events from fixture commit_records
        self._preseed_committed()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit_action(
        self,
        action_text: str,
        actor: str,
        scene_id: str,
        visibility: Visibility | None = None,
        manual_overrides: ManualOverrides | None = None,
    ) -> AuditResult:
        """Parse *action_text*, run the three-layer check, update state."""
        if visibility is None:
            visibility = self._state.config.default_visibility

        parse_result = self._adapter.parse_action(
            action_text=action_text,
            actor=actor,
            scene_id=scene_id,
            committed_event_ids=self._state.committed_event_ids,
        )

        if parse_result.resolution == "unresolved":
            if manual_overrides is not None and parse_result.event_record is not None:
                event = self._adapter.resolve_manual(
                    parse_result.event_record, manual_overrides
                )
                parse_result = parse_result.model_copy(
                    update={
                        "resolution": "manual",
                        "event_record": event,
                    }
                )
            elif manual_overrides is not None:
                # Build a minimal draft event from overrides
                draft = self._draft_from_overrides(
                    action_text, actor, scene_id, visibility, manual_overrides
                )
                event = self._adapter.resolve_manual(draft, manual_overrides)
                parse_result = parse_result.model_copy(
                    update={
                        "resolution": "manual",
                        "event_record": event,
                    }
                )
            else:
                return AuditResult(allowed=False, resolution="unresolved")

        event = parse_result.event_record
        assert event is not None  # for mypy — event is always set by now

        # --- Schedule / Filter / Coupling incremental checks ---
        violations, warnings = self._three_layer_check(event, actor)

        # --- Mark as committed ---
        self._state.event_counter += 1
        event.committed = True
        event.status = "committed"
        event.commit_index = self._state.event_counter
        self._state.committed_event_ids.add(event.id)
        self._state.event_log.append(event)

        # --- Update knowledge state ---
        actor_state = self._get_or_create_actor(actor)
        for info_id in event.output_info_ids:
            info = self._info_lookup.get(info_id)
            if info is None:
                continue
            if info.kind == "know":
                actor_state.known_info_ids.add(info_id)
            elif info.kind == "obs":
                actor_state.observed_info_ids.add(info_id)
            actor_state.authorized_info_ids.add(info_id)
            actor_state.acquired.append(
                KnowledgeItem(
                    info_id=info_id,
                    kind=info.kind,
                    sensitivity=info.sensitivity,
                    content_summary=(
                        info.public_payload or info.payload[:80]
                    ),
                    source_event_id=event.id,
                    source_scene_id=scene_id,
                    acquired_at_minute=event.time_end_minute,
                )
            )

        # --- Update metrics ---
        self._update_metrics(event, violations)
        self._state.violations.extend(violations)

        return AuditResult(
            allowed=True,
            resolution=parse_result.resolution,
            event_record=event,
            violations=list(violations),
            warnings=list(warnings),
            updated_metrics=MetricSummary.model_validate(self._state.metrics),
            matched_clue_id=parse_result.matched_clue_id,
        )

    def get_current_metrics(self) -> MetricSummary:
        return MetricSummary.model_validate(self._state.metrics)

    def get_knowledge_summary(self, character_id: str) -> list[KnowledgeItem]:
        actor = self._state.knowledge_state.get(character_id)
        if actor is None:
            return []
        return list(actor.acquired)

    def get_scene_timeline(self, scene_id: str) -> list[EventRecord]:
        return [e for e in self._state.event_log if e.scene_id == scene_id]

    def get_session_summary(self) -> SessionSummary:
        total_overridden = sum(
            1
            for e in self._state.event_log
            if e.status == "committed" and e.commit_index is not None
            # overridden detection: events with causal violations that got committed
        )
        return SessionSummary(
            fixture_id=self._fixture.id,
            fixture_title=self._fixture.title,
            started_at=self._state.config.started_at,
            total_events=len(self._state.event_log),
            total_committed=sum(
                1 for e in self._state.event_log if e.status == "committed"
            ),
            total_overridden=total_overridden,
        )

    def save_state(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fixture_id": self._fixture.id,
            "committed_event_ids": sorted(self._state.committed_event_ids),
            "knowledge_state": {
                cid: {
                    "character_id": a.character_id,
                    "known_info_ids": sorted(a.known_info_ids),
                    "observed_info_ids": sorted(a.observed_info_ids),
                    "authorized_info_ids": sorted(a.authorized_info_ids),
                    "acquired": [item.model_dump() for item in a.acquired],
                }
                for cid, a in self._state.knowledge_state.items()
            },
            "event_log": [e.model_dump(mode="json") for e in self._state.event_log],
            "violations": [v.model_dump(mode="json") for v in self._state.violations],
            "metrics": self._state.metrics.model_dump(),
            "config": self._state.config.model_dump(),
            "event_counter": self._state.event_counter,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_state(self, path: Path) -> None:
        payload = json.loads(path.read_text(encoding="utf-8"))
        self._state.committed_event_ids = set(payload.get("committed_event_ids", []))
        self._state.knowledge_state = {}
        for cid, data in payload.get("knowledge_state", {}).items():
            self._state.knowledge_state[cid] = _ActorState(
                character_id=data["character_id"],
                known_info_ids=set(data.get("known_info_ids", [])),
                observed_info_ids=set(data.get("observed_info_ids", [])),
                authorized_info_ids=set(data.get("authorized_info_ids", [])),
                acquired=[
                    KnowledgeItem.model_validate(item)
                    for item in data.get("acquired", [])
                ],
            )
        self._state.event_log = [
            EventRecord.model_validate(e) for e in payload.get("event_log", [])
        ]
        self._state.violations = [
            AuditEntry.model_validate(v) for v in payload.get("violations", [])
        ]
        self._state.metrics = MetricSummary.model_validate(
            payload.get("metrics", {})
        )
        self._state.config = SessionConfig.model_validate(
            payload.get("config", {})
        )
        self._state.event_counter = payload.get("event_counter", 0)

    def get_barrier_states(self) -> list[BarrierState]:
        committed = self._state.committed_event_ids
        result: list[BarrierState] = []
        committed_info: set[str] = set()
        for actor in self._state.knowledge_state.values():
            committed_info |= actor.known_info_ids | actor.observed_info_ids
            committed_info |= actor.authorized_info_ids

        for barrier in self._fixture.barriers:
            satisfied_events = [
                eid for eid in barrier.required_event_ids if eid in committed
            ]
            satisfied_infos = [
                iid for iid in barrier.required_info_ids if iid in committed_info
            ]
            all_events_ok = len(satisfied_events) == len(barrier.required_event_ids)
            all_infos_ok = len(satisfied_infos) == len(barrier.required_info_ids)
            status: CommitStatus = (
                "committed" if all_events_ok and all_infos_ok else "proposed"
            )
            result.append(
                BarrierState(
                    barrier_id=barrier.id,
                    status=(
                        "satisfied"
                        if status == "committed"
                        else "waiting"
                    ),
                    required_event_ids=list(barrier.required_event_ids),
                    satisfied_event_ids=satisfied_events,
                    required_info_ids=list(barrier.required_info_ids),
                    satisfied_info_ids=satisfied_infos,
                )
            )
        return result

    def get_coupling_states(self) -> list[CouplingState]:
        committed = self._state.committed_event_ids
        result: list[CouplingState] = []
        for coupling in self._fixture.couplings:
            all_inputs_committed = all(
                eid in committed for eid in coupling.input_event_ids
            )
            # compute drift: difference in time between committed input events
            drift = 0
            if all_inputs_committed:
                committed_times = [
                    e.time_end_minute
                    for e in self._state.event_log
                    if e.id in coupling.input_event_ids
                ]
                if committed_times:
                    actual_end = max(committed_times)
                    drift = abs(actual_end - coupling.expected_drift_minutes)
            result.append(
                CouplingState(
                    coupling_id=coupling.id,
                    source_scene_id=coupling.source_scene_id,
                    target_scene_id=coupling.target_scene_id,
                    mode=coupling.mode,
                    drift_minutes=drift,
                    active=all_inputs_committed,
                )
            )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _info_lookup(self) -> dict[str, InfoLabel]:
        if not hasattr(self, "_info_lut"):
            self._info_lut: dict[str, InfoLabel] = {
                info.id: info for info in self._fixture.info_labels
            }
        return self._info_lut

    def _get_or_create_actor(self, actor: str) -> _ActorState:
        if actor not in self._state.knowledge_state:
            self._state.knowledge_state[actor] = _ActorState(character_id=actor)
        return self._state.knowledge_state[actor]

    def _three_layer_check(
        self, event: EventRecord, actor: str
    ) -> tuple[list[AuditEntry], list[str]]:
        violations: list[AuditEntry] = []
        warnings: list[str] = []

        # --- Schedule check ---
        missing_events = [
            eid
            for eid in event.depends_on_event_ids
            if eid not in self._state.committed_event_ids
        ]
        actor_state = self._state.knowledge_state.get(actor)
        known: set[str] = set()
        if actor_state is not None:
            known = actor_state.known_info_ids | actor_state.observed_info_ids
        missing_info = [
            iid for iid in event.required_info_ids if iid not in known
        ]
        if missing_events or missing_info:
            violations.append(
                AuditEntry(
                    id=f"audit_causal_{event.id}",
                    metric="causal_violation",
                    run_mode="ktsl_full",
                    scene_id=event.scene_id,
                    event_id=event.id,
                    severity="error",
                    message=(
                        f"Causal violation: missing events={missing_events}, "
                        f"missing info={missing_info}"
                    ),
                    caused_by_event_ids=missing_events,
                    caused_by_info_ids=missing_info,
                )
            )

        # --- Filter check ---
        for info_id in event.output_info_ids:
            info = self._info_lookup.get(info_id)
            if info is None:
                continue
            if info.sensitivity == "public":
                continue
            if info.sensitivity == "keeper":
                violations.append(
                    AuditEntry(
                        id=f"audit_unauth_{event.id}_{info.id}",
                        metric="unauthorized_action",
                        run_mode="ktsl_full",
                        scene_id=event.scene_id,
                        event_id=event.id,
                        info_id=info.id,
                        character_id=actor,
                        severity="error",
                        message=(
                            f"Keeper-level info {info.id} exposed to {actor}"
                        ),
                        caused_by_info_ids=[info.id],
                    )
                )
                continue
            # low / medium / high sensitivity
            if info.sensitivity in SENSITIVE_LEVELS:
                decision = decide_info_access(
                    info=info,
                    event=event,
                    character_id=actor,
                    player_id=actor,
                    state=actor_state if isinstance(actor_state, ActorKnowledgeState | None) else None,
                    run_mode="ktsl_full",
                )
                if decision.status in {"blocked", "redacted"}:
                    violations.append(
                        AuditEntry(
                            id=f"audit_unauth_{event.id}_{info.id}",
                            metric="unauthorized_action",
                            run_mode="ktsl_full",
                            scene_id=event.scene_id,
                            event_id=event.id,
                            info_id=info.id,
                            character_id=actor,
                            severity="warning",
                            message=(
                                f"Unauthorized access to {info.id} "
                                f"(sensitivity={info.sensitivity}) by {actor}"
                            ),
                            caused_by_info_ids=[info.id],
                        )
                    )

        # --- Coupling check ---
        for coupling in self._fixture.couplings:
            if event.scene_id not in (
                coupling.source_scene_id,
                coupling.target_scene_id,
            ):
                continue
            # if any input event was just committed, check drift
            if (
                event.id in coupling.input_event_ids
                and coupling.expected_drift_minutes > 0
            ):
                drift = abs(
                    event.time_end_minute - coupling.expected_drift_minutes
                )
                if drift > coupling.expected_drift_minutes:
                    warnings.append(
                        f"Coupling {coupling.id}: drift {drift}min "
                        f"> expected {coupling.expected_drift_minutes}min"
                    )
                    violations.append(
                        AuditEntry(
                            id=f"audit_drift_{event.id}_{coupling.id}",
                            metric="coupling_drift",
                            run_mode="ktsl_full",
                            scene_id=event.scene_id,
                            event_id=event.id,
                            severity="warning",
                            message=(
                                f"Coupling {coupling.id}: time drift "
                                f"{drift}min exceeds threshold "
                                f"{coupling.expected_drift_minutes}min"
                            ),
                        )
                    )

        return violations, warnings

    def _update_metrics(
        self, event: EventRecord, violations: list[AuditEntry]
    ) -> None:
        metrics = self._state.metrics
        metrics.committed_event_count = (
            (metrics.committed_event_count or 0) + 1
        )
        for v in violations:
            if v.metric == "causal_violation":
                metrics.causal_violation_count = (
                    metrics.causal_violation_count or 0
                ) + 1
            elif v.metric == "unauthorized_action":
                metrics.unauthorized_action_count = (
                    metrics.unauthorized_action_count or 0
                ) + 1
            elif v.metric == "public_payload_leak":
                metrics.public_payload_leak_count = (
                    metrics.public_payload_leak_count or 0
                ) + 1
            elif v.metric == "retcon":
                metrics.retcon_count = (metrics.retcon_count or 0) + 1
            elif v.metric == "coupling_drift":
                metrics.high_coupling_time_drift_minutes = max(
                    metrics.high_coupling_time_drift_minutes or 0,
                    1,  # at least one drift increment
                )

    def _draft_from_overrides(
        self,
        action_text: str,
        actor: str,
        scene_id: str,
        visibility: Visibility,
        overrides: ManualOverrides,
    ) -> EventRecord:
        """Construct a draft EventRecord purely from manual overrides."""
        return EventRecord(
            id=f"manual_{actor}_{scene_id}_{self._state.event_counter}",
            scene_id=scene_id,
            action_id="manual_action",
            action_text=action_text[:200],
            actor=actor,
            character_id=actor,
            visibility=visibility,
            status="proposed",
            barrier_id=overrides.barrier_id,
            required_info_ids=list(overrides.required_info_ids),
            output_info_ids=list(overrides.output_info_ids),
            causal_dependency_ids=list(overrides.causal_dependency_ids),
            depends_on_event_ids=list(overrides.depends_on_event_ids),
        )

    def _preseed_committed(self) -> None:
        """Mark fixture-defined 'committed' events as already committed.

        This lets the tracker know about pre-existing causal prerequisites
        (e.g. library decoded index → sewer trace sigil).
        """
        for event in self._fixture.events:
            if event.committed and event.status == "committed":
                self._state.committed_event_ids.add(event.id)
