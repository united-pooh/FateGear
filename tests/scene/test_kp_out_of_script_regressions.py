from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from scenario.agent.models import (
    AuthorizedPrivateClue,
    CommitResult,
    KeeperNarration,
    PrivateClue,
)
from scenario.agent.render_agent import _apply_narration_guard
from scenario.runtime import SceneRuntime
from tests.scene.card_fixtures import build_player_cards


@dataclass
class _Meta:
    fallback_used: bool = False


@dataclass
class _Record:
    prompt: Any
    output: Any
    meta: _Meta = field(default_factory=_Meta)


class _LeakyNarrator:
    def __init__(self) -> None:
        self.records: list[_Record] = []

    async def call(self, prompt: CommitResult) -> _Record:
        output = _apply_narration_guard(
            KeeperNarration(
                public_narration=(
                    "你注意到门上便签。不要回头数车厢，听见后方咀嚼声时继续向前。"
                ),
                private_clues=[
                    PrivateClue(
                        player_id="p1",
                        clue_text="钥匙在守规矩的车厢里。",
                        related_action_id="",
                    )
                ],
                keeper_hint="钥匙在守规矩的车厢里。",
            ),
            prompt,
        )
        record = _Record(prompt=prompt, output=output)
        self.records.append(record)
        return record


def _resolve(runtime: SceneRuntime, session_id: str, intent: dict[str, object]):
    runtime.submit_intent(session_id, "p1", intent)
    return asyncio.run(runtime.resolve_turn(session_id))


def test_tokoyami_freeform_observe_does_not_select_or_authorize_note_warning() -> None:
    narrator = _LeakyNarrator()
    runtime = SceneRuntime(render_agent=narrator)
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )

    resolution = _resolve(
        runtime,
        session.session_id,
        {"type": "observe", "text": "环绕四周环境"},
    )

    outcome = resolution.scene_batches[0].outcomes[0]
    assert outcome.intent_type == "freeform"
    assert outcome.freeform_text == "环绕四周环境"
    assert outcome.effects_applied == []
    prompt = narrator.records[0].prompt
    assert "lore:note_warning" not in prompt.narrative.selected_ids
    assert prompt.authorized_private_clues == []

    narration = resolution.scene_batches[0].narration
    assert narration.private_clues == []
    assert "钥匙在" not in narration.keeper_hint


def test_tokoyami_inspect_note_authorizes_only_note_warning_verbatim() -> None:
    narrator = _LeakyNarrator()
    runtime = SceneRuntime(render_agent=narrator)
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )

    resolution = _resolve(
        runtime,
        session.session_id,
        {"type": "action", "action_id": "inspect_note"},
    )

    prompt = narrator.records[0].prompt
    assert [clue.source_id for clue in prompt.authorized_private_clues] == [
        "lore:note_warning"
    ]
    assert prompt.authorized_private_clues[0].related_action_id == "inspect_note"
    assert prompt.authorized_private_clues[0].clue_text == (
        "便签的字迹像是仓促写下的求生规则：不要回头数车厢，听见后方咀嚼声时继续向前。"
    )

    narration = resolution.scene_batches[0].narration
    assert [clue.clue_text for clue in narration.private_clues] == [
        prompt.authorized_private_clues[0].clue_text
    ]
    combined = "\n".join(
        [
            narration.public_narration,
            narration.keeper_hint,
            *(clue.clue_text for clue in narration.private_clues),
        ]
    )
    assert "钥匙在" not in combined
    assert "守规矩的车厢" not in combined


def test_render_guard_canonicalizes_private_clues_and_scrubs_unbacked_key_facts() -> None:
    commit = CommitResult(
        session_id="s1",
        turn_no=1,
        scene_id="car_6",
        scene_name="6号车厢",
        scene_description="末班车的起始车厢，门上贴着便签。",
        outcomes=[
            {
                "player_id": "p1",
                "intent_type": "action",
                "success": True,
                "action_id": "inspect_note",
            }
        ],
        authorized_private_clues=[
            AuthorizedPrivateClue(
                player_id="p1",
                clue_text="便签的字迹像是仓促写下的求生规则：不要回头数车厢，听见后方咀嚼声时继续向前。",
                related_action_id="inspect_note",
                source_id="lore:note_warning",
            )
        ],
    )
    guarded = _apply_narration_guard(
        KeeperNarration(
            public_narration="钥匙藏在守规矩的车厢里。",
            private_clues=[
                PrivateClue(player_id="p1", clue_text="钥匙在守规矩的车厢里。")
            ],
            keeper_hint="密码为 1234，出口位于前方。",
        ),
        commit,
    )

    assert [clue.clue_text for clue in guarded.private_clues] == [
        commit.authorized_private_clues[0].clue_text
    ]
    combined = "\n".join([guarded.public_narration, guarded.keeper_hint])
    assert "钥匙在" not in combined
    assert "钥匙藏在" not in combined
    assert "密码是" not in combined
    assert "密码为" not in combined
    assert "出口在" not in combined
    assert "出口位于" not in combined
