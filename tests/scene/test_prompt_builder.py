from __future__ import annotations

from scenario.agent import PromptBuilder
from scenario.io import load_module_by_id
from scenario.runtime import SceneRuntime
from tests.scene.card_fixtures import build_player_cards


def test_prompt_builder_prefers_explicit_pending_intent_snapshot() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    module = load_module_by_id("generic_mvp")
    builder = PromptBuilder()

    prompt = builder.build(
        session=session,
        module=module,
        scene_id="foyer",
        pending_intents={"p1": {"type": "move", "target_scene_id": "storage"}},
    )

    assert len(prompt.pending_intents) == 1
    assert prompt.pending_intents[0].player_id == "p1"
    assert prompt.pending_intents[0].target_scene_id == "storage"
