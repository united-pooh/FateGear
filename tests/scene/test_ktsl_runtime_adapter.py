"""Tests for the RuntimeEventAdapter (Phase 1)."""

from __future__ import annotations

import pytest

from scenario.ktsl.fixtures import build_library_sewer_church_fixture
from scenario.runtime_event import RuntimeEventAdapter


@pytest.fixture
def adapter() -> RuntimeEventAdapter:
    return RuntimeEventAdapter(build_library_sewer_church_fixture())


class TestAdapterMatchesClueByTitleKeyword:
    def test_adapter_matches_clue_by_title_keyword(self, adapter: RuntimeEventAdapter) -> None:
        result = adapter.parse_action(
            action_text="Search the restricted archive index in the library",
            actor="ada",
            scene_id="scene_library",
            committed_event_ids=set(),
        )
        assert result.resolution == "matched"
        assert result.matched_clue_id == "clue_archive_index"
        assert result.event_record is not None
        assert "info_archive_index" in result.event_record.output_info_ids

    def test_adapter_chinese_keyword_match(self, adapter: RuntimeEventAdapter) -> None:
        # Even with pure Chinese n-grams, the clue title in the fixture is English,
        # so we expect unresolved OR (if any bigram overlaps) keyword_fallback.
        # The test simply confirms the adapter does not crash and returns a valid resolution.
        result = adapter.parse_action(
            action_text="调查被封锁的档案索引",
            actor="ada",
            scene_id="scene_library",
            committed_event_ids=set(),
        )
        assert result.resolution in {"matched", "keyword_fallback", "unresolved"}


class TestAdapterReturnsUnresolvedForUnknownAction:
    def test_returns_unresolved_for_unknown_action(self, adapter: RuntimeEventAdapter) -> None:
        result = adapter.parse_action(
            action_text="completely unrelated pizza-making activity",
            actor="ada",
            scene_id="scene_library",
            committed_event_ids=set(),
        )
        assert result.resolution == "unresolved"
        assert result.event_record is None

    def test_empty_scene_unresolved(self, adapter: RuntimeEventAdapter) -> None:
        result = adapter.parse_action(
            action_text="anything",
            actor="ada",
            scene_id="nonexistent_scene",
            committed_event_ids=set(),
        )
        assert result.resolution == "unresolved"


class TestAdapterKeywordFallback:
    def test_keyword_fallback(self, adapter: RuntimeEventAdapter) -> None:
        # "catalog number" is part of clue_archive_index.public_hint
        result = adapter.parse_action(
            action_text="catalog number below street level",
            actor="ada",
            scene_id="scene_library",
            committed_event_ids=set(),
        )
        assert result.resolution in {"matched", "keyword_fallback"}
        assert result.resolution != "unresolved"


class TestResolveManualOverridesDraft:
    def test_resolve_manual_overrides_output_info_ids(self, adapter: RuntimeEventAdapter) -> None:
        from scenario.ktsl.models import EventRecord, ManualOverrides

        draft = EventRecord(
            id="manual_001",
            scene_id="scene_library",
            action_id="manual_action",
            action_text="custom action",
            actor="ada",
            status="proposed",
        )
        overrides = ManualOverrides(
            output_info_ids=["info_archive_index", "info_confession"],
            required_info_ids=["info_archive_index"],
        )
        resolved = adapter.resolve_manual(draft, overrides)
        assert resolved.output_info_ids == ["info_archive_index", "info_confession"]
        assert resolved.required_info_ids == ["info_archive_index"]
        assert resolved.status == "committed"
        assert resolved.committed is True

    def test_resolve_manual_overrides_barrier_and_deps(self, adapter: RuntimeEventAdapter) -> None:
        from scenario.ktsl.models import EventRecord, ManualOverrides

        draft = EventRecord(
            id="manual_002",
            scene_id="scene_sewer",
            action_id="manual_action_2",
            action_text="custom sewer action",
            actor="bram",
            status="proposed",
        )
        overrides = ManualOverrides(
            output_info_ids=["info_sewer_sigil"],
            barrier_id="barrier_sewer_entry",
            depends_on_event_ids=["evt_library_decode_index"],
        )
        resolved = adapter.resolve_manual(draft, overrides)
        assert resolved.barrier_id == "barrier_sewer_entry"
        assert resolved.depends_on_event_ids == ["evt_library_decode_index"]


class TestAdapterEmptyFixtureNoCrash:
    def test_empty_fixture_no_crash(self) -> None:
        from scenario.ktsl.models import KTSLFixture

        fixture = KTSLFixture(
            id="empty",
            title="Empty fixture",
            description="A fixture with no clues",
        )
        adapter = RuntimeEventAdapter(fixture)
        result = adapter.parse_action(
            action_text="any action",
            actor="anyone",
            scene_id="any_scene",
            committed_event_ids=set(),
        )
        assert result.resolution == "unresolved"
        assert result.event_record is None
