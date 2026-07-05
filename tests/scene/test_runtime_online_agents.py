from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from collections.abc import Iterable
from pathlib import Path

import pytest

from cards import build_investigator_from_mapping, load_skill_template_mapping
from scenario.runtime import SceneRuntime, TurnResolution
from scenario.runtime.engine import KeeperPlanAgent, KeeperRenderAgent

_LOG_DIR_SCENE = Path(__file__).resolve().parents[2] / "log" / "scene"
_LOG_DIR_STORY = Path(__file__).resolve().parents[2] / "log" / "story"
_TEST_LOG_PREFIX = "test_runtime_online_agents"


def _write_agent_trace_log(
    *,
    log_name: str,
    resolutions: list[TurnResolution],
) -> None:
    """将所有回合的 plan/render event_log 写入 log/scene/ 目录。"""
    _LOG_DIR_SCENE.mkdir(parents=True, exist_ok=True)
    turns = []
    for resolution in resolutions:
        turn_entry = {
            "session_id": resolution.session_id,
            "turn_no": resolution.turn_no,
            "new_stage": resolution.new_stage,
            "applied_story_transition_id": resolution.applied_story_transition_id,
            "resolved_ending": resolution.resolved_ending,
            "event_log": [e.model_dump() for e in resolution.event_log],
        }
        turns.append(turn_entry)
    (_LOG_DIR_SCENE / log_name).write_text(
        json.dumps(turns, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _write_story_log(
    *,
    log_name: str,
    resolutions: list[TurnResolution],
) -> None:
    """将所有回合的叙事文本写入 log/story/ 目录，方便人工观察。"""
    _LOG_DIR_STORY.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for resolution in resolutions:
        lines.append(f"══════════════ 第 {resolution.turn_no} 回合 ══════════════")
        for batch in resolution.scene_batches:
            lines.append(f"【场景：{batch.scene_id}】")
            if batch.narration is not None:
                public = batch.narration.public_narration.strip()
                if public:
                    lines.append(public)
                for dialogue in batch.narration.npc_dialogues:
                    lines.append(f"  [NPC {dialogue.npc_id}]: {dialogue.text}")
                for clue in batch.narration.private_clues:
                    lines.append(
                        f"  [私有线索 → {clue.player_id}]: {clue.clue_text}"
                    )
                hint = batch.narration.keeper_hint.strip()
                if hint:
                    lines.append(f"  (守密人提示: {hint})")
            else:
                lines.append("  （本批次无叙事输出）")
        if resolution.applied_story_transition_id:
            lines.append(
                f"→ 剧情迁移：{resolution.applied_story_transition_id}"
                f"，新阶段：{resolution.new_stage}"
            )
        if resolution.resolved_ending:
            lines.append(f"★ 结局达成：{resolution.resolved_ending}")
        lines.append("")
    (_LOG_DIR_STORY / log_name).write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "cards"
    / "fixtures"
    / "investigator_minimal.json"
)
_SKILL_TEMPLATES = load_skill_template_mapping()
_ONLINE_SKILL_INPUTS: list[dict[str, object]] = [
    {"template_key": "spot_hidden", "value": 90},
    {"template_key": "listen", "value": 85},
    {"template_key": "library_use", "value": 85},
    {"template_key": "psychology", "value": 80},
    {"template_key": "stealth", "value": 80},
    {"template_key": "first_aid", "value": 80},
    {
        "template_key": "art_craft",
        "branch_key": "locksmith",
        "branch_name": "锁匠",
        "value": 90,
    },
    {
        "template_key": "art_craft",
        "branch_key": "repair",
        "branch_name": "修理",
        "value": 85,
    },
    {
        "template_key": "science",
        "branch_key": "physics",
        "branch_name": "物理",
        "value": 90,
    },
    {
        "template_key": "science",
        "branch_key": "chemistry",
        "branch_name": "化学",
        "value": 85,
    },
    {
        "template_key": "science",
        "branch_key": "biology",
        "branch_name": "生物学",
        "value": 85,
    },
]


class FixedRollProvider:
    def __init__(self, rolls: Iterable[int]) -> None:
        self._rolls = iter(rolls)

    def __call__(self) -> int:
        try:
            return next(self._rolls)
        except StopIteration as exc:
            raise AssertionError("固定检定结果不足，测试用例需要补充 rolls") from exc


def _load_investigator_payload() -> dict[str, object]:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def _build_online_test_card() -> object:
    payload = _load_investigator_payload()
    payload["玩家"] = "online-smoke"
    payload["姓名"] = "联网 Smoke 调查员"
    return build_investigator_from_mapping(
        payload,
        skill_templates=_SKILL_TEMPLATES,
        skill_inputs=_ONLINE_SKILL_INPUTS,
    )


def _submit_and_resolve(
    runtime: SceneRuntime,
    *,
    session_id: str,
    intents: dict[str, dict[str, object]],
) -> TurnResolution:
    for player_id, intent in intents.items():
        runtime.submit_intent(session_id, player_id, intent)
    return asyncio.run(runtime.resolve_turn(session_id))


def _require_online_agent_prerequisites() -> tuple[KeeperPlanAgent, KeeperRenderAgent]:
    if os.environ.get("RUN_ONLINE_AGENT_TESTS") != "1":
        pytest.skip(
            "长联网 runtime smoke test 默认跳过；设置 RUN_ONLINE_AGENT_TESTS=1 后手动运行。"
        )
    if importlib.util.find_spec("openai") is None:
        pytest.skip(
            "openai SDK 未安装；请使用 `UV_CACHE_DIR=/tmp/uv-cache uv run --python .venv/bin/python "
            "pip install -r requirements.txt` 先同步项目环境。"
        )

    planner = KeeperPlanAgent(timeout_seconds=120.0)
    narrator = KeeperRenderAgent(timeout_seconds=120.0)
    planner.max_retries = 0
    narrator.max_retries = 0
    missing: list[str] = []
    if planner._client is None:
        missing.append("planner")
    if narrator._client is None:
        missing.append("narrator")
    if missing:
        pytest.skip(
            "联网 runtime smoke test 需要有效的 Agent API 配置；缺失角色: "
            + ", ".join(missing)
        )
    return planner, narrator


def _collect_events(resolutions: list[TurnResolution], event_type: str) -> list:
    return [
        event
        for resolution in resolutions
        for event in resolution.event_log
        if event.type == event_type
    ]


def test_generic_mvp_runtime_online_agents_happy_path() -> None:
    """真实联网的 runtime e2e smoke test。

    推荐执行方式：
    `RUN_ONLINE_AGENT_TESTS=1 pytest -q tests/scene/test_runtime_online_agents.py`
    """

    planner, narrator = _require_online_agent_prerequisites()

    runtime = SceneRuntime(
        roll_provider=FixedRollProvider([5] * 32),
        plan_agent=planner,
        render_agent=narrator,
    )
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards={"p1": _build_online_test_card()},
    )

    resolutions = [
        _submit_and_resolve(
            runtime,
            session_id=session.session_id,
            intents={"p1": {"type": "move", "target_scene_id": "storage"}},
        ),
        _submit_and_resolve(
            runtime,
            session_id=session.session_id,
            intents={"p1": {"type": "action", "action_id": "find_key"}},
        ),
        _submit_and_resolve(
            runtime,
            session_id=session.session_id,
            intents={"p1": {"type": "action", "action_id": "unlock_control_door"}},
        ),
        _submit_and_resolve(
            runtime,
            session_id=session.session_id,
            intents={"p1": {"type": "move", "target_scene_id": "foyer"}},
        ),
        _submit_and_resolve(
            runtime,
            session_id=session.session_id,
            intents={"p1": {"type": "move", "target_scene_id": "control"}},
        ),
        _submit_and_resolve(
            runtime,
            session_id=session.session_id,
            intents={"p1": {"type": "action", "action_id": "prime_machine"}},
        ),
        _submit_and_resolve(
            runtime,
            session_id=session.session_id,
            intents={"p1": {"type": "action", "action_id": "open_exit"}},
        ),
        _submit_and_resolve(
            runtime,
            session_id=session.session_id,
            intents={"p1": {"type": "move", "target_scene_id": "exit"}},
        ),
    ]
    final = resolutions[-1]

    _write_agent_trace_log(
        log_name=f"{_TEST_LOG_PREFIX}.happy_path.log",
        resolutions=resolutions,
    )
    _write_story_log(
        log_name=f"{_TEST_LOG_PREFIX}.happy_path.story.txt",
        resolutions=resolutions,
    )

    assert final.applied_story_transition_id == "escape_facility"
    assert final.new_stage == "escaped"
    assert final.resolved_ending == "escaped"
    assert session.story_state.current_stage_id == "escaped"
    assert session.resolved_ending == "escaped"
    assert not any(
        event.type == "action_resolved" and event.success is False
        for resolution in resolutions
        for event in resolution.event_log
    )

    plan_called = _collect_events(resolutions, "plan_agent_called")
    render_called = _collect_events(resolutions, "render_agent_called")
    assert len(plan_called) == 8
    assert len(render_called) == 8
    assert not _collect_events(resolutions, "plan_agent_skipped")
    assert not _collect_events(resolutions, "render_agent_skipped")
    assert all(event.fallback_used is False for event in plan_called)
    assert all(event.fallback_used is False for event in render_called)

    narrated_batches = [
        batch for resolution in resolutions for batch in resolution.scene_batches
    ]
    assert narrated_batches
    assert all(batch.narration is not None for batch in narrated_batches)
    assert all(batch.narration.is_fallback is False for batch in narrated_batches)
    assert all(batch.narration.public_narration.strip() for batch in narrated_batches)


