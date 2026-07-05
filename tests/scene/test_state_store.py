from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scenario.agent.models import (
    KeeperNarration,
    NPCDialogue,
    PrivateClue,
    VisibleScope,
)
from scenario.runtime import (
    AgentCallAudit,
    DiceRollAudit,
    SceneBatchResolution,
    SceneRuntime,
    TurnResolution,
)
from scenario.store import JsonScenarioStateStore
from scenario.store.protocols import ScenarioStateStoreLockError
from scenario.view import TurnViewBuilder
from tests.scene.card_fixtures import build_player_cards


_LOCK_HOLDER_CODE = """
import fcntl
import pathlib
import sys
import time

path = pathlib.Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
handle = path.open("a+", encoding="utf-8")
fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
print("ready", flush=True)
time.sleep(30)
"""


class _FailSessionSaveAfterTurnStore(JsonScenarioStateStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.armed = False
        self.fail_next_session_save = False
        self.save_turn_calls = 0

    def save_turn(self, resolution: TurnResolution) -> None:
        self.save_turn_calls += 1
        super().save_turn(resolution)
        if self.armed:
            self.armed = False
            self.fail_next_session_save = True

    def save_session(self, session) -> None:
        if self.fail_next_session_save:
            self.fail_next_session_save = False
            raise RuntimeError("injected save_session failure")
        super().save_session(session)


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


def test_json_state_store_replays_orphan_turn_after_session_save_failure(
    tmp_path,
) -> None:
    store = _FailSessionSaveAfterTurnStore(tmp_path)
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
    runtime.submit_intent(
        session.session_id,
        "p1",
        {"type": "action", "action_id": "find_key"},
    )

    store.armed = True
    with pytest.raises(RuntimeError, match="injected save_session failure"):
        asyncio.run(runtime.resolve_turn(session.session_id, expected_turn=2))

    persisted_turn = store.load_turns(session.session_id)[2]
    stale_runtime = SceneRuntime(roll_provider=lambda: 99, state_store=store)
    stale_session = stale_runtime.get_session(session.session_id)

    assert persisted_turn.dice_rolls[0].roll_value == 1
    assert stale_session.current_turn == 2
    assert stale_session.pending_intents["p1"]["action_id"] == "find_key"
    assert "key_found" not in stale_session.global_flags

    replay = asyncio.run(
        stale_runtime.resolve_turn(session.session_id, expected_turn=2)
    )
    repaired = stale_runtime.get_session(session.session_id)
    reloaded = SceneRuntime(roll_provider=lambda: 99, state_store=store).get_session(
        session.session_id
    )

    assert replay.model_dump() == persisted_turn.model_dump()
    assert repaired.current_turn == 3
    assert repaired.pending_intents == {}
    assert "key_found" in repaired.global_flags
    assert "find_key" in repaired.completed_actions
    assert store.save_turn_calls == 2
    assert reloaded.current_turn == 3
    assert reloaded.pending_intents == {}


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


def test_json_state_store_quarantines_corrupted_session_file(tmp_path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    corrupt_path = sessions_dir / "broken.json"
    corrupt_path.write_text("{", encoding="utf-8")
    store = JsonScenarioStateStore(tmp_path)

    assert store.load_sessions() == {}
    assert not corrupt_path.exists()

    quarantine_files = list(
        (tmp_path / "quarantine" / "sessions").glob("*broken.json")
    )
    assert len(quarantine_files) == 1
    assert quarantine_files[0].read_text(encoding="utf-8") == "{"
    snapshot = store.health_snapshot()
    assert snapshot.healthy is False
    assert snapshot.counts["quarantined_files"] == 1
    assert "quarantined sessions file" in (snapshot.last_error or "")
    assert snapshot.operations["load_sessions"].failures == 0
    assert any(event.operation == "quarantine" for event in snapshot.recent_events)


def test_json_state_store_lists_ids_and_ignores_temp_json(tmp_path) -> None:
    store = JsonScenarioStateStore(tmp_path)
    runtime = SceneRuntime(roll_provider=lambda: 1)
    first = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    second = runtime.create_session(
        "generic_mvp",
        ["p2"],
        player_cards=build_player_cards(["p2"]),
    )
    store.save_session(second)
    store.save_session(first)
    (tmp_path / "sessions" / f"{first.session_id}.json.tmp").write_text(
        "{",
        encoding="utf-8",
    )

    assert store.list_session_ids() == sorted([first.session_id, second.session_id])
    assert sorted(store.load_sessions()) == sorted([first.session_id, second.session_id])
    assert store.health_snapshot().counts["temp_files"] == 1


def test_json_state_store_lock_conflict_has_clear_error(tmp_path) -> None:
    pytest.importorskip("fcntl")
    store = JsonScenarioStateStore(tmp_path)
    lock_path = Path(store.health_snapshot().paths["lock"])
    proc = subprocess.Popen(
        [sys.executable, "-c", _LOCK_HOLDER_CODE, str(lock_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "ready"
        runtime = SceneRuntime(roll_provider=lambda: 1)
        session = runtime.create_session(
            "generic_mvp",
            ["p1"],
            player_cards=build_player_cards(["p1"]),
        )

        with pytest.raises(ScenarioStateStoreLockError, match="lock"):
            store.save_session(session)

        snapshot = store.health_snapshot()
        assert snapshot.healthy is False
        assert snapshot.operations["save_session"].failures == 1
        assert "lock" in (snapshot.last_error or "")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def test_json_state_store_health_snapshot_reports_paths_counts_and_latency(
    tmp_path,
) -> None:
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

    snapshot = store.health_snapshot()
    assert snapshot.store_type == "json"
    assert snapshot.healthy is True
    assert snapshot.paths["root"] == str(tmp_path)
    assert snapshot.paths["sessions"] == str(tmp_path / "sessions")
    assert snapshot.paths["turns"] == str(tmp_path / "turns")
    assert snapshot.counts["sessions"] == 1
    assert snapshot.counts["turns"] == 1
    assert snapshot.last_error is None
    assert snapshot.operations["save_session"].count >= 2
    assert snapshot.operations["save_turn"].count == 1
    assert snapshot.operations["save_turn"].last_latency_ms is not None
    assert snapshot.operations["save_turn"].average_latency_ms is not None
    assert snapshot.recent_events


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
        dice_rolls=[
            DiceRollAudit(
                source="static_action_check",
                turn_no=1,
                player_id="p1",
                scene_id="foyer",
                action_id="find_key",
                skill_key="spot_hidden",
                roll_value=42,
                threshold=80,
                success=True,
            )
        ],
        agent_calls=[
            AgentCallAudit(
                stage="render",
                turn_no=1,
                scene_id="foyer",
                fallback_used=False,
                output_summary={"private_clues": 2},
            )
        ],
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
    assert loaded.dice_rolls[0].roll_value == 42
    assert loaded.agent_calls[0].output_summary == {"private_clues": 2}
    assert "公共叙事" in payload
    assert "公开台词" in payload
    assert "p1 私密" in payload
    assert "p2 私密" not in payload
    assert "守密人暗线" not in payload
    assert "下一轮暗示" not in payload
