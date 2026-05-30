"""PromptBuilder：从会话快照构造 AgentPlanPrompt。

设计说明：
- 分层构建，各层可独立缓存以节省 token。
- 不依赖 LLM，只做信息聚合与格式化。
- 输出为 AgentPlanPrompt，可直接序列化为 JSON 传入 BaseAgent.call()。
"""

from __future__ import annotations

import logging
from typing import Sequence

from ..context import NarrativeContextLayer, NarrativeContextSelector
from ..module.models import ModuleDefinition
from ..session.state import SessionMapState
from ..story.models import StoryState
from .models import (
    AgentPlanPrompt,
    HistoryLayer,
    KeeperPrivateLayer,
    ModuleLayer,
    PlayerIntentSummary,
    SpatialLayer,
    SystemLayer,
)

logger = logging.getLogger(__name__)

# 历史层默认保留最近 N 条事件
_DEFAULT_HISTORY_SIZE = 10

# COC 7e 规则摘要（固定文本，可外部注入覆盖）
_DEFAULT_COC_RULE_SUMMARY = """\
【COC 7e 核心规则摘要】
- 技能值表示成功概率（%）；掷 d100 ≤ 技能值为普通成功。
- 成功等级：极难成功（≤ 技能值/5）、困难成功（≤ 技能值/2）、普通成功（≤ 技能值）、失败（> 技能值）。
- 大成功（Fumble）：96-100（低技能值时触发更易）；关键成功（Bonus die）视场景而定。
- 对抗检定：双方各掷检定，成功等级更高者胜。
- SAN 值归零或失去大量 SAN 可能导致暂时性/长期性精神失常。
"""


