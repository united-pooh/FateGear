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

from ..context import NarrativeContextLayer
from .base import AgentCallRecord, AgentOutputError, BaseAgent
from .config import (
    AgentSettings,
    build_openai_client,
    detect_provider_kind,
    load_agent_settings,
)
from .models import CommitResult, KeeperNarration, PrivateClue

logger = logging.getLogger(__name__)

# KeeperNarration JSON schema（供 structured outputs 使用）
_KEEPER_NARRATION_SCHEMA = KeeperNarration.model_json_schema()
_DEEPSEEK_NARRATION_JSON_EXAMPLE = """\
请只输出一个合法的 json object，不要输出 markdown，不要输出额外解释。
example json:
{
  "public_narration": "面向所有玩家的公共叙事文本",
  "npc_dialogues": [],
  "private_clues": [],
  "keeper_hint": "给守密人的内部提示",
  "is_fallback": false
}
如果没有 NPC 台词或私有线索，请返回空数组。
"""

_SYSTEM_PROMPT = """\
你是 Call of Cthulhu 桌游的守密人，负责将本回合的裁定结果转化为沉浸式的叙事文本。

输出要求：
1. public_narration：对本场景本回合发生的事件进行生动描述，所有玩家可见，不超过 300 字。
2. npc_dialogues：如果场景中有 NPC 参与，给出其台词，按可见范围分配。
3. private_clues：如果某位玩家触发了私有线索，单独说明，仅发给该玩家。
4. keeper_hint：对守密人的内部提示，包含剧情走向建议，不对玩家展示。
5. 保持克苏鲁恐怖风格，语气压抑、充满未知感。
6. 不要破坏游戏内的第四堵墙（不提及规则数值）。
7. 不得编造钥匙、密码、出口、真相、NPC动机等关键事实；这些内容必须来自本轮授权线索、已提交状态或明确事件。
8. private_clues 只能使用【本轮授权私有线索】中的内容；没有授权线索时必须返回空数组。
"""


def _normalize_narration_payload(data: object) -> object:
    """兼容 DeepSeek 常见的叙事字段别名。"""
    if not isinstance(data, dict):
        return data

    normalized = dict(data)
    dialogues = normalized.get("npc_dialogues")
    if isinstance(dialogues, list):
        rewritten_dialogues: list[object] = []
        for dialogue in dialogues:
            if not isinstance(dialogue, dict):
                continue
            rewritten = dict(dialogue)
            if "npc_id" not in rewritten:
                for alias in (
                    "npc",
                    "npcId",
                    "character_id",
                    "character",
                    "npc_name",
                ):
                    candidate = rewritten.get(alias)
                    if isinstance(candidate, str) and candidate.strip():
                        rewritten["npc_id"] = candidate.strip()
                        break
            if "dialogue" not in rewritten:
                for alias in ("text", "line", "content"):
                    candidate = rewritten.get(alias)
                    if isinstance(candidate, str):
                        rewritten["dialogue"] = candidate
                        break
            if "visible_scope" not in rewritten:
                candidate = rewritten.get("visible_to") or rewritten.get("audience")
                if isinstance(candidate, str) and candidate.strip():
                    scope = candidate.strip().lower()
                    if scope in {"all", "public", "players"}:
                        rewritten["visible_scope"] = "public"
                    elif scope in {"gm", "keeper"}:
                        rewritten["visible_scope"] = "keeper"
                    else:
                        rewritten["visible_scope"] = scope
            if "npc_id" not in rewritten or "dialogue" not in rewritten:
                logger.info(
                    "KeeperRenderAgent: 丢弃缺少 npc_id/dialogue 的 npc_dialogue=%r。",
                    dialogue,
                )
                continue
            rewritten_dialogues.append(rewritten)
        normalized["npc_dialogues"] = rewritten_dialogues

    private_clues = normalized.get("private_clues")
    if isinstance(private_clues, list):
        rewritten_clues: list[object] = []
        for clue in private_clues:
            if not isinstance(clue, dict):
                continue
            rewritten = dict(clue)
            if "player_id" not in rewritten:
                for alias in ("player", "target", "target_player", "recipient", "to"):
                    candidate = rewritten.get(alias)
                    if isinstance(candidate, str) and candidate.strip():
                        rewritten["player_id"] = candidate.strip()
                        break
            if "clue_text" not in rewritten:
                for alias in ("text", "clue", "content"):
                    candidate = rewritten.get(alias)
                    if isinstance(candidate, str):
                        rewritten["clue_text"] = candidate
                        break
            if "player_id" not in rewritten or "clue_text" not in rewritten:
                logger.info(
                    "KeeperRenderAgent: 丢弃缺少 player_id/clue_text 的 private_clue=%r。",
                    clue,
                )
                continue
            rewritten_clues.append(rewritten)
        normalized["private_clues"] = rewritten_clues

    if "keeper_hint" not in normalized:
        for alias in ("keeper_notes", "keeper_note", "gm_hint"):
            candidate = normalized.get(alias)
            if isinstance(candidate, str):
                normalized["keeper_hint"] = candidate
                break
    return normalized


