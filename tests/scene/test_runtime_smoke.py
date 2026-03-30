from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

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
    return runtime.resolve_turn(session_id)


def test_generic_mvp_cards_smoke_happy_path_reaches_escaped() -> None:
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
    runtime = SceneRuntime(roll_provider=FixedRollProvider([22, 28, 30, 18]))
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards={"p1": card},
    )
    assert session.player_states["p1"].investigator is not None

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
    assert session.resolved_ending == "escaped"
    assert not any(
        event.type == "action_resolved" and event.success is False
        for resolution in resolutions
        for event in resolution.event_log
    )
