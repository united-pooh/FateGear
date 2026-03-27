"""基于 YAML 模组定义的最小场景运行时。"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, TypeAdapter

from scene.loader import MODULE_ROOT, load_module_by_id
from scene.map_state import SceneInstanceState, SessionMapState, SessionPlayerState
from scene.module_definition import (
    ModuleAction,
    ModuleCondition,
    ModuleDefinition,
    ModuleEffect,
    ModuleEnding,
)
from scene.movement import SceneMovementRules
from scene.scene import SceneLink


class MoveIntent(BaseModel):
    type: Literal["move"]
    target_scene_id: str = Field(..., min_length=1, max_length=30)


class ActionIntent(BaseModel):
    type: Literal["action"]
    action_id: str = Field(..., min_length=1, max_length=40)


SceneIntent = MoveIntent | ActionIntent
SCENE_INTENT_ADAPTER: TypeAdapter[SceneIntent] = TypeAdapter(SceneIntent)


class IntentResolution(BaseModel):
    player_id: str
    scene_id: str
    intent_type: str
    success: bool
    reason: str = Field(default="")
    target_scene_id: str = Field(default="")
    action_id: str = Field(default="")
    effects_applied: list[str] = Field(default_factory=list)


class SceneBatchResolution(BaseModel):
    scene_id: str
    player_ids: list[str] = Field(default_factory=list)
    outcomes: list[IntentResolution] = Field(default_factory=list)


class RuntimeEvent(BaseModel):
    type: Literal[
        "turn_started",
        "no_pending_intents",
        "scene_batch_started",
        "movement_attempted",
        "action_resolved",
        "movement_committed",
        "flags_changed",
        "clocks_advanced",
        "clock_events_triggered",
        "ending_reached",
        "turn_completed",
    ]
    message: str
    turn_no: int
    scene_id: str = Field(default="")
    scene_name: str = Field(default="")
    player_id: str = Field(default="")
    player_ids: list[str] = Field(default_factory=list)
    action_id: str = Field(default="")
    action_name: str = Field(default="")
    from_scene_id: str = Field(default="")
    from_scene_name: str = Field(default="")
    to_scene_id: str = Field(default="")
    to_scene_name: str = Field(default="")
    success: bool | None = Field(default=None)
    reason: str = Field(default="")
    effects_applied: list[str] = Field(default_factory=list)
    added_flags: list[str] = Field(default_factory=list)
    removed_flags: list[str] = Field(default_factory=list)
    clock_deltas: dict[str, int] = Field(default_factory=dict)
    triggered_clock_events: list[str] = Field(default_factory=list)
    ending_id: str = Field(default="")
    ending_result: str = Field(default="")
    clock_values: dict[str, int] = Field(default_factory=dict)

    def to_log_line(self) -> str:
        return self.message

    def __str__(self) -> str:
        return self.message


class TurnResolution(BaseModel):
    session_id: str
    turn_no: int
    next_turn: int
    scene_batches: list[SceneBatchResolution] = Field(default_factory=list)
    event_log: list[RuntimeEvent] = Field(default_factory=list)
    applied_flags: list[str] = Field(default_factory=list)
    applied_clock_deltas: dict[str, int] = Field(default_factory=dict)
    triggered_clock_events: list[str] = Field(default_factory=list)
    clock_values: dict[str, int] = Field(default_factory=dict)
    resolved_ending: str | None = Field(default=None)
    ending_result: str = Field(default="")


class SceneRuntime:
    """YAML 模组的最小运行时协调器。"""

    def __init__(self, *, module_root: str | Path | None = None) -> None:
        self._module_root = (
            Path(module_root) if module_root is not None else MODULE_ROOT
        )
        self._sessions: dict[str, SessionMapState] = {}
        self._module_cache: dict[str, ModuleDefinition] = {}

    def create_session(
        self,
        module_id: str,
        player_ids: list[str],
    ) -> SessionMapState:
        if not player_ids:
            raise ValueError("创建会话时至少需要一个 player_id")

        module = self._load_module(module_id)
        session_id = uuid4().hex[:12]
        entry_scene_id = module.entry_scene_id
        player_states = {
            player_id: SessionPlayerState(
                session_id=session_id,
                player_id=player_id,
                current_scene_id=entry_scene_id,
                last_scene_id=entry_scene_id,
            )
            for player_id in player_ids
        }
        scene_instances = {
            scene.id: SceneInstanceState(scene_id=scene.id) for scene in module.scenes
        }
        session = SessionMapState(
            session_id=session_id,
            module_id=module.module_id,
            clock_values={clock.id: clock.start for clock in module.clocks},
            scene_instances=scene_instances,
            player_states=player_states,
        )
        self._sessions[session_id] = session
        return session

    def destroy_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def submit_intent(
        self,
        session_id: str,
        player_id: str,
        intent: dict[str, object] | SceneIntent,
    ) -> None:
        session = self._get_session(session_id)
        module = self._load_module(session.module_id)

        if session.resolved_ending is not None:
            raise ValueError(f"会话 {session_id} 已进入结局，不能继续提交意图")
        if player_id not in session.player_states:
            raise KeyError(f"未知玩家: {player_id}")
        if player_id in session.pending_intents:
            raise ValueError(f"玩家 {player_id} 在本回合已经提交过意图")

        validated = SCENE_INTENT_ADAPTER.validate_python(intent)
        if isinstance(validated, MoveIntent):
            if validated.target_scene_id not in module.scene_map():
                raise ValueError(
                    f"玩家 {player_id} 提交了不存在的目标场景: {validated.target_scene_id}"
                )
        else:
            if validated.action_id not in module.action_map():
                raise ValueError(
                    f"玩家 {player_id} 提交了不存在的动作: {validated.action_id}"
                )

        session.pending_intents[player_id] = validated.model_dump()

    def resolve_turn(self, session_id: str) -> TurnResolution:
        session = self._get_session(session_id)
        if session.resolved_ending is not None:
            raise ValueError(f"会话 {session_id} 已进入结局，不能继续结算")

        snapshot = session.model_copy(deep=True)
        module = self._load_module(session.module_id)
        scene_by_id = module.scene_map()
        movement_rules = self._movement_rules(
            module=module, flags=snapshot.global_flags
        )
        event_log = [
            RuntimeEvent(
                type="turn_started",
                turn_no=snapshot.current_turn,
                message=(
                    f"第 {snapshot.current_turn} 回合开始："
                    f"会话={session_id}，待结算玩家={sorted(snapshot.pending_intents)}"
                ),
                player_ids=sorted(snapshot.pending_intents),
            )
        ]

        flag_sets: set[str] = set()
        flag_clears: set[str] = set()
        clock_deltas: dict[str, int] = defaultdict(int)
        completed_actions: set[str] = set()
        scene_events: set[str] = set()
        scene_clears: set[str] = set()
        scene_action_history: dict[str, set[str]] = defaultdict(set)
        pending_moves: dict[str, str] = {}
        scene_batches: list[SceneBatchResolution] = []

        grouped = self._group_pending_intents(snapshot)
        if not grouped:
            event_log.append(
                RuntimeEvent(
                    type="no_pending_intents",
                    turn_no=snapshot.current_turn,
                    message="本回合没有玩家意图，仅推进每回合时钟。",
                )
            )
        for scene in module.scenes:
            intents = grouped.get(scene.id)
            if not intents:
                continue

            event_log.append(
                RuntimeEvent(
                    type="scene_batch_started",
                    turn_no=snapshot.current_turn,
                    scene_id=scene.id,
                    scene_name=scene.name,
                    player_ids=[player_id for player_id, _ in intents],
                    message=(
                        f"场景批次：{scene.name}（{scene.id}），"
                        f"玩家={[player_id for player_id, _ in intents]}"
                    ),
                )
            )
            outcomes: list[IntentResolution] = []
            for player_id, intent_payload in intents:
                intent = SCENE_INTENT_ADAPTER.validate_python(intent_payload)
                player_state = snapshot.player_states[player_id]
                if isinstance(intent, MoveIntent):
                    decision = movement_rules.evaluate_transition(
                        from_scene_id=player_state.current_scene_id,
                        to_scene_id=intent.target_scene_id,
                    )
                    if decision.allowed:
                        pending_moves[player_id] = intent.target_scene_id
                    from_scene_name = scene_by_id[player_state.current_scene_id].name
                    target_scene_name = scene_by_id[intent.target_scene_id].name
                    event_log.append(
                        RuntimeEvent(
                            type="movement_attempted",
                            turn_no=snapshot.current_turn,
                            player_id=player_id,
                            from_scene_id=player_state.current_scene_id,
                            from_scene_name=from_scene_name,
                            to_scene_id=intent.target_scene_id,
                            to_scene_name=target_scene_name,
                            success=decision.allowed,
                            reason=decision.reason,
                            message=(
                                f"玩家 {player_id} 尝试移动："
                                f"{from_scene_name}（{player_state.current_scene_id}） -> "
                                f"{target_scene_name}（{intent.target_scene_id}），"
                                f"{'成功' if decision.allowed else '失败'}"
                                + (f"，原因：{decision.reason}" if decision.reason else "")
                            ),
                        )
                    )
                    outcomes.append(
                        IntentResolution(
                            player_id=player_id,
                            scene_id=player_state.current_scene_id,
                            intent_type="move",
                            success=decision.allowed,
                            reason=decision.reason,
                            target_scene_id=intent.target_scene_id,
                        )
                    )
                    continue

                action = module.action_map()[intent.action_id]
                available, reason = self._can_execute_action(
                    action=action,
                    session=snapshot,
                    player_id=player_id,
                )
                if not available:
                    current_scene_name = scene_by_id[player_state.current_scene_id].name
                    event_log.append(
                        RuntimeEvent(
                            type="action_resolved",
                            turn_no=snapshot.current_turn,
                            player_id=player_id,
                            scene_id=player_state.current_scene_id,
                            scene_name=current_scene_name,
                            action_id=action.id,
                            action_name=action.name,
                            success=False,
                            reason=reason,
                            message=(
                                f"玩家 {player_id} 在"
                                f"{current_scene_name}（{player_state.current_scene_id}）"
                                f"执行动作「{action.name}」失败，原因：{reason}"
                            ),
                        )
                    )
                    outcomes.append(
                        IntentResolution(
                            player_id=player_id,
                            scene_id=player_state.current_scene_id,
                            intent_type="action",
                            success=False,
                            reason=reason,
                            action_id=action.id,
                        )
                    )
                    continue

                scene_events.add(action.scene_id)
                completed_actions.add(action.id)
                scene_action_history[action.scene_id].add(action.id)
                if action.marks_scene_cleared:
                    scene_clears.add(action.scene_id)

                effects_applied = self._queue_effects(
                    action.effects_on_success,
                    flag_sets=flag_sets,
                    flag_clears=flag_clears,
                    clock_deltas=clock_deltas,
                )
                current_scene_name = scene_by_id[player_state.current_scene_id].name
                event_log.append(
                    RuntimeEvent(
                        type="action_resolved",
                        turn_no=snapshot.current_turn,
                        player_id=player_id,
                        scene_id=player_state.current_scene_id,
                        scene_name=current_scene_name,
                        action_id=action.id,
                        action_name=action.name,
                        success=True,
                        effects_applied=effects_applied,
                        message=(
                            f"玩家 {player_id} 在"
                            f"{current_scene_name}（{player_state.current_scene_id}）"
                            f"执行动作「{action.name}」成功，"
                            f"效果={effects_applied or ['无']}"
                        ),
                    )
                )
                outcomes.append(
                    IntentResolution(
                        player_id=player_id,
                        scene_id=player_state.current_scene_id,
                        intent_type="action",
                        success=True,
                        action_id=action.id,
                        effects_applied=effects_applied,
                    )
                )

            scene_batches.append(
                SceneBatchResolution(
                    scene_id=scene.id,
                    player_ids=[player_id for player_id, _ in intents],
                    outcomes=outcomes,
                )
            )

        session.pending_intents = {}
        for player_id, target_scene_id in pending_moves.items():
            player_state = session.player_states[player_id]
            previous_scene_id = player_state.current_scene_id
            player_state.last_scene_id = player_state.current_scene_id
            player_state.current_scene_id = target_scene_id
            event_log.append(
                RuntimeEvent(
                    type="movement_committed",
                    turn_no=snapshot.current_turn,
                    player_id=player_id,
                    from_scene_id=previous_scene_id,
                    from_scene_name=scene_by_id[previous_scene_id].name,
                    to_scene_id=target_scene_id,
                    to_scene_name=scene_by_id[target_scene_id].name,
                    success=True,
                    message=(
                        f"提交移动结果：玩家 {player_id} "
                        f"{scene_by_id[previous_scene_id].name}（{previous_scene_id}） -> "
                        f"{scene_by_id[target_scene_id].name}（{target_scene_id}）"
                    ),
                )
            )

        for action_id in completed_actions:
            session.completed_actions.add(action_id)
        for scene_id in scene_events:
            session.scene_instances[scene_id].has_event_occurred = True
        for scene_id in scene_clears:
            session.scene_instances[scene_id].is_cleared = True
        for scene_id, action_ids in scene_action_history.items():
            session.scene_instances[scene_id].completed_action_ids.update(action_ids)

        self._apply_flag_changes(session, flag_sets=flag_sets, flag_clears=flag_clears)
        self._apply_clock_deltas(session, module=module, deltas=clock_deltas)

        session.current_turn += 1
        per_turn_deltas = {
            clock.id: clock.step_per_turn
            for clock in module.clocks
            if clock.step_per_turn > 0
        }
        self._apply_clock_deltas(session, module=module, deltas=per_turn_deltas)
        combined_clock_deltas = dict(clock_deltas)
        for clock_id, delta in per_turn_deltas.items():
            combined_clock_deltas[clock_id] = (
                combined_clock_deltas.get(clock_id, 0) + delta
            )

        triggered_clock_events = self._trigger_clock_events(session, module)
        ending = self._resolve_ending(session, module)

        applied_flags = sorted(session.global_flags - snapshot.global_flags)
        if applied_flags or flag_clears:
            event_log.append(
                RuntimeEvent(
                    type="flags_changed",
                    turn_no=snapshot.current_turn,
                    added_flags=applied_flags,
                    removed_flags=sorted(flag_clears),
                    message=(
                        "标记变化："
                        f"新增={applied_flags or []}，"
                        f"移除={sorted(flag_clears) or []}"
                    ),
                )
            )
        if combined_clock_deltas:
            event_log.append(
                RuntimeEvent(
                    type="clocks_advanced",
                    turn_no=snapshot.current_turn,
                    clock_deltas=dict(combined_clock_deltas),
                    message=f"时钟推进：{dict(combined_clock_deltas)}",
                )
            )
        if triggered_clock_events:
            event_log.append(
                RuntimeEvent(
                    type="clock_events_triggered",
                    turn_no=snapshot.current_turn,
                    triggered_clock_events=triggered_clock_events,
                    message=f"触发时钟事件：{triggered_clock_events}",
                )
            )
        if ending is not None:
            event_log.append(
                RuntimeEvent(
                    type="ending_reached",
                    turn_no=snapshot.current_turn,
                    ending_id=ending.id,
                    ending_result=ending.result,
                    scene_id=ending.scene_id,
                    scene_name=scene_by_id[ending.scene_id].name,
                    message=f"达成结局：{ending.id}，结果：{ending.result}",
                )
            )
        event_log.append(
            RuntimeEvent(
                type="turn_completed",
                turn_no=snapshot.current_turn,
                clock_values=dict(session.clock_values),
                message=(
                    f"第 {snapshot.current_turn} 回合结束："
                    f"下一回合={session.current_turn}，时钟值={dict(session.clock_values)}"
                ),
            )
        )
        return TurnResolution(
            session_id=session_id,
            turn_no=snapshot.current_turn,
            next_turn=session.current_turn,
            scene_batches=scene_batches,
            event_log=event_log,
            applied_flags=applied_flags,
            applied_clock_deltas=combined_clock_deltas,
            triggered_clock_events=triggered_clock_events,
            clock_values=dict(session.clock_values),
            resolved_ending=ending.id if ending is not None else None,
            ending_result=ending.result if ending is not None else "",
        )

    def list_reachable_scenes(
        self,
        session_state: SessionMapState,
        player_id: str,
    ) -> list[str]:
        self._ensure_known_player(session_state, player_id)
        player_state = session_state.player_states[player_id]
        module = self._load_module(session_state.module_id)
        movement_rules = self._movement_rules(
            module=module,
            flags=session_state.global_flags,
        )
        return movement_rules.list_reachable_scenes(
            from_scene_id=player_state.current_scene_id
        )

    def list_available_actions(
        self,
        session_state: SessionMapState,
        player_id: str,
    ) -> list[ModuleAction]:
        self._ensure_known_player(session_state, player_id)
        player_state = session_state.player_states[player_id]
        module = self._load_module(session_state.module_id)

        available_actions: list[ModuleAction] = []
        for action in module.actions:
            if action.scene_id != player_state.current_scene_id:
                continue
            available, _ = self._can_execute_action(
                action=action,
                session=session_state,
                player_id=player_id,
            )
            if available:
                available_actions.append(action)
        return available_actions

    def _load_module(self, module_id: str) -> ModuleDefinition:
        if module_id not in self._module_cache:
            self._module_cache[module_id] = load_module_by_id(
                module_id,
                module_root=self._module_root,
            )
        return self._module_cache[module_id]

    def _get_session(self, session_id: str) -> SessionMapState:
        if session_id not in self._sessions:
            raise KeyError(f"未知会话: {session_id}")
        return self._sessions[session_id]

    def _movement_rules(
        self,
        *,
        module: ModuleDefinition,
        flags: set[str],
    ) -> SceneMovementRules:
        scene_links = [
            SceneLink(
                from_scene_id=link.from_scene_id,
                to_scene_id=link.to_scene_id,
                required_flags=list(link.required_flags),
                block_reason=link.block_reason,
            )
            for link in module.links
        ]
        return SceneMovementRules(
            scene_links=scene_links,
            active_flags=flags,
        )

    def _group_pending_intents(
        self,
        session: SessionMapState,
    ) -> dict[str, list[tuple[str, dict[str, object]]]]:
        grouped: dict[str, list[tuple[str, dict[str, object]]]] = defaultdict(list)
        for player_id, intent in session.pending_intents.items():
            scene_id = session.player_states[player_id].current_scene_id
            grouped[scene_id].append((player_id, intent))
        return grouped

    def _can_execute_action(
        self,
        *,
        action: ModuleAction,
        session: SessionMapState,
        player_id: str,
    ) -> tuple[bool, str]:
        player_state = session.player_states[player_id]
        if action.scene_id != player_state.current_scene_id:
            return False, "动作不在玩家当前场景中"
        if action.once and action.id in session.completed_actions:
            return False, "该动作在本会话中已经执行过"
        if not self._conditions_met(action.conditions, session):
            return False, "动作前置条件未满足"
        return True, ""

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

    def _queue_effects(
        self,
        effects: list[ModuleEffect],
        *,
        flag_sets: set[str],
        flag_clears: set[str],
        clock_deltas: dict[str, int],
    ) -> list[str]:
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

    def _apply_flag_changes(
        self,
        session: SessionMapState,
        *,
        flag_sets: set[str],
        flag_clears: set[str],
    ) -> None:
        for flag in flag_clears:
            session.global_flags.discard(flag)
        for flag in flag_sets:
            session.global_flags.add(flag)

    def _apply_clock_deltas(
        self,
        session: SessionMapState,
        *,
        module: ModuleDefinition,
        deltas: dict[str, int],
    ) -> None:
        for clock in module.clocks:
            delta = deltas.get(clock.id, 0)
            if delta == 0:
                continue
            current_value = session.clock_values.get(clock.id, clock.start)
            session.clock_values[clock.id] = min(clock.max_value, current_value + delta)

    def _trigger_clock_events(
        self,
        session: SessionMapState,
        module: ModuleDefinition,
    ) -> list[str]:
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
        self._queue_effects(
            effects,
            flag_sets=flag_sets,
            flag_clears=flag_clears,
            clock_deltas=clock_deltas,
        )
        self._apply_flag_changes(
            session,
            flag_sets=flag_sets,
            flag_clears=flag_clears,
        )
        self._apply_clock_deltas(
            session,
            module=module,
            deltas=clock_deltas,
        )

    def _resolve_ending(
        self,
        session: SessionMapState,
        module: ModuleDefinition,
    ) -> ModuleEnding | None:
        if session.resolved_ending is not None:
            ending = next(
                (item for item in module.endings if item.id == session.resolved_ending),
                None,
            )
            return ending

        occupied_scenes = {
            player_state.current_scene_id
            for player_state in session.player_states.values()
        }
        for ending in module.endings:
            if ending.scene_id not in occupied_scenes:
                continue
            if self._conditions_met(ending.conditions, session):
                session.resolved_ending = ending.id
                return ending
        return None

    def _ensure_known_player(
        self,
        session_state: SessionMapState,
        player_id: str,
    ) -> None:
        if player_id not in session_state.player_states:
            raise KeyError(f"未知玩家: {player_id}")