# ---------------------------------------------------------------------------
# GROUP-9 · TASK-015 / TASK-016 — NPC patch + A-phase producer-gate tests
# ---------------------------------------------------------------------------


def test_npc_patches_commit_atomic() -> None:
    """TASK-015: accepted patch applies atomically to session.npc_states."""
    from scenario.npc_patches import (
        NPCStatePatchProposal,
        apply_npc_patches,
        validate_npc_patch,
    )
    from scenario.session.state import NPCSessionState, SessionMapState

    def _story_stub():
        from scenario.story.models import StoryState

        return StoryState(current_stage_id="entry")

    npc_id = "npc_alpha"
    session = SessionMapState(
        session_id="sess_atomic",
        module_id="mod_x",
        current_turn=3,
        story_state=_story_stub(),
        npc_states={
            npc_id: NPCSessionState(
                npc_id=npc_id,
                module_id="mod_x",
                current_scene_id="car_4",
            )
        },
    )

    proposal = NPCStatePatchProposal(
        npc_id=npc_id,
        path="current_scene_id",
        old_value="car_4",
        new_value="car_5",
        reason="unit-test atomic commit",
        producer="session_init",
    )

    rejection = validate_npc_patch(session, proposal)
    assert rejection is None, f"expected acceptance, got: {rejection}"

    accepted = [proposal]
    apply_npc_patches(session, accepted)
    assert session.npc_states[npc_id].current_scene_id == "car_5"


