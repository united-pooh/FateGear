from __future__ import annotations

from scenario.module import ModuleEffect
from scenario.story import (
    StorySignal,
    StoryStage,
    StoryState,
    StoryStateService,
    StoryTransition,
    TransitionValidator,
)


def test_transition_validator_prefers_matching_transition_with_higher_priority() -> (
    None
):
    validator = TransitionValidator()
    story_state = StoryState(current_stage_id="investigation")
    stages = {
        "investigation": StoryStage(id="investigation", name="调查中"),
        "good_end": StoryStage(id="good_end", name="好结局"),
        "bad_end": StoryStage(id="bad_end", name="坏结局"),
    }
    transitions = [
        StoryTransition(
            id="to_good_end",
            source_stage_id="investigation",
            target_stage_id="good_end",
            trigger_type="action_succeeded",
            trigger_value="inspect_console",
            priority=20,
        ),
        StoryTransition(
            id="to_bad_end",
            source_stage_id="investigation",
            target_stage_id="bad_end",
            trigger_type="action_succeeded",
            trigger_value="inspect_console",
            priority=10,
        ),
    ]
    signals = [
        StorySignal(
            type="action_succeeded",
            turn_no=3,
            player_id="p1",
            scene_id="control",
            action_id="inspect_console",
        )
    ]

    transition = validator.can_transition(
        story_state=story_state,
        stages=stages,
        transitions=transitions,
        signals=signals,
        flags=set(),
    )

    assert transition is not None
    assert transition.id == "to_bad_end"


def test_transition_validator_can_unlock_target_stage_with_transition_effects() -> None:
    validator = TransitionValidator()
    story_state = StoryState(current_stage_id="setup")
    stages = {
        "setup": StoryStage(id="setup", name="准备阶段"),
        "access_opened": StoryStage(
            id="access_opened",
            name="通路开启",
            required_flags=["door_opened"],
        ),
    }
    transition = StoryTransition(
        id="unlock_access",
        source_stage_id="setup",
        target_stage_id="access_opened",
        trigger_type="action_succeeded",
        trigger_value="unlock_door",
        required_flags=["key_found"],
        effects=[
            ModuleEffect(type="set_flag", flag="door_opened"),
        ],
    )
    signals = [
        StorySignal(
            type="action_succeeded",
            turn_no=2,
            player_id="p1",
            scene_id="storage",
            action_id="unlock_door",
        )
    ]

    matched = validator.can_transition(
        story_state=story_state,
        stages=stages,
        transitions=[transition],
        signals=signals,
        flags={"key_found"},
    )

    assert matched is not None
    assert matched.id == "unlock_access"


def test_transition_validator_requires_declared_clue_coverage_when_provided() -> None:
    validator = TransitionValidator()
    story_state = StoryState(current_stage_id="investigation")
    stages = {
        "investigation": StoryStage(id="investigation", name="调查中"),
        "ritual_route": StoryStage(
            id="ritual_route",
            name="仪式路线",
            available_clues=["archive_index"],
        ),
    }
    transition = StoryTransition(
        id="to_ritual_route",
        source_stage_id="investigation",
        target_stage_id="ritual_route",
        trigger_type="action_succeeded",
        trigger_value="inspect_archive",
    )
    signals = [
        StorySignal(
            type="action_succeeded",
            turn_no=2,
            player_id="p1",
            scene_id="library",
            action_id="inspect_archive",
        )
    ]

    blocked = validator.can_transition(
        story_state=story_state,
        stages=stages,
        transitions=[transition],
        signals=signals,
        flags=set(),
        covered_clue_ids=set(),
    )
    matched = validator.can_transition(
        story_state=story_state,
        stages=stages,
        transitions=[transition],
        signals=signals,
        flags=set(),
        covered_clue_ids={"archive_index"},
    )

    assert blocked is None
    assert matched is not None
    assert matched.id == "to_ritual_route"


def test_story_state_service_marks_terminal_stage_as_resolved_ending() -> None:
    service = StoryStateService()
    story_state = StoryState(current_stage_id="breakthrough", stage_entered_turn=4)
    stages = {
        "breakthrough": StoryStage(id="breakthrough", name="突破障碍"),
        "true_end": StoryStage(
            id="true_end",
            name="真结局",
            is_terminal=True,
            terminal_type="success",
        ),
    }
    transition = StoryTransition(
        id="reach_true_end",
        source_stage_id="breakthrough",
        target_stage_id="true_end",
        trigger_type="action_succeeded",
        trigger_value="accelerate_train",
    )

    new_state = service.apply_transition(
        story_state=story_state,
        transition=transition,
        stages=stages,
        turn_no=5,
    )

    assert new_state.current_stage_id == "true_end"
    assert new_state.stage_entered_turn == 5
    assert new_state.resolved_ending_id == "true_end"
