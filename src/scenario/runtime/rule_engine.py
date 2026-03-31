"""运行时规则引擎。

负责动作可执行性、检定、flag/clock 效果应用和时钟阈值触发。
不负责会话生命周期、批次编排、事件日志或剧情迁移。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from random import randint

from cards.domain.card import InvestigatorCard

from ..agent.models import ProposedCheck
from ..module.models import ModuleAction, ModuleActionCheck, ModuleDefinition
from ..module.types import ModuleCondition, ModuleEffect
from ..session.state import SessionMapState, SessionPlayerState

RollProvider = Callable[[], int]


class RuleEngine:
    """场景运行时的规则与效果执行组件。"""

    def __init__(self, *, roll_provider: RollProvider | None = None) -> None:
        self._roll_provider = roll_provider or (lambda: randint(1, 100))

    def can_execute_action(
        self,
        *,
        action: ModuleAction,
        session: SessionMapState,
        player_id: str,
    ) -> tuple[bool, str]:
        """判断动作在当前会话快照中是否可执行，并返回失败原因。"""
        player_state = session.player_states[player_id]
        if action.scene_id != player_state.current_scene_id:
            return False, "动作不在玩家当前场景中"
        if (
            action.required_stages
            and session.story_state.current_stage_id not in action.required_stages
        ):
            return False, "当前剧情阶段不允许执行该动作"
        if action.once and action.id in session.completed_actions:
            return False, "该动作在本会话中已经执行过"
        if not self._conditions_met(action.conditions, session):
            return False, "动作前置条件未满足"
        return True, ""

    def resolve_action_check(
        self,
        *,
        action: ModuleAction,
        player_state: SessionPlayerState,
        flag_sets: set[str],
        flag_clears: set[str],
        clock_deltas: dict[str, int],
    ) -> tuple[bool, str, list[str]]:
        """执行动作检定并返回成功标记、失败原因和失败效果摘要。"""
        check = action.check
        if check is None:
            return True, "", []

        skill = player_state.investigator.skills.get(check.skill_key)
        failure_effects = self.queue_effects(
            action.effects_on_failure,
            flag_sets=flag_sets,
            flag_clears=flag_clears,
            clock_deltas=clock_deltas,
        )
        if skill is None:
            return False, f"缺少技能 {check.skill_key}", failure_effects

        roll = self._next_roll()
        threshold = self._difficulty_threshold(skill.value, check)
        if roll <= threshold:
            return True, "", []
        return False, check.failure_reason, failure_effects

    def queue_effects(
        self,
        effects: list[ModuleEffect],
        *,
        flag_sets: set[str],
        flag_clears: set[str],
        clock_deltas: dict[str, int],
    ) -> list[str]:
        """把效果累加到暂存容器，不直接写回会话。"""
        effect_summaries: list[str] = []
        for effect in effects:
            if effect.type == "set_flag":
                flag_sets.add(effect.flag)
                effect_summaries.append(f"设置标记:{effect.flag}")
            elif effect.type == "clear_flag":
                flag_clears.add(effect.flag)
                effect_summaries.append(f"移除标记:{effect.flag}")
            elif effect.type == "advance_clock":
                clock_deltas[effect.clock_id] += effect.value
                effect_summaries.append(f"推进时钟:{effect.clock_id}+={effect.value}")
        return effect_summaries

    def apply_flag_changes(
        self,
        session: SessionMapState,
        *,
        flag_sets: set[str],
        flag_clears: set[str],
    ) -> None:
        """把暂存的标记增删写回会话。"""
        for flag in flag_clears:
            session.global_flags.discard(flag)
        for flag in flag_sets:
            session.global_flags.add(flag)

    def apply_clock_deltas(
        self,
        session: SessionMapState,
        *,
        module: ModuleDefinition,
        deltas: dict[str, int],
    ) -> None:
        """把时钟增量写回会话，并受模组时钟上限约束。"""
        for clock in module.clocks:
            delta = deltas.get(clock.id, 0)
            if delta == 0:
                continue
            current_value = session.clock_values.get(clock.id, clock.start)
            session.clock_values[clock.id] = min(clock.max_value, current_value + delta)

    def trigger_clock_events(
        self,
        session: SessionMapState,
        module: ModuleDefinition,
    ) -> list[str]:
        """触发达到阈值且尚未触发过的时钟事件。"""
        triggered: list[str] = []
        changed = True
        while changed:
            changed = False
            for clock in module.clocks:
                current_value = session.clock_values.get(clock.id, clock.start)
                for threshold in clock.threshold_events:
                    trigger_id = f"{clock.id}:{threshold.value}"
                    if trigger_id in session.triggered_clock_events:
                        continue
                    if current_value < threshold.value:
                        continue
                    self._apply_effects_directly(
                        session=session,
                        module=module,
                        effects=threshold.effects,
                    )
                    session.triggered_clock_events.add(trigger_id)
                    triggered.append(trigger_id)
                    changed = True
        return triggered

    def resolve_proposed_check(
        self,
        *,
        proposed: ProposedCheck,
        player_state: SessionPlayerState,
    ) -> dict:
        """执行 Agent 提议的动态检定，返回标准检定结果字典。

        返回字段：
        - player_id: str
        - action_id: str
        - skill_key: str
        - proposed_difficulty: str
        - roll_value: int
        - threshold: int
        - success: bool
        - success_level: str  ("extreme" / "hard" / "regular" / "fail")
        - rationale: str

        若玩家没有对应技能，``success`` 为 False，``roll_value`` 为 0。
        """
        skill = player_state.investigator.skills.get(proposed.skill_key)
        if skill is None:
            return {
                "player_id": proposed.player_id,
                "action_id": proposed.action_id,
                "skill_key": proposed.skill_key,
                "proposed_difficulty": proposed.proposed_difficulty,
                "roll_value": 0,
                "threshold": 0,
                "success": False,
                "success_level": "fail",
                "rationale": proposed.rationale,
                "note": f"缺少技能 {proposed.skill_key}",
            }
        roll = self._next_roll()
        sv = skill.value
        if roll <= sv // 5:
            level = "extreme"
            success = True
        elif roll <= sv // 2:
            level = "hard"
            success = True
        elif roll <= sv:
            level = "regular"
            success = True
        else:
            level = "fail"
            success = False
        # proposed_difficulty 用于叙事参考，不改变实际阈值
        return {
            "player_id": proposed.player_id,
            "action_id": proposed.action_id,
            "skill_key": proposed.skill_key,
            "proposed_difficulty": proposed.proposed_difficulty,
            "roll_value": roll,
            "threshold": sv,
            "success": success,
            "success_level": level,
            "rationale": proposed.rationale,
        }

    def clone_card(self, investigator: InvestigatorCard) -> InvestigatorCard:
        """复制人物卡，隔离会话内状态与外部引用。"""
        return investigator.model_copy(deep=True)

    def _conditions_met(
        self,
        conditions: list[ModuleCondition],
        session: SessionMapState,
    ) -> bool:
        for condition in conditions:
            if (
                condition.type == "flag_set"
                and condition.flag not in session.global_flags
            ):
                return False
            if (
                condition.type == "flag_unset"
                and condition.flag in session.global_flags
            ):
                return False
            if (
                condition.type == "action_completed"
                and condition.action_id not in session.completed_actions
            ):
                return False
            if (
                condition.type == "clock_at_least"
                and session.clock_values.get(condition.clock_id, 0) < condition.value
            ):
                return False
        return True

    def _difficulty_threshold(
        self,
        skill_value: int,
        check: ModuleActionCheck,
    ) -> int:
        if check.difficulty == "regular":
            return skill_value
        if check.difficulty == "hard":
            return skill_value // 2
        return skill_value // 5

    def _next_roll(self) -> int:
        rolled = self._roll_provider()
        if rolled < 1 or rolled > 100:
            raise ValueError(f"检定结果必须在 1..100 之间，收到: {rolled}")
        return rolled

    def _apply_effects_directly(
        self,
        *,
        session: SessionMapState,
        module: ModuleDefinition,
        effects: list[ModuleEffect],
    ) -> None:
        flag_sets: set[str] = set()
        flag_clears: set[str] = set()
        clock_deltas: dict[str, int] = defaultdict(int)
        self.queue_effects(
            effects,
            flag_sets=flag_sets,
            flag_clears=flag_clears,
            clock_deltas=clock_deltas,
        )
        self.apply_flag_changes(
            session,
            flag_sets=flag_sets,
            flag_clears=flag_clears,
        )
        self.apply_clock_deltas(
            session,
            module=module,
            deltas=clock_deltas,
        )
