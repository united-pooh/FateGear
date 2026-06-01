"""Build committed narration input packets from resolved turns."""

from __future__ import annotations

from collections.abc import Mapping

from scenario.module.models import ModuleDefinition, ModuleScene
from scenario.session.state import SessionMapState
from scenario.runtime.contracts import TurnResolution

from .contracts import (
    CheckResultFact,
    NarrativeState,
    NarrationInputPacket,
    PlayerSceneSnapshot,
    RuleFact,
    SceneSnapshot,
    StateDiff,
    StaticSceneContext,
    StorySnapshot,
)
from .events import build_event_refs


def build_narration_input_packet(
    *,
    resolution: TurnResolution,
    session: SessionMapState,
    module: ModuleDefinition,
    narrative_state: NarrativeState | None = None,
    forbidden_facts: list[str] | None = None,
    recent_record_summary: str = "",
) -> NarrationInputPacket:
    """Build a render-stage packet from already committed runtime data.

    The function reads committed snapshots only and never mutates SessionMapState,
    TurnResolution, or ModuleDefinition.
    """

    scene_by_id = module.scene_map()
    stage_by_id = module.story_stage_map()
    event_refs = build_event_refs(resolution)
    event_id_by_index = {
        event_ref.event_index: event_ref.event_id for event_ref in event_refs
    }
    story_stage = stage_by_id.get(session.story_state.current_stage_id)

    return NarrationInputPacket(
        session_id=resolution.session_id,
        turn_no=resolution.turn_no,
        module_id=module.module_id,
        module_title=module.title,
        event_refs=event_refs,
        player_scene_snapshots=[
            PlayerSceneSnapshot(
                player_id=player_id,
                current_scene_id=player_state.current_scene_id,
                current_scene_name=_scene_name(scene_by_id, player_state.current_scene_id),
                last_scene_id=player_state.last_scene_id,
            )
            for player_id, player_state in sorted(session.player_states.items())
        ],
        scene_snapshots=[
            SceneSnapshot(
                scene_id=scene_id,
                scene_name=_scene_name(scene_by_id, scene_id),
                is_cleared=scene_state.is_cleared,
                has_event_occurred=scene_state.has_event_occurred,
                completed_action_ids=sorted(scene_state.completed_action_ids),
                local_flags=sorted(scene_state.local_flags),
            )
            for scene_id, scene_state in sorted(session.scene_instances.items())
        ],
        story_snapshot=StorySnapshot(
            current_stage_id=session.story_state.current_stage_id,
            stage_name=story_stage.name if story_stage is not None else "",
            stage_description=story_stage.description if story_stage is not None else "",
            stage_entered_turn=session.story_state.stage_entered_turn,
            resolved_ending_id=session.story_state.resolved_ending_id,
        ),
        rule_facts=_build_rule_facts(resolution, session),
        state_diffs=_build_state_diffs(resolution, event_id_by_index),
        check_results=_build_check_results(resolution, event_id_by_index),
        forbidden_facts=forbidden_facts or [],
        narrative_state=narrative_state or NarrativeState(),
        recent_record_summary=recent_record_summary,
        static_scene_context=[
            StaticSceneContext(
                scene_id=scene.id,
                scene_name=scene.name,
                description=scene.description,
                tags=list(scene.tags),
            )
            for scene in module.scenes
            if scene.id in _relevant_scene_ids(resolution, session)
        ],
    )


