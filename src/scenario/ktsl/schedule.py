"""Deterministic Schedule layer for KTSL fixtures."""

from __future__ import annotations

from .models import (
    BarrierCheckpoint,
    EventRecord,
    KTSLFixture,
    RunMode,
    ScheduleStep,
)


def schedule_events(fixture: KTSLFixture, run_mode: RunMode) -> list[ScheduleStep]:
    """Return deterministic commit steps for one fixture and run mode."""

    if run_mode == "baseline":
        return _baseline_steps(fixture, run_mode)
    return _gated_steps(fixture, run_mode)


def build_schedule(fixture: KTSLFixture, run_mode: RunMode) -> list[ScheduleStep]:
    """Compatibility alias for callers that name the layer directly."""

    return schedule_events(fixture, run_mode)


def _baseline_steps(fixture: KTSLFixture, run_mode: RunMode) -> list[ScheduleStep]:
    steps: list[ScheduleStep] = []
    events = sorted(
        enumerate(fixture.events),
        key=lambda item: (item[1].spotlight_start_minute, item[0], item[1].id),
    )
    for commit_index, (original_index, event) in enumerate(events):
        required_event_ids, required_info_ids = _event_requirements(fixture, event)
        steps.append(
            ScheduleStep(
                id=f"step_{run_mode}_{event.id}",
                run_mode=run_mode,
                scene_id=event.scene_id,
                event_id=event.id,
                actor=event.actor,
                status="committed" if event.is_settleable else event.status,
                commit_index=commit_index if event.is_settleable else event.commit_index,
                barrier_id=event.barrier_id,
                depends_on_event_ids=required_event_ids,
                required_info_ids=required_info_ids,
                output_info_ids=list(event.output_info_ids),
                time_start_minute=event.time_start_minute,
                time_end_minute=event.time_end_minute,
                spotlight_start_minute=event.spotlight_start_minute,
                spotlight_end_minute=event.spotlight_end_minute,
                sort_key=(event.spotlight_start_minute, event.id),
            )
        )
    return steps


def _gated_steps(fixture: KTSLFixture, run_mode: RunMode) -> list[ScheduleStep]:
    pending = sorted(
        list(enumerate(fixture.events)),
        key=lambda item: (item[1].spotlight_start_minute, item[0], item[1].id),
    )
    committed_event_ids: set[str] = set()
    committed_info_ids = _initial_info_ids(fixture)
    event_end_minutes: dict[str, int] = {}
    steps: list[ScheduleStep] = []

    while pending:
        progressed = False
        still_pending: list[tuple[int, EventRecord]] = []

        for original_index, event in pending:
            required_event_ids, required_info_ids = _event_requirements(fixture, event)
            missing_event_ids = [
                event_id
                for event_id in required_event_ids
                if event_id not in committed_event_ids
            ]
            missing_info_ids = [
                info_id for info_id in required_info_ids if info_id not in committed_info_ids
            ]
            if missing_event_ids or missing_info_ids:
                still_pending.append((original_index, event))
                continue

            wait_cost, wait_reason = _wait_cost_and_reason(
                fixture,
                event,
                required_event_ids,
                event_end_minutes,
            )
            commit_index = len([step for step in steps if step.status == "committed"])
            steps.append(
                ScheduleStep(
                    id=f"step_{run_mode}_{event.id}",
                    run_mode=run_mode,
                    scene_id=event.scene_id,
                    event_id=event.id,
                    actor=event.actor,
                    status="committed" if event.is_settleable else event.status,
                    commit_index=commit_index if event.is_settleable else event.commit_index,
                    barrier_id=event.barrier_id,
                    wait_reason=wait_reason,
                    wait_cost_minutes=wait_cost,
                    depends_on_event_ids=required_event_ids,
                    required_info_ids=required_info_ids,
                    output_info_ids=list(event.output_info_ids),
                    time_start_minute=event.time_start_minute + wait_cost,
                    time_end_minute=event.time_end_minute + wait_cost,
                    spotlight_start_minute=event.spotlight_start_minute,
                    spotlight_end_minute=event.spotlight_end_minute,
                    sort_key=(event.spotlight_start_minute, event.id),
                )
            )
            if event.is_settleable:
                committed_event_ids.add(event.id)
                committed_info_ids.update(event.output_info_ids)
                event_end_minutes[event.id] = event.time_end_minute + wait_cost
            progressed = True

        if not progressed:
            for original_index, event in still_pending:
                required_event_ids, required_info_ids = _event_requirements(fixture, event)
                missing_event_ids = [
                    event_id
                    for event_id in required_event_ids
                    if event_id not in committed_event_ids
                ]
                missing_info_ids = [
                    info_id
                    for info_id in required_info_ids
                    if info_id not in committed_info_ids
                ]
                steps.append(
                    ScheduleStep(
                        id=f"step_{run_mode}_{event.id}",
                        run_mode=run_mode,
                        scene_id=event.scene_id,
                        event_id=event.id,
                        actor=event.actor,
                        status="blocked",
                        barrier_id=event.barrier_id,
                        wait_reason=_missing_reason(missing_event_ids, missing_info_ids),
                        depends_on_event_ids=required_event_ids,
                        required_info_ids=required_info_ids,
                        output_info_ids=list(event.output_info_ids),
                        missing_event_ids=missing_event_ids,
                        missing_info_ids=missing_info_ids,
                        time_start_minute=event.time_start_minute,
                        time_end_minute=event.time_end_minute,
                        spotlight_start_minute=event.spotlight_start_minute,
                        spotlight_end_minute=event.spotlight_end_minute,
                        sort_key=(event.spotlight_start_minute, event.id),
                    )
                )
            break

        pending = still_pending

    return sorted(
        steps,
        key=lambda step: (
            step.commit_index is None,
            step.commit_index if step.commit_index is not None else 10**9,
            step.spotlight_start_minute,
            step.event_id,
        ),
    )


