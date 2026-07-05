"""Tests for ktsl wizard."""
from __future__ import annotations


from scenario.ktsl.fixtures import build_library_sewer_church_fixture
from scenario.ktsl.wizard import build_spec_from_fixture


class TestBuildSpecFromFixture:
    def test_build_spec_from_library_fixture_has_three_scenes(self) -> None:
        fixture = build_library_sewer_church_fixture()
        spec = build_spec_from_fixture(fixture)
        scene_ids = {s.scene_id for s in spec.scenes}
        assert "library" in scene_ids
        assert "sewer" in scene_ids
        assert "church" in scene_ids

    def test_build_spec_creates_info_labels_from_keeper_truths(self) -> None:
        fixture = build_library_sewer_church_fixture()
        spec = build_spec_from_fixture(fixture)
        assert spec.info_labels
        # Each info_label should have redaction since they're sensitive
        for info in spec.info_labels:
            if info.sensitivity in {"medium", "high", "keeper"}:
                assert info.redaction, f"info {info.info_id} missing redaction"

    def test_build_spec_creates_initial_knowledge(self) -> None:
        fixture = build_library_sewer_church_fixture()
        spec = build_spec_from_fixture(fixture)
        assert spec.initial_knowledge
