"""Tests for KTSLLedger data model."""
from __future__ import annotations

import pytest
from scenario.ktsl.models import KTSLLedger


class TestKTSLLedgerEmpty:
    def test_empty_ledger_has_no_scenes(self) -> None:
        ledger = KTSLLedger.empty(module_id="test_mod")
        assert ledger.scenes == {}
        assert ledger.events == []
        assert ledger.module_id == "test_mod"

    def test_empty_ledger_snapshot_is_stable(self) -> None:
        ledger = KTSLLedger.empty(module_id="m")
        snap = ledger.snapshot()
        assert snap["module_id"] == "m"
        assert snap["committed_count"] == 0
