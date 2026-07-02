from __future__ import annotations

import json

from scenario.agent.models import (
    KeeperNarration,
    NPCDialogue,
    PrivateClue,
    VisibleScope,
)
from scenario.runtime import DiceRollAudit, SceneBatchResolution, TurnResolution
from scenario.runtime import SceneRuntime
from scenario.session import SessionMapState
from scenario.view import TurnViewBuilder
from tests.scene.card_fixtures import build_player_cards


def _build_resolution_with_private_material() -> tuple[SessionMapState, TurnResolution]:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["p1", "p2"],
        player_cards=build_player_cards(["p1", "p2"]),
    )
    narration = KeeperNarration(
        public_narration="公共叙事：前厅的灯闪了一下。",
        npc_dialogues=[
            NPCDialogue(
                npc_id="guide",
                npc_name="向导",
                dialogue="所有人都能听见这句话。",
                visible_scope=VisibleScope.PUBLIC,
            ),
            NPCDialogue(
                npc_id="keeper_only",
                npc_name="暗线",
                dialogue="只有守密人该看到这句。",
                visible_scope=VisibleScope.KEEPER,
            ),
        ],
        private_clues=[
            PrivateClue(player_id="p1", clue_text="p1 的私有线索"),
            PrivateClue(player_id="p2", clue_text="p2 的私有线索"),
        ],
        keeper_hint="keeper-only 下一步提示",
    )
    resolution = TurnResolution(
        session_id=session.session_id,
        turn_no=1,
        next_turn=2,
        dice_rolls=[
            DiceRollAudit(
                source="runtime_freeform_check",
                player_id="p1",
                visibility="public",
                label="spot_hidden CHECK",
                display_text="spot_hidden CHECK\n投掷骰子 d100=42",
            ),
            DiceRollAudit(
                source="status_consequence",
                player_id="p1",
                visibility="keeper",
                label="SAN CHECK",
                display_text="[暗骰] SAN CHECK\n投掷骰子 1d3=3",
            ),
        ],
        scene_batches=[
            SceneBatchResolution(
                scene_id="foyer",
                player_ids=["p1", "p2"],
                outcomes=[],
                narration=narration,
            )
        ],
    )
    return session, resolution


def test_player_turn_view_filters_private_clues_and_omits_keeper_hint() -> None:
    session, resolution = _build_resolution_with_private_material()
    view = TurnViewBuilder().build_player_turn_view(
        resolution=resolution,
        session=session,
        player_id="p1",
    )
    payload = json.dumps(view.model_dump(), ensure_ascii=False)

    assert "公共叙事" in payload
    assert "p1 的私有线索" in payload
    assert "p2 的私有线索" not in payload
    assert "keeper-only 下一步提示" not in payload
    assert "只有守密人该看到这句" not in payload
    assert "keeper_hint" not in payload
    assert "spot_hidden CHECK" in payload
    assert "SAN CHECK" not in payload


def test_keeper_turn_view_preserves_all_private_material() -> None:
    session, resolution = _build_resolution_with_private_material()
    view = TurnViewBuilder().build_keeper_turn_view(
        resolution=resolution,
        session=session,
    )
    payload = json.dumps(view.model_dump(), ensure_ascii=False)

    assert "公共叙事" in payload
    assert "p1 的私有线索" in payload
    assert "p2 的私有线索" in payload
    assert "keeper-only 下一步提示" in payload
    assert "只有守密人该看到这句" in payload
    assert "keeper_hint" in payload
    assert "spot_hidden CHECK" in payload
    assert "SAN CHECK" in payload
