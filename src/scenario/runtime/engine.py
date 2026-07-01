"""基于 YAML 模组定义的最小场景运行时。"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from cards.domain.card import InvestigatorCard

from ..agent.models import CommitResult, KeeperAgentPlan
from ..agent.plan_agent import KeeperPlanAgent
from ..agent.prompt_builder import PromptBuilder
from ..agent.render_agent import KeeperRenderAgent
from ..io.module_loader import MODULE_ROOT, load_module_by_id
from ..module.models import ModuleAction, ModuleDefinition
from ..scene.models import SceneLink
from ..scene.rules import SceneMovementRules
from ..session.state import (
    IllegalMoveRiskState,
    SceneInstanceState,
    SessionMapState,
    SessionPlayerState,
)
from ..story.models import StorySignal, StoryState
from ..story.services import StoryStateService, TransitionValidator
from .contracts import (
    IntentResolution,
    MoveIntent,
    RuntimeEvent,
    SCENE_INTENT_ADAPTER,
    SceneBatchResolution,
    SceneIntent,
    TurnResolution,
)
from .movement_risk import (
    OFF_MAP_DECAY_PER_SAFE_TURN,
    off_map_penalty_tier,
    off_map_threshold_value,
    preview_off_map_risk_update,
)
from .rule_engine import RollProvider, RuleEngine

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from scenario.narration import KeeperNarrationRecord, NarrationPipeline


class SceneRuntime:
    """YAML 模组的最小运行时协调器。

    负责会话生命周期、回合结算、规则判定与剧情状态推进。
    """

    def __init__(
        self,
        *,
        module_root: str | Path | None = None,
        roll_provider: RollProvider | None = None,
        rule_engine: RuleEngine | None = None,
        plan_agent: KeeperPlanAgent | None = None,
        render_agent: KeeperRenderAgent | None = None,
        prompt_builder: PromptBuilder | None = None,
    ) -> None:
        """
        Args:
            module_root: 模组根目录，默认从 MODULE_ROOT 读取。
            roll_provider: 骰子随机数提供者（测试时可注入固定值）。
            rule_engine: 规则引擎，默认自动创建。
            plan_agent: Plan 阶段 Agent；为 None 时跳过 Planner，规则引擎按 YAML 默认逻辑处理。
            render_agent: Render 阶段 Agent；为 None 时 SceneBatchResolution.narration 为 None。
            prompt_builder: PromptBuilder；为 None 时若 plan_agent 不为 None 则自动创建默认实例。
        """
        self._module_root = (
            Path(module_root) if module_root is not None else MODULE_ROOT
        )
        self._sessions: dict[str, SessionMapState] = {}
        self._module_cache: dict[str, ModuleDefinition] = {}
        self._transition_validator = TransitionValidator()
        self._story_state_service = StoryStateService()
        self._rule_engine = rule_engine or RuleEngine(roll_provider=roll_provider)
        self._plan_agent = plan_agent
        self._render_agent = render_agent
        # 如果传入了 plan_agent 但没有传 prompt_builder，则自动创建默认实例
        self._prompt_builder = prompt_builder or (
            PromptBuilder() if plan_agent is not None else None
        )

    def create_session(
        self,
        module_id: str,
        player_ids: list[str],
        *,
        player_cards: Mapping[str, InvestigatorCard],
    ) -> SessionMapState:
        """创建会话快照并初始化玩家、场景实例与时钟。"""
        if not player_ids:
            raise ValueError("创建会话时至少需要一个 player_id")

        unknown_player_ids = sorted(set(player_cards) - set(player_ids))
        if unknown_player_ids:
            raise ValueError(f"player_cards 包含未知玩家: {unknown_player_ids}")
        missing_player_ids = sorted(set(player_ids) - set(player_cards))
        if missing_player_ids:
            raise ValueError(f"player_cards 缺少玩家: {missing_player_ids}")
        empty_card_player_ids = sorted(
            player_id for player_id in player_ids if player_cards[player_id] is None
        )
        if empty_card_player_ids:
            raise ValueError(
                f"player_cards 中玩家未绑定人物卡: {empty_card_player_ids}"
            )

        module = self._load_module(module_id)
        session_id = uuid4().hex[:12]
        entry_scene_id = module.entry_scene_id
        player_states = {
            player_id: SessionPlayerState(
                session_id=session_id,
                player_id=player_id,
                current_scene_id=entry_scene_id,
                last_scene_id=entry_scene_id,
                investigator=self._rule_engine.clone_card(player_cards[player_id]),
            )
            for player_id in player_ids
        }
        scene_instances = {
            scene.id: SceneInstanceState(scene_id=scene.id) for scene in module.scenes
        }
        session = SessionMapState(
            session_id=session_id,
            module_id=module.module_id,
            story_state=StoryState(current_stage_id=module.entry_stage_id),
            clock_values={clock.id: clock.start for clock in module.clocks},
            scene_instances=scene_instances,
            player_states=player_states,
        )
        self._sessions[session_id] = session
        return session

    def destroy_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def get_session(self, session_id: str) -> SessionMapState:
        return self._get_session(session_id)

    def add_player(
        self,
        session_id: str,
        player_id: str,
        *,
        investigator: InvestigatorCard,
    ) -> SessionPlayerState:
        """向尚未开始且未结束的会话加入玩家。"""
        if investigator is None:
            raise ValueError("add_player 时必须提供 investigator 人物卡")

        session = self._get_session(session_id)
        if (
            session.resolved_ending is not None
            or session.story_state.resolved_ending_id is not None
        ):
            raise ValueError(f"会话 {session_id} 已进入结局，不能再加入新玩家")
        if session.current_turn != 1:
            raise ValueError(f"会话 {session_id} 已经开始，不能再加入新玩家")
        if session.pending_intents:
            raise ValueError(f"会话 {session_id} 当前已有待结算意图，不能加入新玩家")
        if player_id in session.player_states:
            raise ValueError(f"玩家 {player_id} 已经在会话 {session_id} 中")

        module = self._load_module(session.module_id)
        player_state = SessionPlayerState(
            session_id=session_id,
            player_id=player_id,
            current_scene_id=module.entry_scene_id,
            last_scene_id=module.entry_scene_id,
            investigator=self._rule_engine.clone_card(investigator),
        )
        session.player_states[player_id] = player_state
        return player_state

    def submit_intent(
        self,
        session_id: str,
        player_id: str,
        intent: dict[str, object] | SceneIntent,
    ) -> None:
        """提交并缓存玩家本回合意图。"""
        session = self._get_session(session_id)
        module = self._load_module(session.module_id)

        if (
            session.resolved_ending is not None
            or session.story_state.resolved_ending_id is not None
        ):
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

    async def resolve_turn(self, session_id: str) -> TurnResolution:
        """结算一个完整回合（异步）。

        流程：
        1. 读取快照，按场景分批分组
        2. 每批次：[Plan Agent] → [规则引擎 + 动态检定] → [提交效果] → [Render Agent]
        3. 跨批次：推进时钟 / 触发时钟事件 / 计算剧情迁移 / 写 event_log

        若 ``plan_agent`` 未配置，步骤 2 中的 Plan 阶段被跳过，
        规则引擎按 YAML 定义的静态检定与效果运行（与原有行为完全兼容）。
        若 ``render_agent`` 未配置，``SceneBatchResolution.narration`` 保持 None。
        """
        session = self._get_session(session_id)
        if (
            session.resolved_ending is not None
            or session.story_state.resolved_ending_id is not None
        ):
            raise ValueError(f"会话 {session_id} 已进入结局，不能继续结算")

        # 使用深拷贝快照做“判定输入”，避免中途写入影响同回合后续判定。
        snapshot = session.model_copy(deep=True)
        module = self._load_module(session.module_id)
        scene_by_id = module.scene_map()
        story_stage_by_id = module.story_stage_map()
        movement_rules = self._movement_rules(
            module=module,
            flags=snapshot.global_flags,
            stage_id=snapshot.story_state.current_stage_id,
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
                source_stage_id=snapshot.story_state.current_stage_id,
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
        movement_risk_states: dict[str, IllegalMoveRiskState] = {
            player_id: player_state.illegal_move_risk.model_copy(deep=True)
            for player_id, player_state in session.player_states.items()
        }
        players_with_off_map_move: set[str] = set()
        scene_batches: list[SceneBatchResolution] = []

        # 先按玩家当前位置分组，形成场景批次结算。
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

            batch_player_ids = [player_id for player_id, _ in intents]
            event_log.append(
                RuntimeEvent(
                    type="scene_batch_started",
                    turn_no=snapshot.current_turn,
                    scene_id=scene.id,
                    scene_name=scene.name,
                    player_ids=batch_player_ids,
                    message=(
                        f"场景批次：{scene.name}（{scene.id}），玩家={batch_player_ids}"
                    ),
                )
            )

            # ------------------------------------------------------------------
            # Plan 阶段：调用 KeeperPlanAgent 产出结构化提议
            # ------------------------------------------------------------------
            plan: KeeperAgentPlan | None = None
            # 本批次 Agent 提议的动态检定结果，key 为 (player_id, action_id)
            dynamic_check_results: dict[tuple[str, str], dict] = {}

            if self._plan_agent is not None and self._prompt_builder is not None:
                try:
                    agent_prompt = self._prompt_builder.build(
                        session=snapshot,
                        module=module,
                        scene_id=scene.id,
                        recent_events=event_log,
                    )
                    plan_record = await self._plan_agent.call(agent_prompt)
                    plan = plan_record.output
                    event_log.append(
                        RuntimeEvent(
                            type="plan_agent_called",
                            turn_no=snapshot.current_turn,
                            scene_id=scene.id,
                            scene_name=scene.name,
                            fallback_used=plan_record.meta.fallback_used,
                            message=(
                                f"Plan Agent 调用完成（scene={scene.id}，"
                                f"fallback={plan_record.meta.fallback_used}）："
                                f"提议检定数={len(plan.proposed_checks)}，"
                                f"提议效果数={len(plan.proposed_effects)}，"
                                f"提议迁移={'有' if plan.proposed_transition else '无'}"
                            ),
                        )
                    )
                    # 执行 Agent 提议的动态检定（在规则引擎静态检定之前）
                    for proposed in plan.proposed_checks:
                        ps = snapshot.player_states.get(proposed.player_id)
                        if ps is None:
                            logger.warning(
                                "Plan Agent 提议对未知玩家 %s 执行检定，已跳过",
                                proposed.player_id,
                            )
                            continue
                        result = self._rule_engine.resolve_proposed_check(
                            proposed=proposed,
                            player_state=ps,
                        )
                        dynamic_check_results[
                            (proposed.player_id, proposed.action_id)
                        ] = result
                        logger.debug(
                            "动态检定：player=%s action=%s skill=%s roll=%s success=%s",
                            proposed.player_id,
                            proposed.action_id,
                            proposed.skill_key,
                            result.get("roll_value"),
                            result.get("success"),
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Plan Agent 调用失败（scene=%s）：%s，继续按规则引擎默认逻辑处理",
                        scene.id,
                        exc,
                    )
                    event_log.append(
                        RuntimeEvent(
                            type="plan_agent_skipped",
                            turn_no=snapshot.current_turn,
                            scene_id=scene.id,
                            scene_name=scene.name,
                            message=f"Plan Agent 调用失败（scene={scene.id}）：{exc}",
                        )
                    )
            else:
                event_log.append(
                    RuntimeEvent(
                        type="plan_agent_skipped",
                        turn_no=snapshot.current_turn,
                        scene_id=scene.id,
                        scene_name=scene.name,
                        message=f"Plan Agent 未配置，scene={scene.id} 按规则引擎默认逻辑处理",
                    )
                )

            # ------------------------------------------------------------------
            # 规则判定阶段：逐意图处理（移动 / 动作 / 动态检定覆盖）
            # ------------------------------------------------------------------
            outcomes: list[IntentResolution] = []
            # 本批次已完成的动态检定结果，最终传入 CommitResult
            batch_resolved_checks: list[dict] = list(dynamic_check_results.values())

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
                    violation_kind = (
                        "off_map_move"
                        if not decision.allowed and decision.reason_code == "no_link"
                        else ""
                    )
                    reason_code = decision.reason_code
                    penalty_tier = ""
                    illegal_value: int | None = None
                    effects_applied: list[str] = []
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
                            reason_code=reason_code,
                            violation_kind=violation_kind,
                            message=(
                                f"玩家 {player_id} 尝试移动："
                                f"{from_scene_name}（{player_state.current_scene_id}） -> "
                                f"{target_scene_name}（{intent.target_scene_id}），"
                                f"{'成功' if decision.allowed else '失败'}"
                                + (
                                    f"，原因：{decision.reason}"
                                    if decision.reason
                                    else ""
                                )
                            ),
                        )
                    )
                    if violation_kind == "off_map_move":
                        players_with_off_map_move.add(player_id)
                        risk_update, penalty_event = self._record_off_map_move_risk(
                            risk=movement_risk_states[player_id],
                            player_id=player_id,
                            turn_no=snapshot.current_turn,
                            from_scene_id=player_state.current_scene_id,
                            from_scene_name=from_scene_name,
                            to_scene_id=intent.target_scene_id,
                            to_scene_name=target_scene_name,
                        )
                        event_log.append(risk_update)
                        penalty_tier = risk_update.penalty_tier
                        illegal_value = risk_update.score_after
                        if penalty_event is not None:
                            event_log.append(penalty_event)
                            effects_applied = list(penalty_event.effects_applied)
                    outcomes.append(
                        IntentResolution(
                            player_id=player_id,
                            scene_id=player_state.current_scene_id,
                            intent_type="move",
                            success=decision.allowed,
                            reason=decision.reason,
                            reason_code=reason_code,
                            violation_kind=violation_kind,
                            penalty_tier=penalty_tier,
                            illegal_value=illegal_value,
                            target_scene_id=intent.target_scene_id,
                            effects_applied=effects_applied,
                        )
                    )
                    continue

                action = module.action_map()[intent.action_id]
                available, reason = self._rule_engine.can_execute_action(
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

                # 检查 Agent 是否已为此 (player_id, action_id) 提议过动态检定。
                # 若有，使用动态检定结果决定成败；否则走 YAML 静态检定。
                dynamic_result = dynamic_check_results.get((player_id, action.id))
                if dynamic_result is not None:
                    check_passed = dynamic_result["success"]
                    check_reason = (
                        ""
                        if check_passed
                        else (
                            action.check.failure_reason
                            if action.check
                            else f"动态检定失败（{dynamic_result['skill_key']}）"
                        )
                    )
                    failure_effects: list[str] = []
                    if not check_passed:
                        failure_effects = self._rule_engine.queue_effects(
                            action.effects_on_failure,
                            flag_sets=flag_sets,
                            flag_clears=flag_clears,
                            clock_deltas=clock_deltas,
                        )
                else:
                    check_passed, check_reason, failure_effects = (
                        self._rule_engine.resolve_action_check(
                            action=action,
                            player_state=player_state,
                            flag_sets=flag_sets,
                            flag_clears=flag_clears,
                            clock_deltas=clock_deltas,
                        )
                    )

                if not check_passed:
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
                            reason=check_reason,
                            effects_applied=failure_effects,
                            message=(
                                f"玩家 {player_id} 在"
                                f"{current_scene_name}（{player_state.current_scene_id}）"
                                f"执行动作「{action.name}」失败，原因：{check_reason}"
                            ),
                        )
                    )
                    outcomes.append(
                        IntentResolution(
                            player_id=player_id,
                            scene_id=player_state.current_scene_id,
                            intent_type="action",
                            success=False,
                            reason=check_reason,
                            action_id=action.id,
                            effects_applied=failure_effects,
                        )
                    )
                    continue

                scene_events.add(action.scene_id)
                completed_actions.add(action.id)
                scene_action_history[action.scene_id].add(action.id)
                if action.marks_scene_cleared:
                    scene_clears.add(action.scene_id)

                effects_applied = self._rule_engine.queue_effects(
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

            # ------------------------------------------------------------------
            # Render 阶段：基于本批次已结算结果调用 KeeperRenderAgent 生成叙事
            # ------------------------------------------------------------------
            batch_narration = None
            if self._render_agent is not None:
                # 从本批次 outcomes 提取已生效效果摘要
                batch_effects = []
                for outcome in outcomes:
                    batch_effects.extend(outcome.effects_applied)

                commit = CommitResult(
                    session_id=session_id,
                    turn_no=snapshot.current_turn,
                    scene_id=scene.id,
                    resolved_checks=batch_resolved_checks,
                    applied_effects=batch_effects,
                    # 剧情迁移信息此时还未计算，放空（叙事可在无迁移情况下正常生成）
                    applied_transition_id=None,
                    new_stage_id=None,
                    resolved_ending=None,
                    event_summary=[e.message for e in event_log[-10:]],
                )
                try:
                    render_record = await self._render_agent.call(commit)
                    batch_narration = render_record.output
                    event_log.append(
                        RuntimeEvent(
                            type="render_agent_called",
                            turn_no=snapshot.current_turn,
                            scene_id=scene.id,
                            scene_name=scene.name,
                            fallback_used=render_record.meta.fallback_used,
                            message=(
                                f"Render Agent 调用完成（scene={scene.id}，"
                                f"fallback={render_record.meta.fallback_used}）"
                            ),
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Render Agent 调用失败（scene=%s）：%s",
                        scene.id,
                        exc,
                    )
                    event_log.append(
                        RuntimeEvent(
                            type="render_agent_skipped",
                            turn_no=snapshot.current_turn,
                            scene_id=scene.id,
                            scene_name=scene.name,
                            message=f"Render Agent 调用失败（scene={scene.id}）：{exc}",
                        )
                    )
            else:
                event_log.append(
                    RuntimeEvent(
                        type="render_agent_skipped",
                        turn_no=snapshot.current_turn,
                        scene_id=scene.id,
                        scene_name=scene.name,
                        message=f"Render Agent 未配置，scene={scene.id} 无叙事输出",
                    )
                )

            scene_batches.append(
                SceneBatchResolution(
                    scene_id=scene.id,
                    player_ids=batch_player_ids,
                    outcomes=outcomes,
                    narration=batch_narration,
                )
            )

        for player_id, risk in movement_risk_states.items():
            if player_id in players_with_off_map_move:
                continue
            decay_event = self._decay_off_map_move_risk(
                risk=risk,
                player_id=player_id,
                turn_no=snapshot.current_turn,
            )
            if decay_event is not None:
                event_log.append(decay_event)

        # 批次处理结束后统一提交状态，先清空待结算意图。
        session.pending_intents = {}
        for player_id, risk in movement_risk_states.items():
            session.player_states[player_id].illegal_move_risk = risk
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

        # 先应用动作层效果，再处理每回合时钟推进。
        self._rule_engine.apply_flag_changes(
            session,
            flag_sets=flag_sets,
            flag_clears=flag_clears,
        )
        self._rule_engine.apply_clock_deltas(
            session,
            module=module,
            deltas=clock_deltas,
        )

        session.current_turn += 1
        per_turn_deltas = {
            clock.id: clock.step_per_turn
            for clock in module.clocks
            if clock.step_per_turn > 0
        }
        self._rule_engine.apply_clock_deltas(
            session,
            module=module,
            deltas=per_turn_deltas,
        )
        combined_clock_deltas = dict(clock_deltas)
        for clock_id, delta in per_turn_deltas.items():
            combined_clock_deltas[clock_id] = (
                combined_clock_deltas.get(clock_id, 0) + delta
            )

        triggered_clock_events = self._rule_engine.trigger_clock_events(session, module)
        story_signals = self._build_story_signals(
            events=event_log,
            triggered_clock_events=triggered_clock_events,
            turn_no=snapshot.current_turn,
        )
        # 仅基于“本回合已提交结果”生成信号并计算剧情迁移。
        transition = self._transition_validator.can_transition(
            story_state=snapshot.story_state,
            stages=story_stage_by_id,
            transitions=module.story_transitions,
            signals=story_signals,
            flags=set(session.global_flags),
        )

        new_stage: str | None = None
        applied_story_transition_id: str | None = None
        story_transition_flag_clears: set[str] = set()
        if transition is not None:
            story_flag_sets: set[str] = set()
            story_flag_clears: set[str] = set()
            story_clock_deltas: dict[str, int] = defaultdict(int)
            story_effects_applied = self._rule_engine.queue_effects(
                transition.effects,
                flag_sets=story_flag_sets,
                flag_clears=story_flag_clears,
                clock_deltas=story_clock_deltas,
            )
            self._rule_engine.apply_flag_changes(
                session,
                flag_sets=story_flag_sets,
                flag_clears=story_flag_clears,
            )
            story_transition_flag_clears = set(story_flag_clears)
            self._rule_engine.apply_clock_deltas(
                session,
                module=module,
                deltas=story_clock_deltas,
            )
            for clock_id, delta in story_clock_deltas.items():
                combined_clock_deltas[clock_id] = (
                    combined_clock_deltas.get(clock_id, 0) + delta
                )
            if story_clock_deltas:
                triggered_clock_events.extend(
                    self._rule_engine.trigger_clock_events(session, module)
                )
            session.story_state = self._story_state_service.apply_transition(
                story_state=snapshot.story_state,
                transition=transition,
                stages=story_stage_by_id,
                turn_no=session.current_turn,
            )
            new_stage = session.story_state.current_stage_id
            applied_story_transition_id = transition.id
            event_log.append(
                RuntimeEvent(
                    type="story_transition_applied",
                    turn_no=snapshot.current_turn,
                    story_transition_id=transition.id,
                    source_stage_id=transition.source_stage_id,
                    target_stage_id=transition.target_stage_id,
                    effects_applied=story_effects_applied,
                    message=(
                        f"剧情迁移：{transition.source_stage_id} -> "
                        f"{transition.target_stage_id}，"
                        f"触发器={transition.trigger_type}:{transition.trigger_value}"
                    ),
                )
            )

        ending_stage = (
            story_stage_by_id[session.story_state.resolved_ending_id]
            if session.story_state.resolved_ending_id is not None
            else None
        )
        if ending_stage is not None:
            session.resolved_ending = session.story_state.resolved_ending_id
        resolved_ending = session.resolved_ending
        ending_result = ending_stage.description if ending_stage is not None else ""

        applied_flags = sorted(session.global_flags - snapshot.global_flags)
        all_removed_flags = sorted(flag_clears | story_transition_flag_clears)
        if applied_flags or all_removed_flags:
            event_log.append(
                RuntimeEvent(
                    type="flags_changed",
                    turn_no=snapshot.current_turn,
                    added_flags=applied_flags,
                    removed_flags=all_removed_flags,
                    message=(
                        "标记变化："
                        f"新增={applied_flags or []}，"
                        f"移除={all_removed_flags or []}"
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
        if ending_stage is not None:
            event_log.append(
                RuntimeEvent(
                    type="ending_reached",
                    turn_no=snapshot.current_turn,
                    ending_id=ending_stage.id,
                    ending_result=ending_stage.description,
                    scene_name=ending_stage.name,
                    target_stage_id=ending_stage.id,
                    message=f"达成结局：{ending_stage.id}，结果：{ending_stage.description}",
                )
            )
        event_log.append(
            RuntimeEvent(
                type="turn_completed",
                turn_no=snapshot.current_turn,
                clock_values=dict(session.clock_values),
                target_stage_id=session.story_state.current_stage_id,
                message=(
                    f"第 {snapshot.current_turn} 回合结束："
                    f"下一回合={session.current_turn}，"
                    f"当前剧情阶段={session.story_state.current_stage_id}，"
                    f"时钟值={dict(session.clock_values)}"
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
            story_signals=story_signals,
            new_stage=new_stage,
            applied_story_transition_id=applied_story_transition_id,
            resolved_ending=resolved_ending,
            ending_result=ending_result,
        )

    def _record_off_map_move_risk(
        self,
        *,
        risk: IllegalMoveRiskState,
        player_id: str,
        turn_no: int,
        from_scene_id: str,
        from_scene_name: str,
        to_scene_id: str,
        to_scene_name: str,
    ) -> tuple[RuntimeEvent, RuntimeEvent | None]:
        score_before = risk.illegal_value
        previous_tier = risk.last_penalty_tier
        preview = preview_off_map_risk_update(risk, turn_no=turn_no)
        consecutive_count = int(preview["consecutive_count"])
        increment = int(preview["delta"])
        score_after = int(preview["score_after"])
        risk.illegal_value = score_after
        risk.consecutive_count = consecutive_count
        risk.total_count += 1
        risk.recent_window_count += 1
        risk.last_violation_turn = turn_no
        risk.last_penalty_tier = str(preview["penalty_tier"])
        if risk.last_penalty_tier == "severe_penalty":
            risk.severe_triggered = True

        threshold_crossed = str(preview["threshold_crossed"])
        threshold_value = off_map_threshold_value(threshold_crossed)
        risk_event_id = (
            f"movement_risk:{player_id}:{turn_no}:"
            f"{from_scene_id}->{to_scene_id}:{risk.total_count}"
        )
        risk_event = RuntimeEvent(
            type="movement_risk_updated",
            turn_no=turn_no,
            player_id=player_id,
            from_scene_id=from_scene_id,
            from_scene_name=from_scene_name,
            to_scene_id=to_scene_id,
            to_scene_name=to_scene_name,
            reason="场景之间不存在可通行连线，记录越界移动风险。",
            reason_code="no_link",
            violation_kind="off_map_move",
            score_before=score_before,
            score_after=score_after,
            delta=increment,
            threshold_crossed=threshold_crossed,
            penalty_tier=risk.last_penalty_tier,
            consecutive_count=risk.consecutive_count,
            recent_window_count=risk.recent_window_count,
            required_threshold=threshold_value,
            source_event_id=risk_event_id,
            message=(
                f"越界移动风险更新：玩家 {player_id} "
                f"{from_scene_name}（{from_scene_id}） -> "
                f"{to_scene_name}（{to_scene_id}），"
                f"分数 {score_before} + {increment} = {score_after}，"
                f"等级={risk.last_penalty_tier}"
            ),
        )

        if risk.last_penalty_tier not in {"major_penalty", "severe_penalty"}:
            return risk_event, None
        if threshold_crossed not in {"major_penalty", "severe_penalty"} and (
            previous_tier in {"major_penalty", "severe_penalty"}
        ):
            return risk_event, None

        required_threshold = off_map_threshold_value(risk.last_penalty_tier)
        penalty_event = RuntimeEvent(
            type="movement_penalty_triggered",
            turn_no=turn_no,
            player_id=player_id,
            from_scene_id=from_scene_id,
            from_scene_name=from_scene_name,
            to_scene_id=to_scene_id,
            to_scene_name=to_scene_name,
            reason="越界移动风险达到重度惩罚阈值。",
            reason_code="no_link",
            violation_kind="off_map_move",
            score_before=score_before,
            score_after=score_after,
            delta=increment,
            threshold_crossed=threshold_crossed or risk.last_penalty_tier,
            penalty_tier=risk.last_penalty_tier,
            consecutive_count=risk.consecutive_count,
            recent_window_count=risk.recent_window_count,
            required_threshold=required_threshold,
            actual_score=score_after,
            source_event_id=risk_event_id,
            effects_applied=[f"off_map_{risk.last_penalty_tier}"],
            message=(
                f"触发越界移动惩罚：玩家 {player_id} "
                f"风险={score_after}/{required_threshold}，"
                f"等级={risk.last_penalty_tier}"
            ),
        )
        return risk_event, penalty_event

    def _decay_off_map_move_risk(
        self,
        *,
        risk: IllegalMoveRiskState,
        player_id: str,
        turn_no: int,
    ) -> RuntimeEvent | None:
        if risk.illegal_value <= 0:
            risk.consecutive_count = 0
            return None

        score_before = risk.illegal_value
        score_after = max(0, score_before - OFF_MAP_DECAY_PER_SAFE_TURN)
        risk.illegal_value = score_after
        risk.consecutive_count = 0
        risk.last_penalty_tier = off_map_penalty_tier(score_after)
        if score_after == 0:
            risk.recent_window_count = 0

        return RuntimeEvent(
            type="movement_risk_updated",
            turn_no=turn_no,
            player_id=player_id,
            reason="本回合未发生越界移动，越界移动风险缓慢衰减。",
            reason_code="risk_decay",
            score_before=score_before,
            score_after=score_after,
            delta=score_after - score_before,
            decay_applied=OFF_MAP_DECAY_PER_SAFE_TURN,
            penalty_tier=risk.last_penalty_tier,
            consecutive_count=risk.consecutive_count,
            recent_window_count=risk.recent_window_count,
            message=(
                f"越界移动风险衰减：玩家 {player_id} "
                f"分数 {score_before} -> {score_after}，"
                f"等级={risk.last_penalty_tier}"
            ),
        )

    def list_reachable_scenes(
        self,
        session_state: SessionMapState,
        player_id: str,
    ) -> list[str]:
        """查询玩家当前场景可达的目标场景列表。"""
        self._ensure_known_player(session_state, player_id)
        player_state = session_state.player_states[player_id]
        module = self._load_module(session_state.module_id)
        movement_rules = self._movement_rules(
            module=module,
            flags=session_state.global_flags,
            stage_id=session_state.story_state.current_stage_id,
        )
        return movement_rules.list_reachable_scenes(
            from_scene_id=player_state.current_scene_id
        )

    def render_narration_after_turn(
        self,
        resolution: TurnResolution,
        pipeline: "NarrationPipeline",
        *,
        forbidden_facts: list[str] | None = None,
        max_prompt_chars: int | None = None,
    ) -> "KeeperNarrationRecord":
        """Run an explicit post-resolution narration hook.

        The helper deep-copies committed session state and passes it to the
        narration layer. It does not change resolve_turn() semantics and does
        not mutate authoritative session fields.
        """

        session_snapshot = self._get_session(resolution.session_id).model_copy(
            deep=True
        )
        module = self._load_module(session_snapshot.module_id)
        return pipeline.render_after_turn(
            resolution=resolution,
            session_snapshot=session_snapshot,
            module=module,
            forbidden_facts=forbidden_facts or [],
            max_prompt_chars=max_prompt_chars,
        )

    def list_available_actions(
        self,
        session_state: SessionMapState,
        player_id: str,
    ) -> list[ModuleAction]:
        """查询玩家当前位置当前可执行的动作。"""
        self._ensure_known_player(session_state, player_id)
        player_state = session_state.player_states[player_id]
        module = self._load_module(session_state.module_id)

        available_actions: list[ModuleAction] = []
        for action in module.actions:
            if action.scene_id != player_state.current_scene_id:
                continue
            available, _ = self._rule_engine.can_execute_action(
                action=action,
                session=session_state,
                player_id=player_id,
            )
            if available:
                available_actions.append(action)
        return available_actions

    def _load_module(self, module_id: str) -> ModuleDefinition:
        """加载并缓存模组定义。"""
        if module_id not in self._module_cache:
            self._module_cache[module_id] = load_module_by_id(
                module_id,
                module_root=self._module_root,
            )
        return self._module_cache[module_id]

    def _get_session(self, session_id: str) -> SessionMapState:
        """按会话 ID 读取内存态会话。"""
        if session_id not in self._sessions:
            raise KeyError(f"未知会话: {session_id}")
        return self._sessions[session_id]

    def _movement_rules(
        self,
        *,
        module: ModuleDefinition,
        flags: set[str],
        stage_id: str,
    ) -> SceneMovementRules:
        """基于当前 flags/stage 构造当回合移动规则实例。"""
        scene_links = [
            SceneLink(
                from_scene_id=link.from_scene_id,
                to_scene_id=link.to_scene_id,
                required_flags=list(link.required_flags),
                required_stages=list(link.required_stages),
                block_reason=link.block_reason,
            )
            for link in module.links
        ]
        return SceneMovementRules(
            scene_links=scene_links,
            active_flags=flags,
            active_stage_id=stage_id,
        )

    def _group_pending_intents(
        self,
        session: SessionMapState,
    ) -> dict[str, list[tuple[str, dict[str, object]]]]:
        """按玩家所在场景对待结算意图分组。"""
        grouped: dict[str, list[tuple[str, dict[str, object]]]] = defaultdict(list)
        for player_id, intent in session.pending_intents.items():
            scene_id = session.player_states[player_id].current_scene_id
            grouped[scene_id].append((player_id, intent))
        return grouped

    def _build_story_signals(
        self,
        *,
        events: list[RuntimeEvent],
        triggered_clock_events: list[str],
        turn_no: int,
    ) -> list[StorySignal]:
        """把运行时事件映射为剧情状态机可消费的信号。"""
        signals: list[StorySignal] = []
        for event in events:
            if event.type == "movement_committed":
                signals.append(
                    StorySignal(
                        type="scene_entered",
                        turn_no=turn_no,
                        player_id=event.player_id,
                        scene_id=event.to_scene_id,
                    )
                )
            elif event.type == "action_resolved" and event.success is True:
                signals.append(
                    StorySignal(
                        type="action_succeeded",
                        turn_no=turn_no,
                        player_id=event.player_id,
                        scene_id=event.scene_id,
                        action_id=event.action_id,
                    )
                )
        for trigger_value in triggered_clock_events:
            clock_id, _, threshold_text = trigger_value.partition(":")
            signals.append(
                StorySignal(
                    type="clock_threshold_triggered",
                    turn_no=turn_no,
                    clock_id=clock_id,
                    threshold=int(threshold_text),
                )
            )
        return signals

    def _ensure_known_player(
        self,
        session_state: SessionMapState,
        player_id: str,
    ) -> None:
        """校验玩家存在于会话中。"""
        if player_id not in session_state.player_states:
            raise KeyError(f"未知玩家: {player_id}")