def _build_render_system_prompt(commit: CommitResult) -> str:
    """构建包含只读叙事上下文的 Render system prompt。"""
    lines = [_SYSTEM_PROMPT]
    narrative = getattr(commit, "narrative", NarrativeContextLayer())
    if not narrative.has_content():
        return "\n".join(lines)

    lines.append("【只读叙事上下文：只能影响表达，不得改写本回合裁定】")
    if narrative.worldview_brief:
        lines.append(f"世界观：{narrative.worldview_brief}")
    if narrative.atmosphere.tone:
        lines.append(f"氛围基调：{narrative.atmosphere.tone}")
    if narrative.atmosphere.sensory_palette:
        lines.append("感官词库：" + "、".join(narrative.atmosphere.sensory_palette))
    if narrative.atmosphere.pacing_hint:
        lines.append(f"节奏提示：{narrative.atmosphere.pacing_hint}")
    if narrative.atmosphere.forbidden_reveals:
        lines.append(
            "禁止提前揭示：" + "；".join(narrative.atmosphere.forbidden_reveals)
        )
    prose = narrative.prose_controls
    lines.append(
        "叙事写法："
        f"语言={prose.language}；人称={prose.narrative_person}；"
        f"时态={prose.tense}；段落上限={prose.paragraph_limit}；"
        f"恐怖强度={prose.horror_intensity}；骰点呈现={prose.dice_visibility}；"
        f"线索公平={prose.clue_fairness}"
    )
    if prose.avoid_fourth_wall:
        lines.append("不要破坏第四堵墙，不要提及 prompt、JSON schema 或系统实现。")
    if prose.style_rules:
        lines.append("文风规则：" + "；".join(prose.style_rules))
    if narrative.selected_safety_boundaries:
        lines.append("【安全边界】")
        for boundary in narrative.selected_safety_boundaries:
            lines.append(f"- {boundary.severity}:{boundary.note}")
    if narrative.selected_npcs:
        lines.append("【可公开使用的 NPC 口吻】")
        for npc in narrative.selected_npcs:
            parts = [
                f"{npc.name}({npc.npc_id})",
                npc.role,
                npc.public_description,
                f"口吻：{npc.speaking_style}" if npc.speaking_style else "",
                (
                    f"知识边界：{npc.knowledge_boundary}"
                    if npc.knowledge_boundary
                    else ""
                ),
            ]
            lines.append("；".join(part for part in parts if part))
    return "\n".join(lines)


def _value(source: object, name: str, default: object = "") -> object:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _list_value(source: object, name: str) -> list[object]:
    value = _value(source, name, [])
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _canonical_private_clues(prompt: CommitResult) -> list[PrivateClue]:
    """把本轮授权线索转成最终允许输出的私有线索。"""
    clues: list[PrivateClue] = []
    for clue in _list_value(prompt, "authorized_private_clues"):
        clues.append(
            PrivateClue(
                player_id=str(_value(clue, "player_id", "")),
                clue_text=str(_value(clue, "clue_text", "")),
                related_action_id=str(_value(clue, "related_action_id", "")),
            )
        )
    return clues


def _contains_unauthorized_key_fact(text: str, prompt: CommitResult) -> bool:
    """粗粒度拦截无来源的关键事实，避免叙事模型补造答案。"""
    if not text:
        return False
    authorized_clues = _list_value(prompt, "authorized_private_clues")
    allowed_text = "\n".join(
        [
            str(_value(prompt, "scene_description", "")),
            "\n".join(str(item) for item in _list_value(prompt, "event_summary")),
            "\n".join(str(item) for item in _list_value(prompt, "applied_effects")),
            "\n".join(
                str(_value(clue, "clue_text", "")) for clue in authorized_clues
            ),
        ]
    )
    critical_terms = ("钥匙", "密码", "出口", "真相", "凶手", "动机")
    return any(term in text and term not in allowed_text for term in critical_terms)


