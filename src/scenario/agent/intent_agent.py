"""KeeperIntentAgent：用 LLM 裁定自然语言是否属于自由行动。"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from .base import AgentOutputError, BaseAgent
from .config import (
    AgentSettings,
    build_model_client,
    detect_provider_kind,
    load_agent_settings,
    select_provider_for_model,
)
from .model_client import ModelMessage, ModelRequest
from .models import IntentAgentDecision, IntentAgentPrompt

logger = logging.getLogger(__name__)

_INTENT_DECISION_SCHEMA = IntentAgentDecision.model_json_schema()
_DEEPSEEK_INTENT_JSON_EXAMPLE = """\
请只输出一个合法的 json object，不要输出 markdown，不要输出额外解释。
example json:
{
  "intent_type": "freeform",
  "confidence": 0.88,
  "freeform_kind": "generic",
  "intended_target": "",
  "risk_hint": "可由守密人自由裁定，不等同于菜单动作。",
  "clarification_question": "",
  "candidates": [],
  "rationale": "玩家正在描述角色在场景内尝试做的事。"
}
"""

_SYSTEM_PROMPT = """\
你是 Call of Cthulhu 跑团系统的意图裁定器，只判断玩家自然语言是否应被接成自由行动。

你不会推进剧情，不会生成旁白，只输出 JSON。

