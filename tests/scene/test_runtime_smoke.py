from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from cards import build_investigator_from_mapping, load_skill_template_mapping
from scenario.runtime import SceneRuntime, TurnResolution


class FixedRollProvider:
    def __init__(self, rolls: Iterable[int]) -> None:
        self._rolls = iter(rolls)

    def __call__(self) -> int:
        try:
            return next(self._rolls)
        except StopIteration as exc:
            raise AssertionError("固定检定结果不足，测试用例需要补充 rolls") from exc


@dataclass
class _Meta:
    fallback_used: bool = False


@dataclass
class _Record:
    prompt: Any
    output: Any
    meta: _Meta = field(default_factory=_Meta)


@dataclass
class _ProposedCheck:
    player_id: str
    action_id: str
    skill_key: str
    proposed_difficulty: str = "regular"
    rationale: str = ""


@dataclass
class _Plan:
    intent_summary: str
    proposed_checks: list[_ProposedCheck]
    proposed_effects: list[Any] = field(default_factory=list)
    proposed_transition: Any = None
    keeper_notes: str = ""


@dataclass
class _Narration:
    public_narration: str
    npc_dialogues: list[Any] = field(default_factory=list)
    private_clues: list[Any] = field(default_factory=list)
    keeper_hint: str = ""
    is_fallback: bool = False


class FakePlannerAgent:
    """异步 Planner 测试替身。

    记录收到的 prompt，并为关键动作回合返回稳定的动态检定提议。
    """

    def __init__(self) -> None:
        self.records: list[_Record] = []

    async def call(self, prompt: Any) -> _Record:
        checks: list[_ProposedCheck] = []
        for intent in prompt.pending_intents:
            if intent.intent_type != "action":
                continue
            skill_key = {
                "find_key": "spot_hidden",
                "unlock_control_door": "art_craft:locksmith",
                "prime_machine": "science:physics",
                "open_exit": "science:physics",
            }.get(intent.action_id)
            if skill_key is None:
                continue
            checks.append(
                _ProposedCheck(
                    player_id=intent.player_id,
                    action_id=intent.action_id,
                    skill_key=skill_key,
                    proposed_difficulty="regular",
                    rationale=f"测试 Planner 为 {intent.action_id} 提议动态检定。",
                )
            )

        record = _Record(
            prompt=prompt,
            output=_Plan(
                intent_summary=(
                    f"测试 Planner 已处理 scene={prompt.scene_id} turn={prompt.turn_no}"
                ),
                proposed_checks=checks,
                keeper_notes="smoke-test planner",
            ),
        )
        self.records.append(record)
        return record


class FakeNarratorAgent:
    """异步 Narrator 测试替身。

    记录收到的 commit，并为每个批次生成稳定 narration。
    """

    def __init__(self) -> None:
        self.records: list[_Record] = []

    async def call(self, prompt: Any) -> _Record:
        record = _Record(
            prompt=prompt,
            output=_Narration(
                public_narration=(
                    f"[scene={prompt.scene_id} turn={prompt.turn_no}] "
                    f"effects={len(prompt.applied_effects)} checks={len(prompt.resolved_checks)}"
                ),
                keeper_hint=f"narrated:{prompt.scene_id}:{prompt.turn_no}",
                is_fallback=False,
            ),
        )
        self.records.append(record)
        return record


def _load_investigator_payload() -> dict[str, object]:
    fixture = (
        Path(__file__).resolve().parents[1]
        / "cards"
        / "fixtures"
        / "investigator_minimal.json"
    )
    return json.loads(fixture.read_text(encoding="utf-8"))


def _submit_and_resolve(
    runtime: SceneRuntime,
    *,
    session_id: str,
    intents: dict[str, dict[str, object]],
) -> TurnResolution:
    for player_id, intent in intents.items():
        runtime.submit_intent(session_id, player_id, intent)
    return asyncio.run(runtime.resolve_turn(session_id))