class PromptBuilder:
    """从运行时数据构建 AgentPlanPrompt。

    通常在每个 SceneTurnBatch 处理前调用一次，
    为 KeeperPlanAgent 提供分层上下文。

    Example::

        builder = PromptBuilder()
        prompt = builder.build(
            session=session,
            module=module_def,
            scene_id="foyer",
            recent_events=event_log[-10:],
        )
        record = await plan_agent.call(prompt)
    """

    def __init__(
        self,
        *,
        coc_rule_summary: str = _DEFAULT_COC_RULE_SUMMARY,
        keeper_role_hint: str = "你是 Call of Cthulhu 桌游的守密人，负责裁定玩家行动并推进故事。",
        history_size: int = _DEFAULT_HISTORY_SIZE,
        narrative_selector: NarrativeContextSelector | None = None,
    ) -> None:
        """
        Args:
            coc_rule_summary: COC 规则摘要文本，可注入自定义内容。
            keeper_role_hint: 守密人角色 system 提示。
            history_size: 纳入历史层的最多事件数。
        """
        self._coc_rule_summary = coc_rule_summary
        self._keeper_role_hint = keeper_role_hint
        self._history_size = history_size
        self._narrative_selector = narrative_selector or NarrativeContextSelector()

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def build(
        self,
        *,
        session: SessionMapState,
        module: ModuleDefinition,
        scene_id: str,
        recent_events: Sequence[object] | None = None,
        keeper_hidden_notes: str = "",
        pending_intents: dict[str, dict[str, object]] | None = None,
    ) -> AgentPlanPrompt:
        """构造 AgentPlanPrompt。

        Args:
            session: 当前会话快照。
            module: 当前模组静态定义。
            scene_id: 本批次处理的场景 ID。
            recent_events: 最近 N 轮运行时事件（倒序或正序均可，builder 内部截取）。
            keeper_hidden_notes: 可选的守密人私有备注（从外部传入，不自动生成）。
            pending_intents: 可选的待结算意图快照；未提供时读取 session.pending_intents。

        Returns:
            AgentPlanPrompt：可直接传入 KeeperPlanAgent.call()。
        """
        system = self._build_system_layer()
        narrative = self.build_narrative_context(
            session=session,
            module=module,
            scene_id=scene_id,
            recent_events=recent_events or [],
            pending_intents=pending_intents,
            include_keeper=True,
        )
        module_layer = self._build_module_layer(
            session=session,
            module=module,
            narrative=narrative,
        )
        spatial = self._build_spatial_layer(
            session=session, module=module, scene_id=scene_id
        )
        history = self._build_history_layer(recent_events=recent_events or [])
        keeper_private = self._build_keeper_private_layer(
            hidden_notes=keeper_hidden_notes
        )
        pending_intents = self._build_pending_intents(
            session=session,
            module=module,
            scene_id=scene_id,
            pending_intents=pending_intents,
        )

        return AgentPlanPrompt(
            session_id=session.session_id,
            turn_no=session.current_turn,
            scene_id=scene_id,
            system=system,
            module=module_layer,
            spatial=spatial,
            history=history,
            keeper_private=keeper_private,
            narrative=narrative,
            pending_intents=pending_intents,
        )

    def build_narrative_context(
        self,
        *,
        session: SessionMapState,
        module: ModuleDefinition,
        scene_id: str,
        recent_events: Sequence[object] | None = None,
        pending_intents: dict[str, dict[str, object]] | None = None,
        include_keeper: bool = True,
    ) -> NarrativeContextLayer:
        return self._narrative_selector.select(
            session=session,
            module=module,
            scene_id=scene_id,
            recent_events=recent_events or [],
            pending_intents=pending_intents,
            include_keeper=include_keeper,
        )

    # ------------------------------------------------------------------
    # 各层构建方法
    # ------------------------------------------------------------------

    def _build_system_layer(self) -> SystemLayer:
        return SystemLayer(
            coc_version="7e",
            rule_summary=self._coc_rule_summary,
            keeper_role_hint=self._keeper_role_hint,
        )

    def _build_module_layer(
        self,
        *,
        session: SessionMapState,
        module: ModuleDefinition,
        narrative: NarrativeContextLayer,
    ) -> ModuleLayer:
        story: StoryState = session.story_state
        stage_map = module.story_stage_map()
        current_stage = stage_map.get(story.current_stage_id)
        stage_description = current_stage.description if current_stage else ""

        # 收集当前阶段可触发的迁移 ID（source_stage_id 对应当前阶段）
        available_transition_ids = [
            t.id
            for t in module.story_transitions
            if t.source_stage_id == story.current_stage_id
        ]

        return ModuleLayer(
            module_id=module.module_id,
            module_title=module.title,
            worldview_brief=narrative.worldview_brief,
            current_stage_id=story.current_stage_id,
            current_stage_description=stage_description,
            available_transition_ids=available_transition_ids,
        )

    def _build_spatial_layer(
        self,
        *,
        session: SessionMapState,
        module: ModuleDefinition,
        scene_id: str,
    ) -> SpatialLayer:
        scene_map = module.scene_map()
        scene = scene_map.get(scene_id)

        # 当前场景可到达的邻接场景（基于 module links）
        reachable_scene_ids = [
            link.to_scene_id for link in module.links if link.from_scene_id == scene_id
        ]

        # 当前场景可执行的动作
        available_action_ids = [
            action.id for action in module.actions if action.scene_id == scene_id
        ]

        # 在场玩家
        present_player_ids = [
            pid
            for pid, ps in session.player_states.items()
            if ps.current_scene_id == scene_id
        ]

        # 在场玩家的技能 key 列表，供 Agent 选择检定技能时参考
        player_skill_keys: dict[str, list[str]] = {
            pid: sorted(session.player_states[pid].investigator.skills.keys())
            for pid in present_player_ids
        }

        return SpatialLayer(
            scene_id=scene_id,
            scene_name=scene.name if scene else scene_id,
            scene_description=scene.description if scene else "",
            present_player_ids=present_player_ids,
            reachable_scene_ids=reachable_scene_ids,
            available_action_ids=available_action_ids,
            global_flags=sorted(session.global_flags),
            clock_values=dict(session.clock_values),
            player_skill_keys=player_skill_keys,
        )

    def _build_history_layer(
        self, *, recent_events: Sequence[object]
    ) -> HistoryLayer:
        # 取最近 N 条事件的 message 作为摘要
        summaries = [
            str(message)
            for event in recent_events[-self._history_size :]
            if (message := getattr(event, "message", ""))
        ]
        return HistoryLayer(
            recent_events_summary=summaries,
            max_events=self._history_size,
        )

    def _build_keeper_private_layer(
        self, *, hidden_notes: str = ""
    ) -> KeeperPrivateLayer:
        return KeeperPrivateLayer(hidden_notes=hidden_notes)

    def _build_pending_intents(
        self,
        *,
        session: SessionMapState,
        module: ModuleDefinition,
        scene_id: str,
        pending_intents: dict[str, dict[str, object]] | None = None,
    ) -> list[PlayerIntentSummary]:
        """从 pending_intents 中筛选出本场景的意图并丰富语义信息。"""
        action_map = module.action_map()
        result: list[PlayerIntentSummary] = []

        intent_map = (
            pending_intents if pending_intents is not None else session.pending_intents
        )
        for player_id, raw_intent in intent_map.items():
            # 只处理当前在本场景的玩家意图
            ps = session.player_states.get(player_id)
            if ps is None or ps.current_scene_id != scene_id:
                continue

            intent_type = str(raw_intent.get("type", ""))
            if intent_type == "move":
                result.append(
                    PlayerIntentSummary(
                        player_id=player_id,
                        intent_type="move",
                        target_scene_id=str(raw_intent.get("target_scene_id", "")),
                    )
                )
            elif intent_type == "action":
                action_id = str(raw_intent.get("action_id", ""))
                action = action_map.get(action_id)
                result.append(
                    PlayerIntentSummary(
                        player_id=player_id,
                        intent_type="action",
                        action_id=action_id,
                        action_name=action.name if action else action_id,
                        action_description=action.description if action else "",
                    )
                )
            elif intent_type == "observe":
                result.append(
                    PlayerIntentSummary(
                        player_id=player_id,
                        intent_type="observe",
                        observation_text=str(raw_intent.get("text", "")),
                    )
                )
            else:
                logger.warning(
                    "PromptBuilder: 未知意图类型 %s，player_id=%s",
                    intent_type,
                    player_id,
                )

        return result
