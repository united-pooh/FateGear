from __future__ import annotations

import asyncio
import json

import pytest

from scenario.agent.models import (
    KeeperNarration,
    NPCDialogue,
    PrivateClue,
    VisibleScope,
)
from scenario.runtime import SceneBatchResolution, SceneRuntime, TurnResolution
from scenario.store import JsonScenarioStateStore
from scenario.view import TurnViewBuilder
from tests.scene.card_fixtures import build_player_cards


def test_json_state_store_restores_session_and_turn_history(tmp_path) -> None:
    store = JsonScenarioStateStore(tmp_path)
    runtime = SceneRuntime(roll_provider=lambda: 1, state_store=store)
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    runtime.submit_intent(
        session.session_id,
        "p1",
        {"type": "move", "target_scene_id": "storage"},
    )

    resolution = asyncio.run(
        runtime.resolve_turn(session.session_id, expected_turn=1)
    )
    fresh_runtime = SceneRuntime(roll_provider=lambda: 1, state_store=store)
    restored = fresh_runtime.get_session(session.session_id)
    replay = asyncio.run(
        fresh_runtime.resolve_turn(session.session_id, expected_turn=1)
    )

    assert (tmp_path / "sessions" / f"{session.session_id}.json").is_file()
    assert (tmp_path / "turns" / session.session_id / "1.json").is_file()
    assert restored.current_turn == 2
    assert restored.pending_intents == {}
    assert restored.player_states["p1"].current_scene_id == "storage"
    assert fresh_runtime.list_session_ids() == [session.session_id]
    assert fresh_runtime.list_resolved_turns(session.session_id) == [1]
    assert (
        fresh_runtime.get_turn_resolution(session.session_id, 1).model_dump()
        == resolution.model_dump()
    )
    assert replay.model_dump() == resolution.model_dump()


def test_json_state_store_delete_session_removes_turn_records(tmp_path) -> None:
    store = JsonScenarioStateStore(tmp_path)
    runtime = SceneRuntime(roll_provider=lambda: 1, state_store=store)
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    runtime.submit_intent(
        session.session_id,
        "p1",
        {"type": "move", "target_scene_id": "storage"},
    )
    asyncio.run(runtime.resolve_turn(session.session_id, expected_turn=1))

    runtime.destroy_session(session.session_id)
    fresh_runtime = SceneRuntime(state_store=store)

    assert not (tmp_path / "sessions" / f"{session.session_id}.json").exists()
    assert not (tmp_path / "turns" / session.session_id).exists()
    assert fresh_runtime.list_session_ids() == []
    with pytest.raises(KeyError, match="未知会话"):
        fresh_runtime.get_session(session.session_id)


def test_json_state_store_narration_round_trip_keeps_player_view_filters(
    tmp_path,
) -> None:
    store = JsonScenarioStateStore(tmp_path)
    runtime = SceneRuntime(state_store=store)
    session = runtime.create_session(
        "generic_mvp",
        ["p1", "p2"],
        player_cards=build_player_cards(["p1", "p2"]),
    )
    resolution = TurnResolution(
        session_id=session.session_id,
        turn_no=1,
        next_turn=2,
        scene_batches=[
            SceneBatchResolution(
                scene_id="foyer",
                player_ids=["p1", "p2"],
                narration=KeeperNarration(
                    public_narration="公共叙事",
                    npc_dialogues=[
                        NPCDialogue(
                            npc_id="guide",
                            npc_name="向导",
                            dialogue="公开台词",
                            visible_scope=VisibleScope.PUBLIC,
                        ),
                        NPCDialogue(
                            npc_id="secret",
                            npc_name="暗线",
                            dialogue="守密人暗线",
                            visible_scope=VisibleScope.KEEPER,
                        ),
                    ],
                    private_clues=[
                        PrivateClue(player_id="p1", clue_text="p1 私密"),
                        PrivateClue(player_id="p2", clue_text="p2 私密"),
                    ],
                    keeper_hint="下一轮暗示",
                ),
            )
        ],
    )

    store.save_turn(resolution)
    loaded = store.load_turns(session.session_id)[1]
    view = TurnViewBuilder().build_player_turn_view(
        resolution=loaded,
        session=session,
        player_id="p1",
    )
    payload = json.dumps(view.model_dump(), ensure_ascii=False)

    assert isinstance(loaded.scene_batches[0].narration, dict)
    assert "公共叙事" in payload
    assert "公开台词" in payload
    assert "p1 私密" in payload
    assert "p2 私密" not in payload
    assert "守密人暗线" not in payload
    assert "下一轮暗示" not in payload