def _safe_public_narration(prompt: CommitResult) -> str:
    """当模型输出越界关键事实时，退回到权威裁定摘要。"""
    scene_id = str(_value(prompt, "scene_id", ""))
    scene_label = str(_value(prompt, "scene_name", "") or scene_id)
    parts = [f"{scene_label}里的状况仍以你能直接感知到的事物为准。"]
    scene_description = str(_value(prompt, "scene_description", ""))
    if scene_description:
        parts.append(scene_description)
    for outcome in _list_value(prompt, "outcomes"):
        intent_type = str(_value(outcome, "intent_type", ""))
        if intent_type == "observe":
            text = str(_value(outcome, "observation_text", "") or "观察环境")
            parts.append(f"你选择先确认环境：{text}。没有新的完整线索被自动揭示。")
        elif intent_type == "action" and _value(outcome, "success", False):
            action_id = str(_value(outcome, "action_id", ""))
            parts.append(f"动作 {action_id} 已完成；可见结果以本轮授权线索为准。")
    return " ".join(part for part in parts if part)


def _apply_narration_guard(
    output: KeeperNarration,
    prompt: CommitResult,
) -> KeeperNarration:
    """最终输出守门：私有线索按授权列表覆盖，关键事实不得凭空生成。"""
    guarded = output.model_copy(deep=True)
    canonical_clues = _canonical_private_clues(prompt)
    guarded.private_clues = canonical_clues

    if _contains_unauthorized_key_fact(guarded.public_narration, prompt):
        guarded.public_narration = _safe_public_narration(prompt)
    if _contains_unauthorized_key_fact(guarded.keeper_hint, prompt):
        guarded.keeper_hint = (
            "本轮没有授权新的关键事实；请只依据模块、已提交状态和授权线索继续裁定。"
        )
    authorized_private_clues = _list_value(prompt, "authorized_private_clues")
    if not authorized_private_clues and output.private_clues:
        guarded.keeper_hint = (
            "本轮未触发新的私有线索；已丢弃未授权 private_clues，避免提前泄露或补造关键事实。"
        )
    elif authorized_private_clues:
        guarded.keeper_hint = (
            "本轮 private_clues 已按授权线索覆盖；不要添加未声明的钥匙、密码、出口或谜题答案。"
        )
    return guarded


