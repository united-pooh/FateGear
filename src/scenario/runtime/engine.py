"""基于 YAML 模组定义的最小场景运行时。"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from cards.domain.card import InvestigatorCard

from ..agent.models import AuthorizedPrivateClue, CommitResult, KeeperAgentPlan
from ..agent.plan_agent import KeeperPlanAgent
from ..agent.prompt_builder import PromptBuilder
from ..agent.render_agent import KeeperRenderAgent
from ..io.module_loader import MODULE_ROOT, load_module_by_id
from ..module.models import ModuleAction, ModuleDefinition
from ..scene.models import SceneLink
from ..scene.rules import SceneMovementRules
from ..session.state import SceneInstanceState, SessionMapState, SessionPlayerState
from ..story.models import StorySignal, StoryState
from ..story.services import StoryStateService, TransitionValidator
from .contracts import (
    AgentCallAudit,
    DiceRollAudit,
    IntentResolution,
    MoveIntent,
    ObserveIntent,
    RuntimeEvent,
    SCENE_INTENT_ADAPTER,
    SceneBatchResolution,
    SceneIntent,
    TurnResolution,
)
from .rule_engine import RollProvider, RuleEngine

if TYPE_CHECKING:
    from ..store import ScenarioStateStore

logger = logging.getLogger(__name__)


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
        state_store: "ScenarioStateStore | None" = None,
    ) -> None:
        """
        Args:
            module_root: 模组根目录，默认从 MODULE_ROOT 读取。
            roll_provider: 骰子随机数提供者（测试时可注入固定值）。
            rule_engine: 规则引擎，默认自动创建。
            plan_agent: Plan 阶段 Agent；为 None 时跳过 Planner，规则引擎按 YAML 默认逻辑处理。
            render_agent: Render 阶段 Agent；为 None 时 SceneBatchResolution.narration 为 None。
            prompt_builder: PromptBuilder；为 None 时若 plan_agent 不为 None 则自动创建默认实例。
            state_store: 可选持久化存储；传入后会自动恢复会话并在状态变化后落盘。
        """
        self._module_root = (
            Path(module_root) if module_root is not None else MODULE_ROOT
        )
        self._sessions: dict[str, SessionMapState] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._turn_history: dict[str, dict[int, TurnResolution]] = defaultdict(dict)
        self._state_store = state_store
        self._module_cache: dict[str, ModuleDefinition] = {}
        self._transition_validator = TransitionValidator()
        self._story_state_service = StoryStateService()
        self._rule_engine = rule_engine or RuleEngine(roll_provider=roll_provider)
        self._plan_agent = plan_agent
        self._render_agent = render_agent
        # 如果传入了 Agent 但没有传 prompt_builder，则自动创建默认实例
        self._prompt_builder = prompt_builder or (
            PromptBuilder()
            if plan_agent is not None or render_agent is not None
            else None
        )
        self._restore_persisted_state()

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
        self._session_locks[session_id] = asyncio.Lock()
        self._persist_session(session)
        return session

    def destroy_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._session_locks.pop(session_id, None)
        self._turn_history.pop(session_id, None)
        if self._state_store is not None:
            self._state_store.delete_session(session_id)

    def get_session(self, session_id: str) -> SessionMapState:
        return self._get_session(session_id)

    def list_session_ids(self) -> list[str]:
        """列出当前运行时已加载的会话 ID。"""
        return sorted(self._sessions)

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
        self._persist_session(session)
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
        elif not isinstance(validated, ObserveIntent):
            if validated.action_id not in module.action_map():
                raise ValueError(
                    f"玩家 {player_id} 提交了不存在的动作: {validated.action_id}"
                )

        session.pending_intents[player_id] = validated.model_dump()
        self._persist_session(session)

    async def resolve_turn(
        self,
        session_id: str,
        *,
        expected_turn: int | None = None,
    ) -> TurnResolution:
        """结算一个完整回合（异步）。

        流程：
        1. 读取快照，按场景分批分组
        2. 每批次：[Plan Agent] → [规则引擎 + 动态检定] → [提交效果] → [Render Agent]
        3. 跨批次：推进时钟 / 触发时钟事件 / 计算剧情迁移 / 写 event_log

        若 ``plan_agent`` 未配置，步骤 2 中的 Plan 阶段被跳过，
        规则引擎按 YAML 定义的静态检定与效果运行（与原有行为完全兼容）。
        若 ``render_agent`` 未配置，``SceneBatchResolution.narration`` 保持 None。
        """
        lock = self._get_session_lock(session_id)
        async with lock:
            return await self._resolve_turn_locked(
                session_id,
                expected_turn=expected_turn,
            )

    def get_turn_resolution(self, session_id: str, turn_no: int) -> TurnResolution:
        """读取已结算回合结果，用于回放或重复请求幂等返回。"""
        self._get_session(session_id)
        resolution = self._turn_history.get(session_id, {}).get(turn_no)
        if resolution is None:
            raise KeyError(f"会话 {session_id} 不存在已结算回合: {turn_no}")
        return resolution.model_copy(deep=True)

    def list_resolved_turns(self, session_id: str) -> list[int]:
        """列出已结算回合编号。"""
        self._get_session(session_id)
        return sorted(self._turn_history.get(session_id, {}))

    async def _resolve_turn_locked(
        self,
        session_id: str,
        *,
        expected_turn: int | None = None,
    ) -> TurnResolution:
        """持有会话异步锁时执行一次权威回合结算。"""
        session = self._get_session(session_id)
        requested_turn = expected_turn or session.current_turn
        if requested_turn < session.current_turn:
            return self.get_turn_resolution(session_id, requested_turn)
        if requested_turn > session.current_turn:
            raise ValueError(
                f"会话 {session_id} 当前是第 {session.current_turn} 回合，"
                f"不能提前结算第 {requested_turn} 回合"
            )
        if (
            session.resolved_ending is not None
            or session.story_state.resolved_ending_id is not None
        ):
            raise ValueError(f"会话 {session_id} 已进入结局，不能继续结算")

        # 使用深拷贝快照做“判定输入”，避免中途写入影响同回合后续判定。
        snapshot = session.model_copy(deep=True)
        module = self._load_module(session.module_id)
        scene_by_id = module.scene_map()
        action_by_id = module.action_map()
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
        dice_rolls: list[DiceRollAudit] = []
        agent_calls: list[AgentCallAudit] = []

        flag_sets: set[str] = set()
        flag_clears: set[str] = set()
        clock_deltas: dict[str, int] = defaultdict(int)
        completed_actions: set[str] = set()
        scene_events: set[str] = set()
        scene_clears: set[str] = set()
        scene_action_history: dict[str, set[str]] = defaultdict(set)
        pending_moves: dict[str, str] = {}
        scene_batches: list[SceneBatchResolution] = []
        render_payloads: dict[
            str, tuple[list[dict], list[str], list[AuthorizedPrivateClue]]
        ] = {}

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
            agent_prompt = None
            # 本批次 Agent 提议的动态检定结果，key 为 (player_id, action_id)
            dynamic_check_results: dict[tuple[str, str], dict] = {}
            pending_action_ids_by_player: dict[str, set[str]] = defaultdict(set)
            for pending_player_id, pending_payload in intents:
                if str(pending_payload.get("type", "")) == "action":
                    pending_action_ids_by_player[pending_player_id].add(
                        str(pending_payload.get("action_id", ""))
                    )

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
                    agent_calls.append(
                        self._build_agent_call_audit(
                            stage="plan",
                            turn_no=snapshot.current_turn,
                            scene_id=scene.id,
                            scene_name=scene.name,
                            record=plan_record,
                            selected_context_ids=agent_prompt.narrative.selected_ids,
                            output_summary={
                                "proposed_checks": len(plan.proposed_checks),
                                "proposed_effects": len(plan.proposed_effects),
                                "has_transition": (
                                    plan.proposed_transition is not None
                                ),
                            },
                        )
                    )
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
                        if proposed.action_id not in pending_action_ids_by_player.get(
                            proposed.player_id,
                            set(),
                        ):
                            logger.info(
                                "Plan Agent 提议的检定未绑定本轮动作，已跳过："
                                "player=%s action=%s skill=%s",
                                proposed.player_id,
                                proposed.action_id,
                                proposed.skill_key,
                            )
                            continue
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
                        dice_rolls.append(
                            self._build_dice_roll_audit(
                                source="dynamic_agent_check",
                                turn_no=snapshot.current_turn,
                                scene_id=scene.id,
                                scene_name=scene.name,
                                action=action_by_id.get(proposed.action_id),
                                result=result,
                            )
                        )
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
            batch_authorized_clues: list[AuthorizedPrivateClue] = []

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
                                + (
                                    f"，原因：{decision.reason}"
                                    if decision.reason
                                    else ""
                                )
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

                if isinstance(intent, ObserveIntent):
                    current_scene_name = scene_by_id[player_state.current_scene_id].name
                    event_log.append(
                        RuntimeEvent(
                            type="observation_requested",
                            turn_no=snapshot.current_turn,
                            player_id=player_id,
                            scene_id=player_state.current_scene_id,
                            scene_name=current_scene_name,
                            success=True,
                            reason=intent.text,
                            message=(
                                f"玩家 {player_id} 在"
                                f"{current_scene_name}（{player_state.current_scene_id}）"
                                f"观察环境：{intent.text}"
                            ),
                        )
                    )
                    outcomes.append(
                        IntentResolution(
                            player_id=player_id,
                            scene_id=player_state.current_scene_id,
                            intent_type="observe",
                            success=True,
                            reason="观察环境，不触发模组动作。",
                            observation_text=intent.text,
                        )
                    )
                    continue

                action = action_by_id[intent.action_id]
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
                    check_passed, check_reason, failure_effects, check_detail = (
                        self._rule_engine.resolve_action_check_detail(
                            action=action,
                            player_state=player_state,
                            flag_sets=flag_sets,
                            flag_clears=flag_clears,
                            clock_deltas=clock_deltas,
                        )
                    )
                    if check_detail is not None:
                        batch_resolved_checks.append(check_detail)
                        dice_rolls.append(
                            self._build_dice_roll_audit(
                                source="static_action_check",
                                turn_no=snapshot.current_turn,
                                scene_id=scene.id,
                                scene_name=scene.name,
                                action=action,
                                result=check_detail,
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
                batch_authorized_clues.extend(
                    self._authorized_clues_for_action(
                        module=module,
                        action=action,
                        player_id=player_id,
                    )
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

            batch_effects: list[str] = []
            for outcome in outcomes:
                batch_effects.extend(outcome.effects_applied)
            render_payloads[scene.id] = (
                batch_resolved_checks,
                batch_effects,
                batch_authorized_clues,
            )

            scene_batches.append(
                SceneBatchResolution(
                    scene_id=scene.id,
                    player_ids=batch_player_ids,
                    outcomes=outcomes,
                    narration=None,
                )
            )

        # 批次处理结束后统一提交状态，先清空待结算意图。
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
        await self._render_scene_batches(
            session=session,
            module=module,
            scene_by_id=scene_by_id,
            snapshot_turn=snapshot.current_turn,
            scene_batches=scene_batches,
            render_payloads=render_payloads,
            event_log=event_log,
            agent_calls=agent_calls,
            applied_story_transition_id=applied_story_transition_id,
            new_stage=new_stage,
            resolved_ending=resolved_ending,
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
        resolution = TurnResolution(
            session_id=session_id,
            turn_no=snapshot.current_turn,
            next_turn=session.current_turn,
            scene_batches=scene_batches,
            event_log=event_log,
            dice_rolls=dice_rolls,
            agent_calls=agent_calls,
            applied_flags=applied_flags,
            applied_clock_deltas=combined_clock_deltas,
            triggered_clock_events=triggered_clock_events,
            clock_values=dict(session.clock_values),
            story_signals=story_signals,
            current_stage_id=session.story_state.current_stage_id,
            new_stage=new_stage,
            applied_story_transition_id=applied_story_transition_id,
            resolved_ending=resolved_ending,
            ending_result=ending_result,
        )
        self._turn_history[session_id][resolution.turn_no] = resolution.model_copy(
            deep=True
        )
        self._persist_turn_resolution(resolution)
        self._persist_session(session)
        return resolution

    async def _render_scene_batches(
        self,
        *,
        session: SessionMapState,
        module: ModuleDefinition,
        scene_by_id: dict[str, object],
        snapshot_turn: int,
        scene_batches: list[SceneBatchResolution],
        render_payloads: dict[
            str, tuple[list[dict], list[str], list[AuthorizedPrivateClue]]
        ],
        event_log: list[RuntimeEvent],
        agent_calls: list[AgentCallAudit],
        applied_story_transition_id: str | None,
        new_stage: str | None,
        resolved_ending: str | None,
    ) -> None:
        """在权威提交后，为每个场景批次生成只读叙事。"""
        for batch in scene_batches:
            scene = scene_by_id[batch.scene_id]
            if self._render_agent is None:
                event_log.append(
                    RuntimeEvent(
                        type="render_agent_skipped",
                        turn_no=snapshot_turn,
                        scene_id=batch.scene_id,
                        scene_name=scene.name,
                        message=(
                            f"Render Agent 未配置，scene={batch.scene_id} 无叙事输出"
                        ),
                    )
                )
                continue

            resolved_checks, batch_effects, authorized_private_clues = (
                render_payloads.get(batch.scene_id, ([], [], []))
            )
            pending_intents = {
                outcome.player_id: {
                    "type": outcome.intent_type,
                    **(
                        {"action_id": outcome.action_id}
                        if outcome.action_id
                        else {}
                    ),
                    **(
                        {"target_scene_id": outcome.target_scene_id}
                        if outcome.target_scene_id
                        else {}
                    ),
                    **(
                        {"text": outcome.observation_text}
                        if outcome.observation_text
                        else {}
                    ),
                }
                for outcome in batch.outcomes
            }
            render_narrative = (
                self._prompt_builder.build_narrative_context(
                    session=session,
                    module=module,
                    scene_id=batch.scene_id,
                    recent_events=event_log,
                    pending_intents=pending_intents,
                    include_keeper=False,
                )
                if self._prompt_builder is not None
                else None
            )
            commit = CommitResult(
                session_id=session.session_id,
                turn_no=snapshot_turn,
                scene_id=batch.scene_id,
                scene_name=scene.name,
                scene_description=scene.description,
                resolved_checks=resolved_checks,
                applied_effects=batch_effects,
                applied_transition_id=applied_story_transition_id,
                new_stage_id=new_stage,
                resolved_ending=resolved_ending,
                event_summary=[e.message for e in event_log[-10:]],
                outcomes=[outcome.model_dump() for outcome in batch.outcomes],
                authorized_private_clues=authorized_private_clues,
                **(
                    {"narrative": render_narrative}
                    if render_narrative is not None
                    else {}
                ),
            )
            try:
                render_record = await self._render_agent.call(commit)
                batch.narration = render_record.output
                agent_calls.append(
                    self._build_agent_call_audit(
                        stage="render",
                        turn_no=snapshot_turn,
                        scene_id=batch.scene_id,
                        scene_name=scene.name,
                        record=render_record,
                        selected_context_ids=commit.narrative.selected_ids,
                        output_summary={
                            "npc_dialogues": len(
                                getattr(
                                    render_record.output,
                                    "npc_dialogues",
                                    [],
                                )
                                or []
                            ),
                            "private_clues": len(
                                getattr(
                                    render_record.output,
                                    "private_clues",
                                    [],
                                )
                                or []
                            ),
                            "is_fallback": bool(
                                getattr(
                                    render_record.output,
                                    "is_fallback",
                                    False,
                                )
                            ),
                        },
                    )
                )
                event_log.append(
                    RuntimeEvent(
                        type="render_agent_called",
                        turn_no=snapshot_turn,
                        scene_id=batch.scene_id,
                        scene_name=scene.name,
                        fallback_used=render_record.meta.fallback_used,
                        message=(
                            f"Render Agent 调用完成（scene={batch.scene_id}，"
                            f"fallback={render_record.meta.fallback_used}）"
                        ),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Render Agent 调用失败（scene=%s）：%s",
                    batch.scene_id,
                    exc,
                )
                event_log.append(
                    RuntimeEvent(
                        type="render_agent_skipped",
                        turn_no=snapshot_turn,
                        scene_id=batch.scene_id,
                        scene_name=scene.name,
                        message=f"Render Agent 调用失败（scene={batch.scene_id}）：{exc}",
                    )
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

    def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        """按会话 ID 读取异步锁，确保 resolve_turn 不会双提交。"""
        self._get_session(session_id)
        lock = self._session_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[session_id] = lock
        return lock

    def _restore_persisted_state(self) -> None:
        """从持久化存储恢复会话和已结算回合。"""
        if self._state_store is None:
            return
        self._sessions = {
            session_id: session.model_copy(deep=True)
            for session_id, session in self._state_store.load_sessions().items()
        }
        self._session_locks = {
            session_id: asyncio.Lock() for session_id in self._sessions
        }
        self._turn_history = defaultdict(dict)
        for session_id in self._sessions:
            self._turn_history[session_id].update(
                self._state_store.load_turns(session_id)
            )

    def _persist_session(self, session: SessionMapState) -> None:
        """保存最新权威会话快照。"""
        if self._state_store is None:
            return
        self._state_store.save_session(session)

    def _persist_turn_resolution(self, resolution: TurnResolution) -> None:
        """保存已结算回合，供客户端幂等重放。"""
        if self._state_store is None:
            return
        self._state_store.save_turn(resolution)

    def _build_dice_roll_audit(
        self,
        *,
        source: str,
        turn_no: int,
        scene_id: str,
        scene_name: str,
        action: ModuleAction | None,
        result: dict,
    ) -> DiceRollAudit:
        return DiceRollAudit(
            source=source,
            turn_no=turn_no,
            player_id=str(result.get("player_id", "")),
            scene_id=scene_id,
            scene_name=scene_name,
            action_id=str(result.get("action_id") or getattr(action, "id", "")),
            action_name=getattr(action, "name", ""),
            skill_key=str(result.get("skill_key", "")),
            difficulty=str(result.get("difficulty", "")),
            proposed_difficulty=str(result.get("proposed_difficulty", "")),
            roll_value=int(result.get("roll_value", 0) or 0),
            threshold=int(result.get("threshold", 0) or 0),
            success=bool(result.get("success", False)),
            success_level=str(result.get("success_level", "")),
            reason=str(result.get("reason", "")),
            note=str(result.get("note", "")),
        )

    def _authorized_clues_for_action(
        self,
        *,
        module: ModuleDefinition,
        action: ModuleAction,
        player_id: str,
    ) -> list[AuthorizedPrivateClue]:
        """返回本轮动作明确触发、允许 Render 写入 private_clues 的线索。"""
        clues: list[AuthorizedPrivateClue] = []
        for entry in module.narrative_context.lorebook_entries:
            if action.id not in entry.scope_action_ids:
                continue
            if entry.visibility == "keeper":
                continue
            clues.append(
                AuthorizedPrivateClue(
                    player_id=player_id,
                    clue_text=entry.content,
                    related_action_id=action.id,
                    source_id=f"lore:{entry.id}",
                )
            )
        return clues

    def _build_agent_call_audit(
        self,
        *,
        stage: str,
        turn_no: int,
        scene_id: str,
        scene_name: str,
        record: object,
        selected_context_ids: list[str],
        output_summary: dict[str, object],
    ) -> AgentCallAudit:
        meta = getattr(record, "meta", None)
        return AgentCallAudit(
            stage=stage,
            turn_no=turn_no,
            scene_id=scene_id,
            scene_name=scene_name,
            model_id=str(getattr(meta, "model_id", "")),
            latency_ms=int(getattr(meta, "latency_ms", 0) or 0),
            attempt=int(getattr(meta, "attempt", 1) or 1),
            fallback_used=bool(getattr(meta, "fallback_used", False)),
            input_tokens=int(getattr(meta, "input_tokens", 0) or 0),
            output_tokens=int(getattr(meta, "output_tokens", 0) or 0),
            selected_context_ids=list(selected_context_ids),
            output_summary=output_summary,
        )

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
