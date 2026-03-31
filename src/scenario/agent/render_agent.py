"""KeeperRenderAgent：Render 阶段的 Agent 实现。

职责：
- 接受 CommitResult（已提交的回合结果），生成 KeeperNarration（叙事文本）。
- 只读操作，不触发任何状态变更。
- LLM 不可用时降级为模板化文本，保证系统健壮性。

设计说明：
- Render 阶段在 Plan 执行、RuleEngine 检定、状态提交之后运行。
- 生成的叙事按可见范围分发（public / keeper / player:{id}）。
- 降级策略（_fallback）必须覆盖所有场景，确保玩家总能收到回馈。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from .base import AgentOutputError, BaseAgent
from .models import CommitResult, KeeperNarration

logger = logging.getLogger(__name__)

# KeeperNarration JSON schema（供 structured outputs 使用）
_KEEPER_NARRATION_SCHEMA = KeeperNarration.model_json_schema()

_SYSTEM_PROMPT = """\
你是 Call of Cthulhu 桌游的守密人，负责将本回合的裁定结果转化为沉浸式的叙事文本。

输出要求：
1. public_narration：对本场景本回合发生的事件进行生动描述，所有玩家可见，不超过 300 字。
2. npc_dialogues：如果场景中有 NPC 参与，给出其台词，按可见范围分配。
3. private_clues：如果某位玩家触发了私有线索，单独说明，仅发给该玩家。
4. keeper_hint：对守密人的内部提示，包含剧情走向建议，不对玩家展示。
5. 保持克苏鲁恐怖风格，语气压抑、充满未知感。
6. 不要破坏游戏内的第四堵墙（不提及规则数值）。
"""


def _build_render_user_message(commit: CommitResult) -> str:
    """从 CommitResult 构建 user message。"""
    lines: list[str] = [
        f"【第 {commit.turn_no} 回合 - 场景：{commit.scene_id}】",
        "",
    ]

    # 检定结果
    if commit.resolved_checks:
        lines.append("【检定结果】")
        for chk in commit.resolved_checks:
            player = chk.get("player_id", "?")
            skill = chk.get("skill_key", "?")
            success = chk.get("success", False)
            level = chk.get("success_level", "")
            roll = chk.get("roll_value", "?")
            lines.append(
                f"  - {player} 检定「{skill}」: "
                f"{'成功' if success else '失败'}"
                + (f"（{level}）" if level else "")
                + f"，掷骰值 {roll}"
            )

    # 生效效果
    if commit.applied_effects:
        lines.append("【本轮生效效果】")
        for effect in commit.applied_effects:
            lines.append(f"  - {effect}")

    # 剧情迁移
    if commit.applied_transition_id:
        lines.append(
            f"【剧情迁移】{commit.applied_transition_id}"
            + (f" → 进入阶段：{commit.new_stage_id}" if commit.new_stage_id else "")
        )

    # 结局
    if commit.resolved_ending:
        lines.append(f"【会话结局】{commit.resolved_ending}")

    # 事件摘要
    if commit.event_summary:
        lines.append("【事件摘要】")
        for evt in commit.event_summary:
            lines.append(f"  - {evt}")

    lines.append("")
    lines.append("请按 JSON schema 输出 KeeperNarration。")
    return "\n".join(lines)


class KeeperRenderAgent(BaseAgent[CommitResult, KeeperNarration]):
    """Render 阶段的守密人叙事 Agent。

    接受已提交的回合结果 CommitResult，生成 KeeperNarration。
    只读操作，不修改任何状态。

    Args:
        model_id: OpenAI 模型名，例如 "gpt-4o" / "gpt-4o-mini"。
        openai_client: 可选的 ``openai.AsyncOpenAI`` 客户端实例。
            若为 None，所有调用均走降级策略（模板化叙事）。
        temperature: LLM 温度参数（叙事场景建议 0.8~1.1）。

    Example::

        agent = KeeperRenderAgent(
            model_id="gpt-4o",
            openai_client=openai.AsyncOpenAI(api_key="sk-..."),
        )
        record = await agent.call(commit_result)
        narration: KeeperNarration = record.output
    """

    max_retries: int = 2
    timeout_seconds: float = 60.0  # 叙事生成可能更慢
    retry_delay_seconds: float = 2.0

    def __init__(
        self,
        *,
        model_id: str = "gpt-4o",
        openai_client: Any = None,  # openai.AsyncOpenAI
        temperature: float = 0.9,
    ) -> None:
        super().__init__(model_id=model_id)
        self._client = openai_client
        self._temperature = temperature

    # ------------------------------------------------------------------
    # BaseAgent 实现
    # ------------------------------------------------------------------

    async def _call_llm(self, prompt: CommitResult) -> str:
        """向 OpenAI 发起 structured output 调用，返回叙事 JSON 字符串。"""
        if self._client is None:
            logger.info(
                "KeeperRenderAgent: openai_client 未配置，跳过 LLM 调用（降级模式）。"
            )
            return ""

        user_msg = _build_render_user_message(prompt)

        response = await self._client.chat.completions.create(
            model=self._model_id,
            temperature=self._temperature,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "KeeperNarration",
                    "strict": True,
                    "schema": _KEEPER_NARRATION_SCHEMA,
                },
            },
        )

        raw_content: str = response.choices[0].message.content or ""

        # 记录 token 用量
        usage = getattr(response, "usage", None)
        if usage is not None:
            self._last_usage = {
                "input_tokens": getattr(usage, "prompt_tokens", 0),
                "output_tokens": getattr(usage, "completion_tokens", 0),
            }

        return raw_content

    def _parse_output(self, raw: str) -> KeeperNarration:
        """将 JSON 字符串解析为 KeeperNarration。"""
        if not raw:
            raise AgentOutputError("LLM 返回空内容。")
        try:
            data = json.loads(raw)
            return KeeperNarration.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise AgentOutputError(f"KeeperNarration 解析失败：{exc}") from exc

    def _fallback(self, prompt: CommitResult) -> KeeperNarration:
        """降级策略：根据 CommitResult 生成模板化叙事。"""
        logger.info(
            "KeeperRenderAgent: 使用降级策略，session=%s turn=%d scene=%s",
            prompt.session_id,
            prompt.turn_no,
            prompt.scene_id,
        )

        # 构建简单的模板叙事
        parts: list[str] = [f"第 {prompt.turn_no} 回合结算完毕。"]

        if prompt.resolved_checks:
            for chk in prompt.resolved_checks:
                player = chk.get("player_id", "?")
                skill = chk.get("skill_key", "?")
                success = chk.get("success", False)
                parts.append(f"{player} 的{skill}检定{'成功' if success else '失败'}。")

        if prompt.applied_effects:
            parts.append("场景状态已更新。")

        if prompt.applied_transition_id and prompt.new_stage_id:
            parts.append(f"剧情进入新的阶段：{prompt.new_stage_id}。")

        if prompt.resolved_ending:
            parts.append(f"故事走向了终局：{prompt.resolved_ending}。")

        return KeeperNarration(
            public_narration=" ".join(parts),
            npc_dialogues=[],
            private_clues=[],
            keeper_hint="[降级模式] 请检查 LLM 配置。",
            is_fallback=True,
        )

    def _validate_output(self, output: KeeperNarration, prompt: CommitResult) -> None:
        """校验叙事输出的基本合法性。"""
        # 叙事内容不得为空
        if not output.public_narration.strip():
            raise AgentOutputError("KeeperNarration.public_narration 不得为空。")

        # 若存在结局，叙事中必须有相关描述（宽松检查）
        if prompt.resolved_ending and not output.public_narration:
            raise AgentOutputError("会话已到达结局，但 public_narration 为空。")
