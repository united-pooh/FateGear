"""Tests for enabling KTSL on real SceneRuntime/ScenarioService sessions."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from shutil import copytree

import pytest

from scenario.api import ScenarioService
from scenario.ktsl.models import KTSLLedger
from scenario.runtime.engine import SceneRuntime
from scenario.store.json_store import JsonScenarioStateStore
from tests.scene.card_fixtures import build_player_cards


def _stage_names(runtime: SceneRuntime) -> list[str]:
    return [type(stage).__name__ for stage in runtime._ktsl_stages]


def test_create_session_keeps_ktsl_disabled_by_default() -> None:
    runtime = SceneRuntime(roll_provider=lambda: 1)

    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )

    assert session.ktsl_ledger is None
    assert runtime._ktsl_stages == []


def test_create_session_enable_ktsl_attaches_ledger_and_default_stages() -> None:
    runtime = SceneRuntime(roll_provider=lambda: 1)

    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
        enable_ktsl=True,
    )

    assert session.ktsl_ledger is not None
    assert session.ktsl_ledger.module_id == "generic_mvp"
    assert _stage_names(runtime) == [
        "ScheduleGateStage",
        "FilterStage",
        "CouplingDriftStage",
        "AuditStage",
    ]


def test_create_session_enable_ktsl_uses_module_ktsl_spec(
    tmp_path: Path,
) -> None:
    module_root = tmp_path / "module"
    source_module_dir = (
        Path(__file__).resolve().parents[3] / "module" / "generic_mvp"
    )
    target_module_dir = module_root / "generic_mvp"
    copytree(source_module_dir, target_module_dir)
    module_path = target_module_dir / "module.yaml"
    module_path.write_text(
        module_path.read_text(encoding="utf-8")
        + """

ktsl_spec:
  scenes:
    - scene_id: foyer
      participant_character_ids: [p1]
      participant_player_ids: [p1]
      time_start_minute: 0
      time_end_minute: 5
  info_labels:
    - info_id: info_foyer_secret
      payload: 控制室钥匙曾被藏在储藏室旧工具箱里。
      sensitivity: high
      public_payload: 储藏室里有值得检查的旧工具箱。
      redaction: "[KTSL redacted: storage clue]"
      known_by_character_ids: [p1]
      authorized_character_ids: [p1]
  initial_knowledge:
    - character_id: p1
      known_info_ids: [info_foyer_secret]
      authorized_info_ids: [info_foyer_secret]
""",
        encoding="utf-8",
    )
    runtime = SceneRuntime(module_root=module_root, roll_provider=lambda: 1)

    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
        enable_ktsl=True,
    )

    assert session.ktsl_ledger is not None
    assert sorted(session.ktsl_ledger.scenes) == ["foyer"]
    assert sorted(session.ktsl_ledger.info_labels) == ["info_foyer_secret"]
    assert session.ktsl_ledger.knowledge["p1"].known_info_ids == [
        "info_foyer_secret"
    ]


def test_create_session_accepts_explicit_ktsl_ledger() -> None:
    runtime = SceneRuntime(roll_provider=lambda: 1)
    ledger = KTSLLedger.empty(module_id="generic_mvp")

    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
        ktsl_ledger=ledger,
    )

    assert session.ktsl_ledger is not None
    assert session.ktsl_ledger.module_id == "generic_mvp"
    assert session.ktsl_ledger is not ledger
    assert _stage_names(runtime) == [
        "ScheduleGateStage",
        "FilterStage",
        "CouplingDriftStage",
        "AuditStage",
    ]


def test_persisted_ktsl_session_restores_ledger_and_default_stages(
    tmp_path: Path,
) -> None:
    store = JsonScenarioStateStore(tmp_path / "state")
    runtime = SceneRuntime(roll_provider=lambda: 1, state_store=store)
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
        enable_ktsl=True,
    )

    restored_runtime = SceneRuntime(roll_provider=lambda: 1, state_store=store)
    restored = restored_runtime.get_session(session.session_id)

    assert restored.ktsl_ledger is not None
    assert restored.ktsl_ledger.module_id == "generic_mvp"
    assert _stage_names(restored_runtime) == [
        "ScheduleGateStage",
        "FilterStage",
        "CouplingDriftStage",
        "AuditStage",
    ]


def test_scenario_service_enable_ktsl_persists_summary_after_restart(
    tmp_path: Path,
) -> None:
    store = JsonScenarioStateStore(tmp_path / "state")
    service = ScenarioService(
        runtime=SceneRuntime(roll_provider=lambda: 1, state_store=store)
    )
    created = service.create_party(
        {
            "module_id": "generic_mvp",
            "creator_id": "keeper",
            "enable_ktsl": True,
        }
    )

    restored_service = ScenarioService(
        runtime=SceneRuntime(roll_provider=lambda: 1, state_store=store)
    )
    restored_party = restored_service.get_party(created.session_id)

    assert restored_party.ktsl_enabled is True
    assert restored_party.owner_id == "keeper"


def test_ktsl_enabled_resolve_writes_decision_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    runtime = SceneRuntime(roll_provider=lambda: 1)
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
        enable_ktsl=True,
    )
    runtime.submit_intent(
        session.session_id,
        "p1",
        {"type": "freeform", "text": "look around the foyer"},
    )

    resolution = asyncio.run(runtime.resolve_turn(session.session_id))
    turn_dir = tmp_path / "log" / "session" / session.session_id / "ktsl" / "1"

    assert resolution.turn_no == 1
    assert (turn_dir / "stage_trace.jsonl").is_file()
    assert (turn_dir / "interventions.jsonl").is_file()
    assert (turn_dir / "ledger_diffs.jsonl").is_file()
    assert (turn_dir / "audit_snapshot.json").is_file()
    stage_trace = [
        json.loads(line)
        for line in (turn_dir / "stage_trace.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert [entry["stage"] for entry in stage_trace] == [
        "ScheduleGateStage",
        "FilterStage",
        "CouplingDriftStage",
        "AuditStage",
    ]
    assert [entry["status"] for entry in stage_trace] == [
        "continue",
        "continue",
        "continue",
        "continue",
    ]
    assert all(entry["scene_id"] == "foyer" for entry in stage_trace)


def test_scenario_service_create_party_can_enable_ktsl() -> None:
    service = ScenarioService(runtime=SceneRuntime(roll_provider=lambda: 1))

    party = service.create_party(
        {
            "module_id": "generic_mvp",
            "creator_id": "keeper",
            "enable_ktsl": True,
        }
    )
    session = service._runtime.get_session(party.session_id)

    assert party.ktsl_enabled is True
    assert session.ktsl_ledger is not None
    assert session.ktsl_ledger.module_id == "generic_mvp"
