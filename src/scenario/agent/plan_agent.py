"""KeeperPlanAgent：Plan 阶段的 Agent 实现。

职责：
- 接受 AgentPlanPrompt，向 LLM 发起调用，返回 KeeperAgentPlan。
- Plan 中的所有内容均为"提议"，由 RuleEngine / TransitionValidator 校验后才生效。
- 内置降级策略：LLM 不可用时返回空提议（pass-through 模式），由规则引擎按默认逻辑处理。

LLM 后端：
- 默认实现使用 OpenAI Chat Completions API（structured outputs 模式）。
- 可通过子类覆盖 ``_call_llm`` 切换为其他后端（Azure、本地 GGUF、Claude 等）。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from ..context import NarrativeContextLayer
from .base import AgentOutputError, BaseAgent
from .config import (
    AgentSettings,
    build_openai_client,
    detect_provider_kind,
    load_agent_settings,
)
from .models import AgentPlanPrompt, KeeperAgentPlan

logger = logging.getLogger(__name__)


def _build_system_message(prompt: AgentPlanPrompt) -> str:
    """从 prompt 分层内容拼接 system message 文本。"""
    lines: list[str] = []

    # 永久层
    sys_layer = prompt.system
    lines.append(sys_layer.keeper_role_hint)
    if sys_layer.rule_summary:
        lines.append(sys_layer.rule_summary)

    # 模组层
    mod = prompt.module
    if mod.worldview_brief:
        lines.append(f"【世界观】{mod.worldview_brief}")
    lines.append(f"【当前剧情阶段：{mod.current_stage_id}】")
    if mod.current_stage_description:
        lines.append(mod.current_stage_description)
    if mod.available_transition_ids:
        lines.append(
            "【可触发剧情迁移（仅参考，不代表授权）】"
            + "、".join(mod.available_transition_ids)
        )

    # 叙事上下文：只读指导，不改变规则权威。
    narrative = getattr(prompt, "narrative", NarrativeContextLayer())
    if narrative.has_content():
        lines.append("【只读叙事上下文：不得直接改写 flag、clock 或剧情迁移】")
    if narrative.atmosphere.tone:
        lines.append(f"氛围基调：{narrative.atmosphere.tone}")
    if narrative.atmosphere.sensory_palette:
        lines.append("感官词库：" + "、".join(narrative.atmosphere.sensory_palette))
    if narrative.atmosphere.pacing_hint:
        lines.append(f"节奏提示：{narrative.atmosphere.pacing_hint}")
    if narrative.atmosphere.escalation_rules:
        lines.append("张力推进：" + "；".join(narrative.atmosphere.escalation_rules))
    if narrative.atmosphere.forbidden_reveals:
        lines.append(
            "禁止提前揭示：" + "；".join(narrative.atmosphere.forbidden_reveals)
        )
    prose = narrative.prose_controls
    if narrative.has_content():
        lines.append(
            "KP写法："
            f"语言={prose.language}；"
            f"人称={prose.narrative_person}；"
            f"时态={prose.tense}；"
            f"段落上限={prose.paragraph_limit}；"
            f"恐怖强度={prose.horror_intensity}；"
            f"骰点呈现={prose.dice_visibility}；"
            f"线索公平={prose.clue_fairness}"
        )
    if prose.style_rules:
        lines.append("文风规则：" + "；".join(prose.style_rules))
    if narrative.selected_safety_boundaries:
        lines.append("【安全边界】")
        for boundary in narrative.selected_safety_boundaries:
            lines.append(f"- {boundary.severity}:{boundary.note}")
    if narrative.selected_npcs:
        lines.append("【在场/相关 NPC 人设卡】")
        for npc in narrative.selected_npcs:
            npc_parts = [
                f"{npc.name}({npc.npc_id})",
                npc.role,
                npc.public_description,
                f"人设：{npc.persona}" if npc.persona else "",
                f"口吻：{npc.speaking_style}" if npc.speaking_style else "",
                (
                    f"知识边界：{npc.knowledge_boundary}"
                    if npc.knowledge_boundary
                    else ""
                ),
            ]
            if npc.goals:
                npc_parts.append("目标：" + "；".join(npc.goals))
            if npc.secrets:
                npc_parts.append("守密人秘密：" + "；".join(npc.secrets))
            lines.append("；".join(part for part in npc_parts if part))

    # 守密人私有层
    priv = prompt.keeper_private
    if priv.hidden_notes:
        lines.append(f"【守密人备注（玩家不可见）】{priv.hidden_notes}")
    if priv.npc_hidden_states:
        npc_desc = "；".join(
            f"{nid}: {state}" for nid, state in priv.npc_hidden_states.items()
        )
        lines.append(f"【NPC 隐藏状态】{npc_desc}")

    return "\n".join(lines)


def _build_user_message(prompt: AgentPlanPrompt) -> str:
    """从 prompt 的空间层、历史层和意图列表拼接 user message 文本。"""
    lines: list[str] = []

    # 空间层
    sp = prompt.spatial
    lines.append(f"【当前场景：{sp.scene_name}（{sp.scene_id}）】")
    if sp.scene_description:
        lines.append(sp.scene_description)
    if sp.present_player_ids:
        lines.append(f"在场玩家：{', '.join(sp.present_player_ids)}")
    if sp.available_action_ids:
        lines.append(f"可用动作：{', '.join(sp.available_action_ids)}")
    if sp.global_flags:
        lines.append(f"全局 Flag：{', '.join(sp.global_flags)}")
    if sp.player_skill_keys:
        lines.append("【玩家技能（proposed_checks 中的 skill_key 必须来自此列表）】")
        for pid, skill_keys in sp.player_skill_keys.items():
            lines.append(f"  {pid}: {', '.join(skill_keys)}")
    if sp.clock_values:
        clocks = "、".join(f"{k}={v}" for k, v in sp.clock_values.items())
        lines.append(f"时钟：{clocks}")

    narrative = getattr(prompt, "narrative", NarrativeContextLayer())
    if narrative.selected_lorebook_entries:
        lines.append("【本轮触发的世界书条目】")
        for entry in narrative.selected_lorebook_entries:
            lines.append(
                f"  - {entry.title}（{entry.entry_id}，{entry.selection_reason}）："
                f"{entry.content}"
            )
    if narrative.selected_ids:
        lines.append("已注入叙事上下文ID：" + ", ".join(narrative.selected_ids))

    # 历史层
    hist = prompt.history
    if hist.recent_events_summary:
        lines.append("【最近事件】")
        for evt in hist.recent_events_summary[-hist.max_events :]:
            lines.append(f"  - {evt}")

    # 意图列表
    if prompt.pending_intents:
        lines.append(f"\n【第 {prompt.turn_no} 回合玩家意图】")
        for intent in prompt.pending_intents:
            if intent.intent_type == "move":
                lines.append(
                    f"  - {intent.player_id} 试图移动到 {intent.target_scene_id}"
                )
            elif intent.intent_type == "action":
                action_line = (
                    f"  - {intent.player_id} 执行动作「"
                    f"{intent.action_name or intent.action_id}」"
                )
                if intent.action_description:
                    action_line += f"：{intent.action_description}"
                lines.append(action_line)
    else:
        lines.append(f"\n【第 {prompt.turn_no} 回合：本场景无待结算意图。】")

    lines.append(
        "\n请以守密人身份，按照 JSON schema 输出本轮的结构化提议（KeeperAgentPlan）。"
        "所有字段均为提议，不代表最终效果。"
    )

    return "\n".join(lines)


# JSON schema 描述（供 LLM structured output 使用）
_KEEPER_AGENT_PLAN_SCHEMA = KeeperAgentPlan.model_json_schema()
_DEEPSEEK_PLAN_JSON_EXAMPLE = """\
请只输出一个合法的 json object，不要输出 markdown，不要输出额外解释。
example json:
{
  "intent_summary": "守密人对本批次意图的理解",
  "proposed_checks": [
    {
      "player_id": "p1",
      "action_id": "find_key",
      "skill_key": "spot_hidden",
      "proposed_difficulty": "normal",
      "rationale": "为什么建议做这次检定"
    }
  ],
  "proposed_effects": [],
  "proposed_transition": null,
  "keeper_notes": "给守密人的内部备注"
}
如果没有提议检定或提议效果，请返回空数组；如果没有剧情迁移，请返回 null。
如果有剧情迁移，`proposed_transition` 必须是 object：
{
  "transition_id": "unlock_access",
  "rationale": "为什么建议推进该剧情迁移"
}
不要把 `proposed_transition` 直接写成字符串，比如不要只写 `"unlock_access"`。
"""


def _normalize_plan_payload(data: object) -> object:
    """兼容 DeepSeek 常见的轻微 schema 偏差。"""
    if not isinstance(data, dict):
        return data

    normalized = dict(data)
    proposed_transition = normalized.get("proposed_transition")
    if isinstance(proposed_transition, str):
        transition_id = proposed_transition.strip()
        if transition_id:
            logger.info(
                "KeeperPlanAgent: 将字符串 proposed_transition=%r 归一化为对象。",
                transition_id,
            )
            normalized["proposed_transition"] = {
                "transition_id": transition_id,
                "rationale": "",
            }
        else:
            normalized["proposed_transition"] = None
    elif isinstance(proposed_transition, dict):
        if "transition_id" not in proposed_transition:
            for alias in ("id", "transition", "transitionId"):
                candidate = proposed_transition.get(alias)
                if isinstance(candidate, str) and candidate.strip():
                    logger.info(
                        "KeeperPlanAgent: 将 proposed_transition.%s=%r 归一化为 transition_id。",
                        alias,
                        candidate,
                    )
                    rewritten = dict(proposed_transition)
                    rewritten["transition_id"] = candidate.strip()
                    rewritten.setdefault("rationale", "")
                    normalized["proposed_transition"] = rewritten
                    break
    return normalized


class KeeperPlanAgent(BaseAgent[AgentPlanPrompt, KeeperAgentPlan]):
    """Plan 阶段的守密人 Agent。

    默认后端为 OpenAI Chat Completions（structured outputs）。
    若不传入 ``openai_client``，则 ``_call_llm`` 会返回空字符串，
    触发降级策略（适用于测试和离线运行）。

    Args:
        model_id: OpenAI 模型名，例如 "gpt-4o" / "gpt-4o-mini"。
        openai_client: 可选的 ``openai.AsyncOpenAI`` 客户端实例。
            若为 None，所有调用均走降级策略。
        temperature: LLM 温度参数（0~2）。

    Example::

        import openai

        agent = KeeperPlanAgent(
            model_id="gpt-4o",
            openai_client=openai.AsyncOpenAI(api_key="sk-..."),
        )
        record = await agent.call(prompt)
        plan: KeeperAgentPlan = record.output
    """

    max_retries: int = 2
    timeout_seconds: float = 45.0
    retry_delay_seconds: float = 2.0

    def __init__(
        self,
        *,
        model_id: str | None = None,
        openai_client: Any = None,  # openai.AsyncOpenAI
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        timeout_seconds: float | None = None,
        config: AgentSettings | None = None,
    ) -> None:
        settings = config or load_agent_settings()
        planner_config = settings.planner
        super().__init__(model_id=model_id or planner_config.model)
        self._client = openai_client or build_openai_client(settings.planner_provider)
        self._temperature = (
            planner_config.temperature if temperature is None else temperature
        )
        self._top_p = planner_config.top_p if top_p is None else top_p
        self._top_k = planner_config.top_k if top_k is None else top_k
        self.timeout_seconds = (
            planner_config.timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        self._provider_kind = detect_provider_kind(
            model_id=self._model_id,
            client=self._client,
        )

    # ------------------------------------------------------------------
    # BaseAgent 实现
    # ------------------------------------------------------------------

    async def _call_llm(self, prompt: AgentPlanPrompt) -> str:
        """向 OpenAI 发起 structured output 调用，返回 JSON 字符串。"""
        if self._client is None:
            logger.info(
                "KeeperPlanAgent: openai_client 未配置，跳过 LLM 调用（降级模式）。"
            )
            return ""

        system_msg = _build_system_message(prompt)
        user_msg = _build_user_message(prompt)
        response_format: dict[str, object]
        if self._provider_kind == "deepseek":
            system_msg = "\n\n".join(
                [
                    system_msg,
                    _DEEPSEEK_PLAN_JSON_EXAMPLE,
                ]
            )
            user_msg = "\n\n".join(
                [
                    user_msg,
                    "再次提醒：请返回合法的 json object，并确保字段名与 example json 保持一致。",
                ]
            )
            response_format = {"type": "json_object"}
        else:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "KeeperAgentPlan",
                    "strict": True,
                    "schema": _KEEPER_AGENT_PLAN_SCHEMA,
                },
            }

        request_kwargs: dict[str, object] = {
            "model": self._model_id,
            "temperature": self._temperature,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            "response_format": response_format,
            "presence_penalty": 1.0,  # 鼓励模型输出与上下文不同的内容
        }
        if self._top_p is not None:
            request_kwargs["top_p"] = self._top_p
        if self._top_k is not None:
            logger.debug(
                "KeeperPlanAgent 配置了 top_k=%s，但当前 OpenAI Chat Completions 调用不会使用该参数。",
                self._top_k,
            )
        if self._provider_kind == "deepseek":
            request_kwargs["max_tokens"] = 1200

        # OpenAI structured outputs（response_format）
        response = await self._client.chat.completions.create(**request_kwargs)

        raw_content: str = response.choices[0].message.content or ""

        # 记录 token 用量（留给 _on_call_end 使用；此处存入临时属性）
        usage = getattr(response, "usage", None)
        if usage is not None:
            self._last_usage = {
                "input_tokens": getattr(usage, "prompt_tokens", 0),
                "output_tokens": getattr(usage, "completion_tokens", 0),
            }

        return raw_content

    def _parse_output(self, raw: str) -> KeeperAgentPlan:
        """将 JSON 字符串解析为 KeeperAgentPlan。"""
        if not raw:
            raise AgentOutputError("LLM 返回空内容。")
        try:
            data = _normalize_plan_payload(json.loads(raw))
            return KeeperAgentPlan.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise AgentOutputError(f"KeeperAgentPlan 解析失败：{exc}") from exc

    def _fallback(self, prompt: AgentPlanPrompt) -> KeeperAgentPlan:
        """LLM 不可用时的降级策略：返回空提议，由规则引擎按默认逻辑处理。"""
        logger.info(
            "KeeperPlanAgent: 使用降级策略（空提议），session=%s turn=%d scene=%s",
            prompt.session_id,
            prompt.turn_no,
            prompt.scene_id,
        )
        return KeeperAgentPlan(
            intent_summary="[降级模式] LLM 不可用，规则引擎将按默认逻辑处理本轮意图。",
            proposed_checks=[],
            proposed_effects=[],
            proposed_transition=None,
            keeper_notes="[降级模式] 无 LLM 输出。",
        )

    def _validate_output(
        self, output: KeeperAgentPlan, prompt: AgentPlanPrompt
    ) -> None:
        """业务层校验：防止 Agent 提议越权。"""
        # 校验 1：proposed_transition 中的 transition_id 必须在允许列表内
        if output.proposed_transition is not None:
            allowed = set(prompt.module.available_transition_ids)
            if allowed and output.proposed_transition.transition_id not in allowed:
                raise AgentOutputError(
                    f"Agent 提议的 transition_id "
                    f"'{output.proposed_transition.transition_id}' "
                    f"不在当前阶段的可触发列表中：{allowed}"
                )

        # 校验 2：proposed_checks 中的 player_id 必须在在场玩家内
        present = set(prompt.spatial.present_player_ids)
        for chk in output.proposed_checks:
            if chk.player_id not in present:
                raise AgentOutputError(
                    f"Agent 提议对不在场的玩家 '{chk.player_id}' 执行检定。"
                )

        # 校验 3：proposed_checks 中的 skill_key 必须是玩家实际持有的技能
        player_skill_keys = prompt.spatial.player_skill_keys
        for chk in output.proposed_checks:
            valid_keys = player_skill_keys.get(chk.player_id)
            if valid_keys is not None and chk.skill_key not in valid_keys:
                raise AgentOutputError(
                    f"Agent 为玩家 '{chk.player_id}' 提议了不存在的技能 "
                    f"'{chk.skill_key}'，该玩家持有的技能为：{valid_keys}"
                )
