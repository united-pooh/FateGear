"""Tests for KTSL stage pipeline registration + no-op default behavior."""
from __future__ import annotations

import pytest

from scenario.runtime.engine import SceneRuntime
from tests.scene.card_fixtures import build_player_cards


class TestStagePipelineRegistration:
    def test_runtime_exposes_ktsl_stage_registration(self) -> None:
        runtime = SceneRuntime(roll_provider=lambda: 1)
        assert hasattr(runtime, "register_ktsl_stages")

    def test_register_accepts_stage_list(self) -> None:
        runtime = SceneRuntime(roll_provider=lambda: 1)
        sentinel = object()
        runtime.register_ktsl_stages([sentinel])
        assert runtime._ktsl_stages == [sentinel]

    def test_default_ktsl_stages_is_empty(self) -> None:
        runtime = SceneRuntime(roll_provider=lambda: 1)
        assert runtime._ktsl_stages == []
