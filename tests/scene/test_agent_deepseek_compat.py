from __future__ import annotations

import asyncio
import importlib.util
import json
from types import SimpleNamespace
from typing import Any
from pathlib import Path

import pytest

from scenario.runtime.engine import KeeperPlanAgent, KeeperRenderAgent


class _RecordingCompletions:
    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return await self._inner.create(**kwargs)


class _RecordingLiveClient:
    def __init__(self, inner: Any) -> None:
        self.base_url = str(getattr(inner, "base_url", "") or "")
        self.chat = SimpleNamespace(
            completions=_RecordingCompletions(inner.chat.completions)
        )


_LOG_DIR = Path(__file__).resolve().parents[2] / "log" / "scene"
_DEEPSEEK_COMPAT_MODEL = "deepseek-v4-flash"


def _write_trace_log(
    *,
    log_name: str,
    request_kwargs: dict[str, object],
    raw: str,
) -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        parsed: object = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"_parse_error": "response is not valid json"}

    payload = {
        "request": request_kwargs,
        "raw_response": raw,
        "parsed_response": parsed,
    }
    (_LOG_DIR / log_name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _build_live_deepseek_client(agent_factory) -> _RecordingLiveClient:
    if importlib.util.find_spec("openai") is None:
        pytest.skip(
            "openai SDK 未安装；请先用项目 .venv 安装 requirements.txt。"
        )

    bootstrap_agent = agent_factory(
        model_id=_DEEPSEEK_COMPAT_MODEL,
        timeout_seconds=20.0,
    )
    if bootstrap_agent._client is None:
        pytest.skip(
            "未检测到可用的 DeepSeek Agent 配置；请检查 .env 中的 AGENT_API_KEY / AGENT_BASE_URL。"
        )
    return _RecordingLiveClient(bootstrap_agent._client)


def _build_plan_prompt() -> SimpleNamespace:
    return SimpleNamespace(
        session_id="s1",
        turn_no=2,
        scene_id="storage",
        system=SimpleNamespace(
            keeper_role_hint="你是守密人。",
            rule_summary="规则摘要。",
        ),
        module=SimpleNamespace(
            worldview_brief="",
            current_stage_id="setup",
            current_stage_description="当前阶段描述。",
            available_transition_ids=[],
        ),
        keeper_private=SimpleNamespace(
            hidden_notes="除非存在充分证据，否则 proposed_transition 必须为 null。",
            npc_hidden_states={},
        ),
        spatial=SimpleNamespace(
            scene_name="储藏室",
            scene_id="storage",
            scene_description="这里堆满箱子。",
            present_player_ids=["p1"],
            available_action_ids=[],
            global_flags=[],
            clock_values={},
            player_skill_keys={},
        ),
        history=SimpleNamespace(
            recent_events_summary=["玩家进入储藏室。"],
            max_events=10,
        ),
        pending_intents=[],
    )


def _build_commit_result() -> SimpleNamespace:
    return SimpleNamespace(
        session_id="s1",
        turn_no=2,
        scene_id="storage",
        resolved_checks=[],
        applied_effects=["设置标记:key_found"],
        applied_transition_id=None,
        new_stage_id=None,
        resolved_ending=None,
        event_summary=["玩家搜索了储藏室，并发现一把生锈的钥匙。"],
    )


def test_plan_agent_uses_json_object_for_deepseek() -> None:
    client = _build_live_deepseek_client(KeeperPlanAgent)
    agent = KeeperPlanAgent(
        openai_client=client,
        model_id=_DEEPSEEK_COMPAT_MODEL,
        timeout_seconds=20.0,
    )
    agent.max_retries = 0

    raw = asyncio.run(agent._call_llm(_build_plan_prompt()))

    assert raw
    call = client.chat.completions.calls[0]
    _write_trace_log(
        log_name="test_agent_deepseek_compat.plan.log",
        request_kwargs=call,
        raw=raw,
    )
    payload = json.loads(raw)
    assert isinstance(payload, dict)
    assert call["response_format"] == {"type": "json_object"}
    assert call["max_tokens"] == 1200
    assert "json object" in call["messages"][0]["content"].lower()
    assert "example json" in call["messages"][0]["content"].lower()
    assert "json object" in call["messages"][1]["content"].lower()


def test_render_agent_uses_json_object_for_deepseek() -> None:
    client = _build_live_deepseek_client(KeeperRenderAgent)
    agent = KeeperRenderAgent(
        openai_client=client,
        model_id=_DEEPSEEK_COMPAT_MODEL,
        timeout_seconds=20.0,
    )
    agent.max_retries = 0

    raw = asyncio.run(agent._call_llm(_build_commit_result()))

    assert raw
    call = client.chat.completions.calls[0]
    _write_trace_log(
        log_name="test_agent_deepseek_compat.render.log",
        request_kwargs=call,
        raw=raw,
    )
    payload = json.loads(raw)
    assert isinstance(payload, dict)
    assert payload.get("public_narration")
    assert call["response_format"] == {"type": "json_object"}
    assert call["max_tokens"] == 1600
    assert "json object" in call["messages"][0]["content"].lower()
    assert "example json" in call["messages"][0]["content"].lower()
    assert "json object" in call["messages"][1]["content"].lower()
