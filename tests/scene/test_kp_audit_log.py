from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from scenario.agent import KeeperNarration, NPCDialogue, PrivateClue
from scenario.api import ScenarioService
from scenario.runtime import SceneRuntime


@dataclass
class _Meta:
    fallback_used: bool = False
    input_tokens: int = 12
    output_tokens: int = 34
    latency_ms: int = 56
    attempt: int = 1
    model_id: str = "audit-test-narrator"


@dataclass
class _Record:
    prompt: Any
    output: Any
    meta: _Meta = field(default_factory=_Meta)


class _AuditNarrator:
    async def call(self, prompt: Any) -> _Record:
        return _Record(
            prompt=prompt,
            output=KeeperNarration(
                public_narration="公共旁白：门后传来铁轨震动。",
                npc_dialogues=[
                    NPCDialogue(
                        npc_id="attendant",
                        npc_name="乘务员",
                        dialogue="别回头，继续往前。",
                    )
                ],
                private_clues=[
                    PrivateClue(
                        player_id="keeper",
                        clue_text="你注意到钥匙孔边缘有新鲜划痕。",
                        related_action_id="inspect_note",
                    )
                ],
                keeper_hint="KP提示：下一轮推进后方威胁。",
                is_fallback=False,
            ),
        )


def test_scenario_service_writes_kp_jsonl_audit_log(tmp_path) -> None:
    log_path = tmp_path / "kp-flow.jsonl"
    runtime = SceneRuntime(
        roll_provider=lambda: 1,
        render_agent=_AuditNarrator(),
    )
    service = ScenarioService(
        runtime=runtime,
        kp_audit_log_path=log_path,
    )

    created = service.create_party({"module_id": "generic_mvp", "creator_id": "keeper"})
    service.submit_text_intent(
        created.session_id,
        {"player_id": "keeper", "text": "我去储藏室"},
    )
    asyncio.run(service.resolve_turn(created.session_id, expected_turn=1))

    events = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]

    assert [event["event_type"] for event in events] == [
        "party_created",
        "text_intent_submitted",
        "turn_resolved",
    ]
    assert events[1]["raw_text"] == "我去储藏室"
    assert events[1]["normalization"]["intent_payload"] == {
        "type": "move",
        "target_scene_id": "storage",
    }

    resolved = events[2]
    scene = resolved["kp_view"]["scenes"][0]
    assert scene["outcomes"][0]["intent_type"] == "move"
    assert scene["public_narration"] == "公共旁白：门后传来铁轨震动。"
    assert scene["npc_dialogues"][0]["dialogue"] == "别回头，继续往前。"
    assert scene["private_clues"][0]["clue_text"] == "你注意到钥匙孔边缘有新鲜划痕。"
    assert scene["keeper_hint"] == "KP提示：下一轮推进后方威胁。"
    assert resolved["turn_resolution"]["agent_calls"][0]["stage"] == "render"