def _build_rule_facts(
    resolution: TurnResolution,
    session: SessionMapState,
) -> list[RuleFact]:
    facts = [
        RuleFact(
            kind="turn",
            text=f"Turn {resolution.turn_no} resolved; next turn is {resolution.next_turn}.",
            data={"turn_no": resolution.turn_no, "next_turn": resolution.next_turn},
        ),
        RuleFact(
            kind="stage",
            text=f"Current story stage is {session.story_state.current_stage_id}.",
            data=session.story_state.model_dump(mode="json"),
        ),
        RuleFact(
            kind="flags",
            text=f"Committed global flags: {sorted(session.global_flags)}.",
            data={"global_flags": sorted(session.global_flags)},
        ),
        RuleFact(
            kind="clocks",
            text=f"Committed clock values: {dict(sorted(session.clock_values.items()))}.",
            data={"clock_values": dict(sorted(session.clock_values.items()))},
        ),
        RuleFact(
            kind="completed_actions",
            text=f"Completed actions: {sorted(session.completed_actions)}.",
            data={"completed_actions": sorted(session.completed_actions)},
        ),
    ]
    if resolution.resolved_ending is not None:
        facts.append(
            RuleFact(
                kind="ending",
                text=f"Resolved ending is {resolution.resolved_ending}.",
                data={
                    "resolved_ending": resolution.resolved_ending,
                    "ending_result": resolution.ending_result,
                },
            )
        )
    return facts


def _scene_name(scene_by_id: Mapping[str, ModuleScene], scene_id: str) -> str:
    scene = scene_by_id.get(scene_id)
    return scene.name if scene is not None else ""


def _relevant_scene_ids(
    resolution: TurnResolution,
    session: SessionMapState,
) -> set[str]:
    scene_ids = {
        player_state.current_scene_id
        for player_state in session.player_states.values()
    }
    for event in resolution.event_log:
        for scene_id in (
            event.scene_id,
            event.from_scene_id,
            event.to_scene_id,
        ):
            if scene_id:
                scene_ids.add(scene_id)
    return scene_ids


def _build_check_results(
    resolution: TurnResolution,
    event_id_by_index: dict[int, str],
) -> list[CheckResultFact]:
    results: list[CheckResultFact] = []
    for index, event in enumerate(resolution.event_log):
        if event.type != "action_resolved" or event.success is None:
            continue
        results.append(
            CheckResultFact(
                event_id=event_id_by_index[index],
                player_id=event.player_id,
                scene_id=event.scene_id,
                action_id=event.action_id,
                action_name=event.action_name,
                success=event.success,
                reason=event.reason,
                effects_applied=list(event.effects_applied),
            )
        )
    return results


def _build_state_diffs(
    resolution: TurnResolution,
    event_id_by_index: dict[int, str],
) -> list[StateDiff]:
    diffs: list[StateDiff] = []
    for index, event in enumerate(resolution.event_log):
        event_id = event_id_by_index[index]
        if event.type == "movement_committed":
            diffs.append(
                StateDiff(
                    kind="movement",
                    path=f"player_states.{event.player_id}.current_scene_id",
                    old_value=event.from_scene_id,
                    new_value=event.to_scene_id,
                    source_event_ids=[event_id],
                )
            )
        elif event.type == "flags_changed":
            for flag in event.added_flags:
                diffs.append(
                    StateDiff(
                        kind="flag_added",
                        path=f"global_flags.{flag}",
                        old_value=False,
                        new_value=True,
                        source_event_ids=[event_id],
                    )
                )
            for flag in event.removed_flags:
                diffs.append(
                    StateDiff(
                        kind="flag_removed",
                        path=f"global_flags.{flag}",
                        old_value=True,
                        new_value=False,
                        source_event_ids=[event_id],
                    )
                )
        elif event.type == "clocks_advanced":
            for clock_id, delta in sorted(event.clock_deltas.items()):
                diffs.append(
                    StateDiff(
                        kind="clock_delta",
                        path=f"clock_values.{clock_id}",
                        new_value=delta,
                        source_event_ids=[event_id],
                    )
                )
        elif event.type == "story_transition_applied":
            diffs.append(
                StateDiff(
                    kind="story_transition",
                    path="story_state.current_stage_id",
                    old_value=event.source_stage_id,
                    new_value=event.target_stage_id,
                    source_event_ids=[event_id],
                )
            )
        elif event.type == "ending_reached":
            diffs.append(
                StateDiff(
                    kind="ending",
                    path="resolved_ending",
                    new_value=event.ending_id,
                    source_event_ids=[event_id],
                )
            )
    return diffs
