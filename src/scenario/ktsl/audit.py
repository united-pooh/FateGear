"""Audit and metric aggregation for deterministic KTSL runs."""

from __future__ import annotations

from hashlib import sha1

from .coupling import HIGH_COUPLING_THRESHOLD
from .filter import declassification_completeness
from .models import (
    AuditEntry,
    CouplingDecision,
    EventRecord,
    FilterDecision,
    KTSLFixture,
    MetricSummary,
    RunMode,
    ScheduleStep,
)


def audit_fixture(
    fixture: KTSLFixture,
    run_mode: RunMode,
    schedule_steps: list[ScheduleStep],
    filter_decisions: list[FilterDecision],
    coupling_decisions: list[CouplingDecision],
) -> tuple[list[AuditEntry], MetricSummary]:
    """Build audit entries and a metric summary for one deterministic run."""

    entries = build_audit_entries(
        fixture=fixture,
        run_mode=run_mode,
        schedule_steps=schedule_steps,
        filter_decisions=filter_decisions,
        coupling_decisions=coupling_decisions,
    )
    return entries, summarize_metrics(
        fixture=fixture,
        run_mode=run_mode,
        schedule_steps=schedule_steps,
        filter_decisions=filter_decisions,
        coupling_decisions=coupling_decisions,
        audit_entries=entries,
    )


def build_audit_entries(
    *,
    fixture: KTSLFixture,
    run_mode: RunMode,
    schedule_steps: list[ScheduleStep],
    filter_decisions: list[FilterDecision],
    coupling_decisions: list[CouplingDecision],
) -> list[AuditEntry]:
    """Return deterministic audit entries from the three KTSL layers."""

    event_lookup = {event.id: event for event in fixture.events}
    entries: list[AuditEntry] = []
    entries.extend(_schedule_entries(run_mode, schedule_steps, event_lookup))
    entries.extend(_filter_entries(run_mode, filter_decisions, event_lookup))
    entries.extend(_coupling_entries(run_mode, coupling_decisions))
    return entries


def summarize_metrics(
    *,
    fixture: KTSLFixture,
    run_mode: RunMode,
    schedule_steps: list[ScheduleStep],
    filter_decisions: list[FilterDecision],
    coupling_decisions: list[CouplingDecision],
    audit_entries: list[AuditEntry] | None = None,
) -> MetricSummary:
    """Summarize audit metrics using settleable events as the counting unit."""

    event_lookup = {event.id: event for event in fixture.events}
    settleable_event_ids = {
        event.id for event in fixture.events if event.is_settleable
    }
    if audit_entries is None:
        audit_entries = build_audit_entries(
            fixture=fixture,
            run_mode=run_mode,
            schedule_steps=schedule_steps,
            filter_decisions=filter_decisions,
            coupling_decisions=coupling_decisions,
        )

    causal_event_ids = {
        entry.event_id
        for entry in audit_entries
        if entry.metric == "causal_violation" and entry.event_id in settleable_event_ids
    }
    unauthorized_event_ids = {
        entry.event_id
        for entry in audit_entries
        if entry.metric == "unauthorized_action" and entry.event_id in settleable_event_ids
    }
    leak_event_ids = {
        entry.event_id
        for entry in audit_entries
        if entry.metric == "public_payload_leak" and entry.event_id in settleable_event_ids
    }
    retcon_event_ids = {
        entry.event_id
        for entry in audit_entries
        if entry.metric == "retcon" and entry.event_id in settleable_event_ids
    }
    committed_steps = [
        step
        for step in schedule_steps
        if step.status == "committed" and _is_settleable(step.event_id, event_lookup)
    ]
    blocked_steps = [
        step
        for step in schedule_steps
        if step.status == "blocked" and _is_settleable(step.event_id, event_lookup)
    ]

    return MetricSummary(
        causal_violation_count=len(causal_event_ids),
        unauthorized_action_count=len(unauthorized_event_ids),
        public_payload_leak_count=len(leak_event_ids),
        spotlight_max_gap_minutes=_spotlight_max_gap(committed_steps),
        declassification_completeness=declassification_completeness(
            fixture, run_mode, filter_decisions
        ),
        retcon_count=len(retcon_event_ids),
        high_coupling_time_drift_minutes=sum(
            decision.drift_minutes
            for decision in coupling_decisions
            if decision.coupling_score >= HIGH_COUPLING_THRESHOLD
        ),
        barrier_wait_minutes=sum(step.wait_cost_minutes for step in schedule_steps),
        committed_event_count=len(committed_steps),
        blocked_event_count=len(blocked_steps),
    )


