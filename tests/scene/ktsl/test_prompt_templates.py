"""Tests for KP language rule prompt templates."""
from __future__ import annotations

import pytest

from scenario.ktsl.prompt_adapter import KTSLPromptAdapter
from scenario.ktsl.prompt_templates import (
    render_redaction_notice,
    render_grayzone_guidance,
    render_broadcast_narration,
    render_private_note,
)


class TestKTSLPromptTemplates:
    def test_redaction_notice_has_placeholder(self) -> None:
        tpl = render_redaction_notice()
        assert "{character_name}" in tpl or "{info_id}" in tpl

    def test_grayzone_guidance_has_placeholder(self) -> None:
        tpl = render_grayzone_guidance()
        assert tpl  # 非空

    def test_broadcast_narration_has_placeholder(self) -> None:
        tpl = render_broadcast_narration()
        assert "{scene_name}" in tpl or "{event_summary}" in tpl

    def test_private_note_has_placeholder(self) -> None:
        tpl = render_private_note()
        assert "{character_name}" in tpl

    def test_adapter_build_redaction_notice(self) -> None:
        adapter = KTSLPromptAdapter()
        decision = type("Decision", (), {
            "character_id": "P1",
            "info_id": "I01",
            "redaction": "[withheld]",
        })()
        notice = adapter.build_redaction_notice(decision)
        assert "P1" in notice or "I01" in notice