def test_generic_mvp_cards_smoke_happy_path_reaches_escaped() -> None:
    card = build_investigator_from_mapping(
        _load_investigator_payload(),
        skill_templates=load_skill_template_mapping(),
        skill_inputs=[
            # 用于通过在 storage 搜索钥匙的侦查检定。
            {"template_key": "spot_hidden", "value": 80},
            # 用于通过开启 control 大门时需要的锁匠检定。
            {
                "template_key": "art_craft",
                "branch_key": "locksmith",
                "branch_name": "锁匠",
                "value": 70,
            },
            # 用于通过启动机器时需要的物理学检定。
            {
                "template_key": "science",
                "branch_key": "physics",
                "value": 75,
            },
        ],
    )
    # 固定四次检定结果，覆盖搜索钥匙、开锁、启动机器与开启出口。
    runtime = SceneRuntime(roll_provider=FixedRollProvider([22, 28, 30, 18]))
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards={"p1": card},
    )
    assert session.player_states["p1"].investigator is not None

    resolutions = [
        # 第 1 回合：验证初始场景可以移动到 storage。
        _submit_and_resolve(
            runtime,
            session_id=session.session_id,
            intents={"p1": {"type": "move", "target_scene_id": "storage"}},
        ),
        # 第 2 回合：验证在 storage 成功搜索到钥匙并推进关键 flag。
        _submit_and_resolve(
            runtime,
            session_id=session.session_id,
            intents={"p1": {"type": "action", "action_id": "find_key"}},
        ),
        # 第 3 回合：验证拿到钥匙后可以解锁 control 的通路。
        _submit_and_resolve(
            runtime,
            session_id=session.session_id,
            intents={"p1": {"type": "action", "action_id": "unlock_control_door"}},
        ),
        # 第 4 回合：验证解锁后可以先返回 foyer。
        _submit_and_resolve(
            runtime,
            session_id=session.session_id,
            intents={"p1": {"type": "move", "target_scene_id": "foyer"}},
        ),
        # 第 5 回合：验证从 foyer 成功进入 control。
        _submit_and_resolve(
            runtime,
            session_id=session.session_id,
            intents={"p1": {"type": "move", "target_scene_id": "control"}},
        ),
        # 第 6 回合：验证在 control 成功启动机器，满足最终逃脱前置条件。
        _submit_and_resolve(
            runtime,
            session_id=session.session_id,
            intents={"p1": {"type": "action", "action_id": "prime_machine"}},
        ),
        # 第 7 回合：验证机器启动后可以打开出口。
        _submit_and_resolve(
            runtime,
            session_id=session.session_id,
            intents={"p1": {"type": "action", "action_id": "open_exit"}},
        ),
        # 第 8 回合：验证进入 exit 后触发 happy path 的逃脱结局。
        _submit_and_resolve(
            runtime,
            session_id=session.session_id,
            intents={"p1": {"type": "move", "target_scene_id": "exit"}},
        ),
    ]
    final = resolutions[-1]

    # 结局断言：剧情迁移和会话终态都应落在 escaped。
    assert final.applied_story_transition_id == "escape_facility"
    assert final.new_stage == "escaped"
    assert final.resolved_ending == "escaped"
    assert session.story_state.current_stage_id == "escaped"
    assert session.resolved_ending == "escaped"
    # 过程断言：整条 happy path 不应出现任何动作失败事件。
    assert not any(
        event.type == "action_resolved" and event.success is False
        for resolution in resolutions
        for event in resolution.event_log
    )


