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

from .base import AgentOutputError, BaseAgent
from .config import AgentSettings, build_openai_client, load_agent_settings
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
    if sp.clock_values:
        clocks = "、".join(f"{k}={v}" for k, v in sp.clock_values.items())
        lines.append(f"时钟：{clocks}")

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
                lines.append(
                    f"  - {intent.player_id} 执行动作「{intent.action_name or intent.action_id}」"
                )
    else:
        lines.append(f"\n【第 {prompt.turn_no} 回合：本场景无待结算意图。】")

    lines.append(
        "\n请以守密人身份，按照 JSON schema 输出本轮的结构化提议（KeeperAgentPlan）。"
        "所有字段均为提议，不代表最终效果。"
    )

    return "\n".join(lines)


# JSON schema 描述（供 LLM structured output 使用）
_KEEPER_AGENT_PLAN_SCHEMA = KeeperAgentPlan.model_json_schema()


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
        request_kwargs: dict[str, object] = {
            "model": self._model_id,
            "temperature": self._temperature,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "KeeperAgentPlan",
                    "strict": True,
                    "schema": _KEEPER_AGENT_PLAN_SCHEMA,
                },
            },
        }
        if self._top_p is not None:
            request_kwargs["top_p"] = self._top_p
        if self._top_k is not None:
            logger.debug(
                "KeeperPlanAgent 配置了 top_k=%s，但当前 OpenAI Chat Completions 调用不会使用该参数。",
                self._top_k,
            )

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
            data = json.loads(raw)
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
