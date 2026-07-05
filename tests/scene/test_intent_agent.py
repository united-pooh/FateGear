from __future__ import annotations

from scenario.agent.intent_agent import _normalize_intent_decision_payload
from scenario.agent.models import IntentAgentDecision


def test_intent_agent_accepts_normalized_intent_result_shape() -> None:
    payload = _normalize_intent_decision_payload(
        {
            "accepted": True,
            "confidence": 0.9,
            "matched_kind": "freeform",
            "matched_id": "llm_freeform",
            "intent_payload": {
                "type": "freeform",
                "text": "环顾四周",
                "freeform_kind": "generic",
                "risk_hint": "自由观察，可由 KP 裁定。",
            },
            "candidates": ["自由观察/感知"],
        }
    )

    decision = IntentAgentDecision.model_validate(payload)

    assert decision.intent_type == "freeform"
    assert decision.confidence == 0.9
    assert decision.freeform_kind == "generic"
    assert decision.risk_hint == "自由观察，可由 KP 裁定。"


def test_intent_agent_accepts_longcat_payload_alias_shape() -> None:
    payload = _normalize_intent_decision_payload(
        {
            "accepted": True,
            "matched": "freeform:observe",
            "payload": {
                "type": "freeform",
                "text": "环顾四周",
            },
            "question": "",
            "candidates": ["自由观察/感知"],
        }
    )

    decision = IntentAgentDecision.model_validate(payload)

    assert decision.intent_type == "freeform"
    assert decision.confidence == 0.5
    assert decision.freeform_kind == "generic"
    assert decision.candidates == ["自由观察/感知"]


def test_intent_agent_converts_rejected_normalized_result_to_clarify() -> None:
    payload = _normalize_intent_decision_payload(
        {
            "accepted": False,
            "confidence": 0.2,
            "clarification_question": "请说明你的角色要做什么。",
            "candidates": ["自由观察/感知"],
        }
    )

    decision = IntentAgentDecision.model_validate(payload)

    assert decision.intent_type == "clarify"
    assert decision.clarification_question == "请说明你的角色要做什么。"
    assert decision.candidates == ["自由观察/感知"]


def test_intent_agent_coerces_null_optional_fields() -> None:
    payload = _normalize_intent_decision_payload(
        {
            "intent_type": "freeform",
            "confidence": None,
            "freeform_kind": None,
            "intended_target": None,
            "risk_hint": None,
            "clarification_question": None,
            "candidates": None,
            "rationale": None,
        }
    )

    decision = IntentAgentDecision.model_validate(payload)

    assert decision.intent_type == "freeform"
    assert decision.confidence == 0.0
    assert decision.risk_hint == ""
    assert decision.candidates == []