def _build_render_user_message(commit: CommitResult) -> str:
    """从 CommitResult 构建 user message。"""
    scene_id = str(_value(commit, "scene_id", ""))
    scene_name = str(_value(commit, "scene_name", "") or scene_id)
    scene_description = str(_value(commit, "scene_description", ""))
    outcomes = _list_value(commit, "outcomes")
    lines: list[str] = [
        (
            f"【第 {_value(commit, 'turn_no', '?')} 回合 - "
            f"场景：{scene_name}（{scene_id}）】"
        ),
        "",
    ]
    if scene_description:
        lines.append(f"【场景可感知描述】{scene_description}")

    if outcomes:
        lines.append("【本轮裁定结果】")
        for outcome in outcomes:
            player = _value(outcome, "player_id", "?")
            intent_type = _value(outcome, "intent_type", "?")
            success = bool(_value(outcome, "success", False))
            if intent_type == "observe":
                lines.append(
                    f"  - {player} 观察/确认环境："
                    f"{_value(outcome, 'observation_text', '')}；"
                    "不触发模组动作，不授权完整线索正文。"
                )
            elif intent_type == "action":
                lines.append(
                    f"  - {player} 执行动作 {_value(outcome, 'action_id', '')}："
                    f"{'成功' if success else '失败'}"
                )
            elif intent_type == "move":
                lines.append(
                    f"  - {player} 尝试移动到 "
                    f"{_value(outcome, 'target_scene_id', '')}："
                    f"{'成功' if success else '失败'}"
                )

    # 检定结果
    resolved_checks = _list_value(commit, "resolved_checks")
    if resolved_checks:
        lines.append("【检定结果】")
        for chk in resolved_checks:
            player = _value(chk, "player_id", "?")
            skill = _value(chk, "skill_key", "?")
            success = _value(chk, "success", False)
            level = _value(chk, "success_level", "")
            roll = _value(chk, "roll_value", "?")
            lines.append(
                f"  - {player} 检定「{skill}」: "
                f"{'成功' if success else '失败'}"
                + (f"（{level}）" if level else "")
                + f"，掷骰值 {roll}"
            )

    # 生效效果
    applied_effects = _list_value(commit, "applied_effects")
    if applied_effects:
        lines.append("【本轮生效效果】")
        for effect in applied_effects:
            lines.append(f"  - {effect}")

    # 剧情迁移
    applied_transition_id = _value(commit, "applied_transition_id", None)
    new_stage_id = _value(commit, "new_stage_id", None)
    if applied_transition_id:
        lines.append(
            f"【剧情迁移】{applied_transition_id}"
            + (f" → 进入阶段：{new_stage_id}" if new_stage_id else "")
        )

    # 结局
    resolved_ending = _value(commit, "resolved_ending", None)
    if resolved_ending:
        lines.append(f"【会话结局】{resolved_ending}")

    # 事件摘要
    event_summary = _list_value(commit, "event_summary")
    if event_summary:
        lines.append("【事件摘要】")
        for evt in event_summary:
            lines.append(f"  - {evt}")

    narrative = getattr(commit, "narrative", NarrativeContextLayer())
    if narrative.selected_lorebook_entries:
        lines.append("【可用于本轮描写的世界书条目】")
        for entry in narrative.selected_lorebook_entries:
            lines.append(
                f"  - {entry.title}（{entry.entry_id}，{entry.selection_reason}）："
                f"{entry.content}"
            )

    lines.append("【本轮授权私有线索】")
    authorized_private_clues = _list_value(commit, "authorized_private_clues")
    if authorized_private_clues:
        for clue in authorized_private_clues:
            lines.append(
                f"  - player={_value(clue, 'player_id', '')} "
                f"action={_value(clue, 'related_action_id', '')} "
                f"source={_value(clue, 'source_id', '')}: "
                f"{_value(clue, 'clue_text', '')}"
            )
    else:
        lines.append("  - 无。private_clues 必须返回 []；不要补造钥匙、密码、出口、真相或下一步答案。")

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
        model_id: str | None = None,
        openai_client: Any = None,  # openai.AsyncOpenAI
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        timeout_seconds: float | None = None,
        config: AgentSettings | None = None,
    ) -> None:
        settings = config or load_agent_settings()
        narrator_config = settings.narrator
        super().__init__(model_id=model_id or narrator_config.model)
        self._client = openai_client or build_openai_client(settings.narrator_provider)
        self._temperature = (
            narrator_config.temperature if temperature is None else temperature
        )
        self._top_p = narrator_config.top_p if top_p is None else top_p
        self._top_k = narrator_config.top_k if top_k is None else top_k
        self.timeout_seconds = (
            narrator_config.timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        self._deepseek_thinking = settings.deepseek_thinking
        self._provider_kind = detect_provider_kind(
            model_id=self._model_id,
            client=self._client,
        )

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
        system_prompt = _build_render_system_prompt(prompt)
        response_format: dict[str, object]
        if self._provider_kind == "deepseek":
            system_prompt = "\n\n".join(
                [system_prompt, _DEEPSEEK_NARRATION_JSON_EXAMPLE]
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
                    "name": "KeeperNarration",
                    "strict": True,
                    "schema": _KEEPER_NARRATION_SCHEMA,
                },
            }
        request_kwargs: dict[str, object] = {
            "model": self._model_id,
            "temperature": self._temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            "response_format": response_format,
            "presence_penalty": 1.0,  # 鼓励模型输出与上下文不同的内容
        }
        if self._top_p is not None:
            request_kwargs["top_p"] = self._top_p
        if self._top_k is not None:
            logger.debug(
                "KeeperRenderAgent 配置了 top_k=%s，但当前 OpenAI Chat Completions 调用不会使用该参数。",
                self._top_k,
            )
        if self._provider_kind == "deepseek":
            request_kwargs["max_tokens"] = 1600
            request_kwargs["extra_body"] = {
                "thinking": {"type": self._deepseek_thinking}
            }

        response = await self._client.chat.completions.create(**request_kwargs)

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
            data = _normalize_narration_payload(json.loads(raw))
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

        return _apply_narration_guard(
            KeeperNarration(
                public_narration=" ".join(parts),
                npc_dialogues=[],
                private_clues=_canonical_private_clues(prompt),
                keeper_hint="[降级模式] 请检查 LLM 配置。",
                is_fallback=True,
            ),
            prompt,
        )

    def _validate_output(self, output: KeeperNarration, prompt: CommitResult) -> None:
        """校验叙事输出的基本合法性。"""
        # 叙事内容不得为空
        if not output.public_narration.strip():
            raise AgentOutputError("KeeperNarration.public_narration 不得为空。")

        # 若存在结局，叙事中必须有相关描述（宽松检查）
        if prompt.resolved_ending and not output.public_narration:
            raise AgentOutputError("会话已到达结局，但 public_narration 为空。")

    async def _on_call_end(
        self,
        record: AgentCallRecord[CommitResult, KeeperNarration],
    ) -> None:
        """调用结束后按运行时授权线索覆盖越界叙事内容。"""
        record.output = _apply_narration_guard(record.output, record.prompt)