def _schedule_entries(
    run_mode: RunMode,
    schedule_steps: list[ScheduleStep],
    event_lookup: dict[str, EventRecord],
) -> list[AuditEntry]:
    entries: list[AuditEntry] = []
    commit_index = {
        step.event_id: step.commit_index
        for step in schedule_steps
        if step.commit_index is not None and step.status == "committed"
    }
    end_minutes = {
        step.event_id: step.time_end_minute
        for step in schedule_steps
        if step.status == "committed"
    }

    for step in schedule_steps:
        event = event_lookup.get(step.event_id)
        if event is None or not event.is_settleable:
            continue
        missing_event_ids = list(step.missing_event_ids)
        missing_info_ids = list(step.missing_info_ids)
        late_event_ids = [
            event_id
            for event_id in step.depends_on_event_ids
            if event_id in commit_index
            and step.commit_index is not None
            and commit_index[event_id] > step.commit_index
        ]
        overlapping_event_ids = [
            event_id
            for event_id in step.depends_on_event_ids
            if run_mode == "baseline"
            and event_id in end_minutes
            and end_minutes[event_id] > step.time_start_minute
        ]
        if step.status == "committed" and (
            missing_event_ids or missing_info_ids or late_event_ids or overlapping_event_ids
        ):
            caused_by_event_ids = list(
                dict.fromkeys(missing_event_ids + late_event_ids + overlapping_event_ids)
            )
            entries.append(
                AuditEntry(
                    id=_entry_id("causal", step.event_id, run_mode),
                    metric="causal_violation",
                    run_mode=run_mode,
                    scene_id=step.scene_id,
                    event_id=step.event_id,
                    severity="error",
                    message="Committed event has unmet or late causal dependencies.",
                    caused_by_event_ids=caused_by_event_ids,
                    caused_by_info_ids=missing_info_ids,
                )
            )
        if event.status == "retconned" or step.status == "retconned":
            entries.append(
                AuditEntry(
                    id=_entry_id("retcon", step.event_id, run_mode),
                    metric="retcon",
                    run_mode=run_mode,
                    scene_id=step.scene_id,
                    event_id=step.event_id,
                    severity="warning",
                    message="Settleable event was marked retconned.",
                )
            )
    return entries


def _filter_entries(
    run_mode: RunMode,
    filter_decisions: list[FilterDecision],
    event_lookup: dict[str, EventRecord],
) -> list[AuditEntry]:
    entries: list[AuditEntry] = []
    unauthorized_seen: set[str] = set()
    leak_seen: set[str] = set()

    for decision in filter_decisions:
        event = event_lookup.get(decision.event_id)
        if event is None or not event.is_settleable:
            continue
        is_actor_decision = decision.character_id == event.character_id
        if (
            is_actor_decision
            and not decision.authorized
            and not decision.declassified
            and decision.status in {"blocked", "redacted"}
            and decision.event_id not in unauthorized_seen
        ):
            unauthorized_seen.add(decision.event_id)
            entries.append(
                AuditEntry(
                    id=_entry_id("unauth", decision.event_id, run_mode),
                    metric="unauthorized_action",
                    run_mode=run_mode,
                    scene_id=event.scene_id,
                    event_id=decision.event_id,
                    info_id=decision.info_id,
                    player_id=decision.player_id,
                    character_id=decision.character_id,
                    severity="error",
                    message="Settleable action referenced unauthorized sensitive information.",
                    caused_by_info_ids=[decision.info_id],
                )
            )
        if decision.leaked_public_payload and decision.event_id not in leak_seen:
            leak_seen.add(decision.event_id)
            entries.append(
                AuditEntry(
                    id=_entry_id("leak", decision.event_id, run_mode),
                    metric="public_payload_leak",
                    run_mode=run_mode,
                    scene_id=event.scene_id,
                    event_id=decision.event_id,
                    info_id=decision.info_id,
                    player_id=decision.player_id,
                    character_id=decision.character_id,
                    severity="error",
                    message="Unauthorized sensitive public payload was exposed.",
                    caused_by_info_ids=[decision.info_id],
                )
            )
    return entries


def _coupling_entries(
    run_mode: RunMode, coupling_decisions: list[CouplingDecision]
) -> list[AuditEntry]:
    entries: list[AuditEntry] = []
    for decision in coupling_decisions:
        if (
            decision.coupling_score >= HIGH_COUPLING_THRESHOLD
            and decision.drift_minutes > 0
        ):
            entries.append(
                AuditEntry(
                    id=_entry_id("drift", decision.coupling_id, run_mode),
                    metric="coupling_drift",
                    run_mode=run_mode,
                    severity="warning" if decision.status == "blocked" else "info",
                    message=(
                        "High coupling time drift measured at "
                        f"{decision.drift_minutes} minutes."
                    ),
                    caused_by_event_ids=decision.input_event_ids,
                    caused_by_info_ids=decision.required_info_ids,
                )
            )
    return entries


def _spotlight_max_gap(committed_steps: list[ScheduleStep]) -> int:
    ordered = sorted(
        committed_steps, key=lambda step: (step.spotlight_start_minute, step.event_id)
    )
    max_gap = 0
    for previous, current in zip(ordered, ordered[1:]):
        max_gap = max(
            max_gap, current.spotlight_start_minute - previous.spotlight_end_minute
        )
    return max(0, max_gap)


def _is_settleable(event_id: str, event_lookup: dict[str, EventRecord]) -> bool:
    event = event_lookup.get(event_id)
    return event is not None and event.is_settleable


def _entry_id(prefix: str, value: str, run_mode: RunMode) -> str:
    digest = sha1(f"{prefix}:{value}:{run_mode}".encode()).hexdigest()[:10]
    return f"audit_{prefix}_{digest}"


__all__ = ["audit_fixture", "build_audit_entries", "summarize_metrics"]
