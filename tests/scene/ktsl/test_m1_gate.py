"""M1 gate: paper fixture converts into a valid KTSLLedger and persists."""
from __future__ import annotations


from scenario.ktsl.fixtures import build_library_sewer_church_fixture
from scenario.ktsl.models import KTSLLedger
from scenario.ktsl.wizard import build_spec_from_fixture


class TestM1Gate:
    def test_paper_fixture_converts_to_ledger(self) -> None:
        fixture = build_library_sewer_church_fixture()
        spec = build_spec_from_fixture(fixture)
        ledger = KTSLLedger.from_module_spec(
            module_id="paper_library_sewer_church", spec=spec
        )
        assert "library" in ledger.scenes
        assert "sewer" in ledger.scenes
        assert "church" in ledger.scenes

    def test_ledger_serializes_to_json(self, tmp_path) -> None:
        fixture = build_library_sewer_church_fixture()
        spec = build_spec_from_fixture(fixture)
        ledger = KTSLLedger.from_module_spec(module_id="m", spec=spec)
        out = tmp_path / "ledger.json"
        out.write_text(ledger.model_dump_json())
        loaded = KTSLLedger.model_validate_json(out.read_text())
        assert len(loaded.scenes) == len(ledger.scenes)

    def test_schema_validator_passes_clean_spec(self) -> None:
        fixture = build_library_sewer_church_fixture()
        spec = build_spec_from_fixture(fixture)
        from scenario.ktsl.stages import SchemaValidatorStage
        stage = SchemaValidatorStage()
        report = stage.validate(spec)
        assert report.is_valid, f"issues={report.issues}"
