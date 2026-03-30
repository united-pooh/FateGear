"""剧情状态机服务。"""

from __future__ import annotations

from .models import StorySignal, StoryStage, StoryState, StoryTransition


class TransitionValidator:
    """剧情迁移校验器。"""

    def can_transition(
        self,
        *,
        story_state: StoryState,
        stages: dict[str, StoryStage],
        transitions: list[StoryTransition],
        signals: list[StorySignal],
        flags: set[str],
    ) -> StoryTransition | None:
        candidate_transitions: list[StoryTransition] = sorted(
            (
                transition
                for transition in transitions
                if transition.source_stage_id == story_state.current_stage_id
            ),
            key=lambda item: item.priority,
        )

        for transition in candidate_transitions:
            if not self._required_flags_met(
                required_flags=transition.required_flags,
                flags=flags,
            ):
                continue
            if not any(
                self._signal_matches_transition(signal=signal, transition=transition)
                for signal in signals
            ):
                continue
            if not self._target_stage_unlocked(
                stage=stages[transition.target_stage_id],
                flags=flags,
                transition=transition,
            ):
                continue
            return transition
        return None

    def _signal_matches_transition(
        self,
        signal: StorySignal,
        transition: StoryTransition,
    ) -> bool:
        if signal.type != transition.trigger_type:
            return False
        if transition.trigger_type == "scene_entered":
            return signal.scene_id == transition.trigger_value
        if transition.trigger_type == "action_succeeded":
            return signal.action_id == transition.trigger_value
        if transition.trigger_type == "clock_threshold_triggered":
            return f"{signal.clock_id}:{signal.threshold}" == transition.trigger_value
        return False

    def _required_flags_met(
        self,
        required_flags: list[str],
        *,
        flags: set[str],
    ) -> bool:
        return all(flag in flags for flag in required_flags)

    def _target_stage_unlocked(
        self,
        stage: StoryStage,
        *,
        flags: set[str],
        transition: StoryTransition,
    ) -> bool:
        projected_flags: set[str] = set(flags)
        for effect in transition.effects:
            if effect.type == "set_flag":
                projected_flags.add(effect.flag)
            elif effect.type == "clear_flag":
                projected_flags.discard(effect.flag)
        return self._required_flags_met(stage.required_flags, flags=projected_flags)


class StoryStateService:
    """剧情状态写入服务。"""

    def apply_transition(
        self,
        *,
        story_state: StoryState,
        transition: StoryTransition,
        stages: dict[str, StoryStage],
        turn_no: int,
    ) -> StoryState:
        target_stage: StoryStage = stages[transition.target_stage_id]
        return StoryState(
            current_stage_id=transition.target_stage_id,
            stage_entered_turn=turn_no,
            resolved_ending_id=(
                transition.target_stage_id if target_stage.is_terminal else None
            ),
        )