def test_generic_mvp_harness_smoke_runs_planner_and_narrator_agents() -> None:
    card = build_investigator_from_mapping(
        _load_investigator_payload(),
        skill_templates=load_skill_template_mapping(),
        skill_inputs=[
            {"template_key": "spot_hidden", "value": 80},
            {
                "template_key": "art_craft",
                "branch_key": "locksmith",
                "branch_name": "锁匠",
                "value": 70,
            },
            {
                "template_key": "science",
                "branch_key": "physics",
                "value": 75,
            },
        ],
    )
    planner = FakePlannerAgent()
    narrator = FakeNarratorAgent()
    runtime = SceneRuntime(
        roll_provider=FixedRollProvider([22, 28, 30, 18]),
        plan_agent=planner,
        render_agent=narrator,
    )
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards={"p1": card},
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

    assert final.applied_story_transition_id == "escape_facility"
    assert final.new_stage == "escaped"
    assert final.resolved_ending == "escaped"
    assert session.story_state.current_stage_id == "escaped"

    assert len(planner.records) == 8
    assert len(narrator.records) == 8
    assert planner.records[0].prompt.scene_id == "foyer"
    assert planner.records[0].prompt.pending_intents[0].intent_type == "move"

    action_prompts = [
        record.prompt
        for record in planner.records
        if record.prompt.pending_intents
        and record.prompt.pending_intents[0].intent_type == "action"
    ]
    assert [prompt.pending_intents[0].action_id for prompt in action_prompts] == [
        "find_key",
        "unlock_control_door",
        "prime_machine",
        "open_exit",
    ]

    planner_check_pairs = [
        (check.player_id, check.action_id, check.skill_key)
        for record in planner.records
        for check in record.output.proposed_checks
    ]
    assert planner_check_pairs == [
        ("p1", "find_key", "spot_hidden"),
        ("p1", "unlock_control_door", "art_craft:locksmith"),
        ("p1", "prime_machine", "science:physics"),
        ("p1", "open_exit", "science:physics"),
    ]

    narrated_batches = [
        batch for resolution in resolutions for batch in resolution.scene_batches
    ]
    assert narrated_batches
    assert all(batch.narration is not None for batch in narrated_batches)
    assert all(batch.narration.is_fallback is False for batch in narrated_batches)
    assert all(batch.narration.public_narration for batch in narrated_batches)

    dynamic_check_turns = [
        record.prompt.turn_no
        for record in narrator.records
        if record.prompt.resolved_checks
    ]
    assert dynamic_check_turns == [2, 3, 6, 7]
    dice_rolls = [roll for resolution in resolutions for roll in resolution.dice_rolls]
    assert [
        (roll.turn_no, roll.source, roll.action_id, roll.skill_key, roll.roll_value)
        for roll in dice_rolls
    ] == [
        (2, "dynamic_agent_check", "find_key", "spot_hidden", 22),
        (3, "dynamic_agent_check", "unlock_control_door", "art_craft:locksmith", 28),
        (6, "dynamic_agent_check", "prime_machine", "science:physics", 30),
        (7, "dynamic_agent_check", "open_exit", "science:physics", 18),
    ]
    final_render_prompt = narrator.records[-1].prompt
    assert final_render_prompt.applied_transition_id == "escape_facility"
    assert final_render_prompt.new_stage_id == "escaped"
    assert final_render_prompt.resolved_ending == "escaped"

    assert all(
        any(event.type == "plan_agent_called" for event in resolution.event_log)
        for resolution in resolutions
    )
    assert all(
        any(event.type == "render_agent_called" for event in resolution.event_log)
        for resolution in resolutions
    )
    assert all(
        [call.stage for call in resolution.agent_calls] == ["plan", "render"]
        for resolution in resolutions
    )
    assert all(
        call.fallback_used is False
        for resolution in resolutions
        for call in resolution.agent_calls
    )
    assert resolutions[1].agent_calls[0].output_summary == {
        "proposed_checks": 1,
        "proposed_effects": 0,
        "has_transition": False,
    }
    assert resolutions[1].agent_calls[1].output_summary == {
        "npc_dialogues": 0,
        "private_clues": 0,
        "is_fallback": False,
    }


def test_runtime_passes_narrative_context_to_planner_and_narrator() -> None:
    planner = FakePlannerAgent()
    narrator = FakeNarratorAgent()
    runtime = SceneRuntime(plan_agent=planner, render_agent=narrator)
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards={"p1": build_investigator_from_mapping(
            _load_investigator_payload(),
            skill_templates=load_skill_template_mapping(),
            skill_inputs=[{"template_key": "spot_hidden", "value": 80}],
        )},
    )

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "inspect_note"}},
    )

    assert resolution.scene_batches[0].narration is not None
    assert planner.records[0].prompt.narrative.selected_ids == [
        "lore:note_warning",
        "safety:body_horror_limit",
    ]
    assert narrator.records[0].prompt.narrative.selected_ids == [
        "lore:note_warning",
        "safety:body_horror_limit",
    ]
    assert session.story_state.current_stage_id == "informed"