def test_reject_stale_old_value() -> None:
    """TASK-015: stale old_value must be rejected with a 'stale' reason."""
    from scenario.npc_patches import (
        NPCStatePatchProposal,
        validate_npc_patch,
    )
    from scenario.session.state import NPCSessionState, SessionMapState

    def _story_stub():
        from scenario.story.models import StoryState

        return StoryState(current_stage_id="entry")

    npc_id = "npc_beta"
    session = SessionMapState(
        session_id="sess_stale",
        module_id="mod_x",
        story_state=_story_stub(),
        npc_states={
            npc_id: NPCSessionState(
                npc_id=npc_id,
                module_id="mod_x",
                current_scene_id="car_4",
            )
        },
    )

    # Manually mutate the current scene behind the patch's back.
    session.npc_states[npc_id].current_scene_id = "car_X"

    stale_proposal = NPCStatePatchProposal(
        npc_id=npc_id,
        path="current_scene_id",
        old_value="car_4",
        new_value="car_5",
        reason="stale patch should fail",
        producer="session_init",
    )
    rejection = validate_npc_patch(session, stale_proposal)
    assert rejection is not None, "expected rejection due to stale old_value"
    assert "stale" in rejection.reason.lower()


def test_A_phase_rejects_world_tick() -> None:
    """TASK-016: producer='world_tick' must be rejected by the A-phase gate."""
    from scenario.npc_patches import (
        NPCStatePatchProposal,
        validate_npc_patch,
    )
    from scenario.session.state import NPCSessionState, SessionMapState

    def _story_stub():
        from scenario.story.models import StoryState

        return StoryState(current_stage_id="entry")

    npc_id = "npc_gamma"
    session = SessionMapState(
        session_id="sess_phaseA",
        module_id="mod_x",
        story_state=_story_stub(),
        npc_states={
            npc_id: NPCSessionState(
                npc_id=npc_id,
                module_id="mod_x",
                current_scene_id="car_1",
            )
        },
    )

    bad_proposal = NPCStatePatchProposal(
        npc_id=npc_id,
        path="current_scene_id",
        old_value="car_1",
        new_value="car_2",
        reason="world_tick should be blocked",
        producer="world_tick",
    )
    rejection = validate_npc_patch(session, bad_proposal)
    assert rejection is not None, "expected world_tick producer to be rejected"
    assert rejection.producer == "world_tick"
    # Reason should flag producer-whitelist failure (mentions 'producer').
    assert "producer" in rejection.reason.lower()


def test_full_scene_runner_smoke() -> None:
    """TASK-015 / smoke: SceneRuntime.resolve_turn must not grow npc_states."""
    from cards import build_investigator_from_mapping, load_skill_template_mapping

    from scenario.runtime import SceneRuntime

    _SKILL_TEMPLATES = load_skill_template_mapping()
    payload = _load_investigator_payload()
    payload["玩家"] = "smoke-runner"
    payload["姓名"] = "Smoke Runner"
    card = build_investigator_from_mapping(
        payload,
        skill_templates=_SKILL_TEMPLATES,
        skill_inputs=[
            {"template_key": "spot_hidden", "value": 80},
            {"template_key": "library_use", "value": 75},
        ],
    )

    runtime = SceneRuntime(roll_provider=FixedRollProvider([4] * 32))
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards={"p1": card},
    )
    npc_count_before = len(session.npc_states)

    # Submit a freeform intent in the entry scene and resolve one turn.
    runtime.submit_intent(
        session.session_id,
        "p1",
        {"type": "freeform", "text": "调查前厅"},
    )
    asyncio.run(runtime.resolve_turn(session.session_id))

    assert len(session.npc_states) == npc_count_before, (
        f"npc_states grew unexpectedly: {npc_count_before} -> {len(session.npc_states)}"
    )
