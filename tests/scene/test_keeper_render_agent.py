from __future__ import annotations

from scenario.narration import (
    CallableKeeperRenderAgent,
    KeeperNarrationDraft,
    NarrationPromptBuilder,
    StaticKeeperRenderAgent,
    build_narration_input_packet,
)
from scenario.runtime import RuntimeEvent, TurnResolution
from scenario.runtime.engine import SceneRuntime

from tests.scene.card_fixtures import build_player_cards


def _prompt_and_packet():
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    resolution = TurnResolution(
        session_id=session.session_id,
        turn_no=1,
        next_turn=2,
        event_log=[RuntimeEvent(type="turn_started", turn_no=1, message="开始")],
    )
    packet = build_narration_input_packet(
        resolution=resolution,
        session=session,
        module=runtime._load_module(session.module_id),  # noqa: SLF001
    )
    return NarrationPromptBuilder().build(packet), packet


def test_callable_agent_adapts_structured_mapping_to_draft() -> None:
    prompt, packet = _prompt_and_packet()
    event_id = packet.event_refs[0].event_id
    agent = CallableKeeperRenderAgent(
        lambda _prompt, _packet, _memories: {
            "public_text": "第 1 回合开始。",
            "source_event_ids": [event_id],
            "cited_memory_ids": [],
        }
    )

    draft = agent.render(prompt, packet, [])

    assert isinstance(draft, KeeperNarrationDraft)
    assert draft.source_event_ids == [event_id]
    assert not hasattr(agent, "persist_record")
    assert not hasattr(agent, "mutate_state")


def test_static_agent_returns_draft_without_persistence_methods() -> None:
    prompt, packet = _prompt_and_packet()
    event_id = packet.event_refs[0].event_id
    agent = StaticKeeperRenderAgent(
        KeeperNarrationDraft(
            public_text="开始。",
            source_event_ids=[event_id],
        )
    )

    draft = agent.render(prompt, packet, [])

    assert draft.public_text == "开始。"
    assert not hasattr(agent, "persist_record")