def _event_requirements(
    fixture: KTSLFixture, event: EventRecord
) -> tuple[list[str], list[str]]:
    required_event_ids = list(dict.fromkeys(event.depends_on_event_ids))
    required_info_ids = list(dict.fromkeys(event.required_info_ids))
    dependencies = {dependency.id: dependency for dependency in fixture.causal_dependencies}
    for dependency_id in event.causal_dependency_ids:
        dependency = dependencies.get(dependency_id)
        if dependency is None:
            continue
        required_event_ids.extend(dependency.required_event_ids)
        required_info_ids.extend(dependency.required_info_ids)
    barrier = _barrier_for_event(fixture, event)
    if barrier is not None:
        required_event_ids.extend(barrier.required_event_ids)
        required_info_ids.extend(barrier.required_info_ids)
    return list(dict.fromkeys(required_event_ids)), list(dict.fromkeys(required_info_ids))


def _barrier_for_event(
    fixture: KTSLFixture, event: EventRecord
) -> BarrierCheckpoint | None:
    if not event.barrier_id:
        return None
    return next((barrier for barrier in fixture.barriers if barrier.id == event.barrier_id), None)


def _initial_info_ids(fixture: KTSLFixture) -> set[str]:
    info_ids: set[str] = set()
    for state in fixture.initial_knowledge:
        info_ids.update(state.known_info_ids)
        info_ids.update(state.authorized_info_ids)
    return info_ids


def _wait_cost_and_reason(
    fixture: KTSLFixture,
    event: EventRecord,
    required_event_ids: list[str],
    event_end_minutes: dict[str, int],
) -> tuple[int, str]:
    latest_required_end = max(
        (event_end_minutes.get(event_id, event.time_start_minute) for event_id in required_event_ids),
        default=event.time_start_minute,
    )
    wait_cost = max(0, latest_required_end - event.time_start_minute)
    reasons: list[str] = []
    if wait_cost:
        reasons.append(f"waited_for_events:{','.join(required_event_ids)}")
    barrier = _barrier_for_event(fixture, event)
    if barrier is not None and required_event_ids:
        reasons.append(f"barrier:{barrier.id}")
    return wait_cost, ";".join(dict.fromkeys(reasons))


def _missing_reason(missing_event_ids: list[str], missing_info_ids: list[str]) -> str:
    parts: list[str] = []
    if missing_event_ids:
        parts.append(f"missing_events:{','.join(missing_event_ids)}")
    if missing_info_ids:
        parts.append(f"missing_info:{','.join(missing_info_ids)}")
    return ";".join(parts) or "blocked"


__all__ = ["build_schedule", "schedule_events"]