裁定原则：
1. 确定性层已处理高置信菜单移动和模组动作；你主要处理灰区。
2. 只要玩家在描述角色于游戏世界中尝试做某件事，即使不是可用动作列表，也应返回 freeform。
3. 玩家试图操作、破坏、触碰、搜索、询问、试探上一轮叙事中出现的物件，也应返回 freeform。
4. 玩家试图前往未定义、当前不可达、地图外或剧本外的地点，返回 freeform，且 freeform_kind 写 off_map_move。
5. 只有在输入不是角色行动、缺少可裁定对象、明显是桌上闲聊，或含义无法落地时，才返回 clarify。
6. 不要把 freeform 改写成可用移动/动作；菜单动作由确定性层负责。
7. 如果 freeform 有风险，risk_hint 应提示 KP 可以使用暗骰、幸运、侦查、聆听、潜行、伤害、SAN 或威胁时钟等方式裁定。
"""


def _normalize_intent_decision_payload(data: object) -> object:
    if not isinstance(data, Mapping):
        return data

    normalized = dict(data)
    for key in (
        "intent_type",
        "freeform_kind",
        "intended_target",
        "risk_hint",
        "clarification_question",
        "rationale",
    ):
        if normalized.get(key) is None:
            normalized[key] = ""
    if normalized.get("candidates") is None:
        normalized["candidates"] = []
    if normalized.get("confidence") is None:
        normalized["confidence"] = 0.0
    if normalized.get("intent_type"):
        return normalized

    if "clarification_question" not in normalized and "question" in data:
        normalized["clarification_question"] = str(data.get("question") or "")

    intent_payload = data.get("intent_payload") or data.get("payload")
    payload = intent_payload if isinstance(intent_payload, Mapping) else {}
    matched = str(data.get("matched") or "")
    matched_kind = str(
        data.get("matched_kind")
        or (matched.split(":", 1)[0] if matched else "")
        or payload.get("type")
        or ""
    ).lower()
    accepted = bool(data.get("accepted", False))

    if accepted and matched_kind in {"freeform", "observe", "perception"}:
        normalized["intent_type"] = "freeform"
        if float(normalized.get("confidence") or 0.0) <= 0.0:
            normalized["confidence"] = 0.5
        normalized["freeform_kind"] = str(
            data.get("freeform_kind") or payload.get("freeform_kind") or "generic"
        )
        normalized["intended_target"] = str(
            data.get("intended_target") or payload.get("intended_target") or ""
        )
        normalized["risk_hint"] = str(
            data.get("risk_hint") or payload.get("risk_hint") or ""
        )
        return normalized

    normalized["intent_type"] = "clarify"
    return normalized


def _build_intent_user_message(prompt: IntentAgentPrompt) -> str:
    lines = [
        f"【模组】{prompt.module_title or prompt.module_id}（{prompt.module_id}）",
        f"【阶段】{prompt.current_stage_id}",
        (
            f"【当前位置】{prompt.current_scene_name or prompt.current_scene_id}"
            f"（{prompt.current_scene_id}）"
        ),
    ]
    if prompt.current_scene_description:
        lines.append(f"【当前场景描述】{prompt.current_scene_description}")
    if prompt.reachable_scenes:
        lines.append("【当前可移动场景】")
        for scene in prompt.reachable_scenes:
            lines.append(
                f"  - {scene.get('id', '')}: {scene.get('name', '')}"
                f"；{scene.get('description', '')}"
            )
    if prompt.available_actions:
        lines.append("【当前模组动作】")
        for action in prompt.available_actions:
            lines.append(
                f"  - {action.get('id', '')}: {action.get('name', '')}"
                f"；{action.get('description', '')}"
            )

    lines.extend(
        [
            "【确定性层初判】",
            f"accepted={prompt.deterministic_accepted}",
            f"matched={prompt.deterministic_matched_kind}:{prompt.deterministic_matched_id}",
            f"payload={prompt.deterministic_payload or {}}",
            f"question={prompt.deterministic_question}",
            f"candidates={prompt.deterministic_candidates}",
            "【玩家原文】",
            prompt.raw_text,
            "",
            "请判断这句话是否应该接成 freeform；如果是地图外/不可达地点探索，freeform_kind=off_map_move。",
        ]
    )
    return "\n".join(lines)


class KeeperIntentAgent(BaseAgent[IntentAgentPrompt, IntentAgentDecision]):
    """自然语言意图裁定 Agent。"""

    max_retries: int = 1
    timeout_seconds: float = 30.0
    retry_delay_seconds: float = 1.0

    def __init__(
        self,
        *,
        model_id: str | None = None,
        openai_client: Any = None,
        model_client: Any = None,
        temperature: float | None = None,
        top_p: float | None = None,
        timeout_seconds: float | None = None,
        config: AgentSettings | None = None,
    ) -> None:
        settings = config or load_agent_settings()
        planner_config = settings.planner
        super().__init__(model_id=model_id or planner_config.model)
        provider = select_provider_for_model(
            model_id=self._model_id,
            default_provider=settings.planner_provider,
            deepseek_provider=settings.deepseek_provider,
            anthropic_provider=settings.anthropic_provider,
        )
        self._model_client = model_client or build_model_client(
            provider,
            model_id=self._model_id,
            openai_client=openai_client,
        )
        self._client = getattr(self._model_client, "raw_client", self._model_client)
        self._temperature = 0.2 if temperature is None else temperature
        self._top_p = planner_config.top_p if top_p is None else top_p
        self.timeout_seconds = (
            min(planner_config.timeout_seconds, 30.0)
            if timeout_seconds is None
            else timeout_seconds
        )
        self._deepseek_thinking = settings.deepseek_thinking
        self._provider_kind = str(
            getattr(
                self._model_client,
                "provider_kind",
                detect_provider_kind(model_id=self._model_id, client=provider),
            )
        )

    async def _call_llm(self, prompt: IntentAgentPrompt) -> str:
        if self._model_client is None:
            logger.info(
                "KeeperIntentAgent: model_client 未配置，跳过 LLM 调用（降级模式）。"
            )
            return ""

        system_msg = _SYSTEM_PROMPT
        user_msg = _build_intent_user_message(prompt)
        response_format: dict[str, object]
        if self._provider_kind == "deepseek":
            system_msg = "\n\n".join([system_msg, _DEEPSEEK_INTENT_JSON_EXAMPLE])
            user_msg = "\n\n".join(
                [
                    user_msg,
                    "再次提醒：只返回合法 json object，字段名与 example json 一致。",
                ]
            )
            response_format = {"type": "json_object"}
        elif self._provider_kind == "anthropic":
            system_msg = "\n\n".join([system_msg, _DEEPSEEK_INTENT_JSON_EXAMPLE])
            user_msg = "\n\n".join(
                [
                    user_msg,
                    "再次提醒：只返回合法 json object，不要输出 markdown 或额外解释。",
                ]
            )
            response_format = {"type": "json_object"}
        elif self._provider_kind == "json_object_only":
            response_format = {"type": "json_object"}
        else:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "IntentAgentDecision",
                    "strict": True,
                    "schema": _INTENT_DECISION_SCHEMA,
                },
            }

        max_tokens: int | None = None
        extra_body: dict[str, object] | None = None
        if self._top_p is not None:
            top_p = self._top_p
        else:
            top_p = None
        if self._provider_kind == "deepseek":
            max_tokens = 700
            extra_body = {
                "thinking": {"type": self._deepseek_thinking}
            }
        elif self._provider_kind in {"json_object_only", "anthropic"}:
            max_tokens = 700

        response = await self._model_client.complete(
            ModelRequest(
                model=self._model_id,
                temperature=self._temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                messages=[
                    ModelMessage(role="system", content=system_msg),
                    ModelMessage(role="user", content=user_msg),
                ],
                response_format=response_format,
                extra_body=extra_body,
            )
        )
        self._last_usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }
        return response.text

    def _parse_output(self, raw: str) -> IntentAgentDecision:
        if not raw:
            raise AgentOutputError("LLM 返回空内容。")
        try:
            data = _normalize_intent_decision_payload(json.loads(raw))
            return IntentAgentDecision.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise AgentOutputError(f"IntentAgentDecision 解析失败：{exc}") from exc

    def _fallback(self, prompt: IntentAgentPrompt) -> IntentAgentDecision:
        return IntentAgentDecision(
            intent_type="clarify",
            confidence=0.0,
            clarification_question=(
                prompt.deterministic_question
                or "这个意图还不够明确，请换一种方式描述你的角色行动。"
            ),
            candidates=prompt.deterministic_candidates,
            rationale="[降级模式] LLM 不可用，保留确定性层澄清结果。",
        )

    def _validate_output(
        self, output: IntentAgentDecision, prompt: IntentAgentPrompt
    ) -> None:
        if output.intent_type not in {"freeform", "clarify"}:
            raise AgentOutputError(f"不支持的 intent_type: {output.intent_type}")
        if output.intent_type == "freeform" and output.confidence <= 0:
            raise AgentOutputError("freeform 判定必须给出正 confidence。")
