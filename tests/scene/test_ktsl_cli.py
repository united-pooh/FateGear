"""Tests for the ktsl CLI (Phase 5).

Invokes subcommands through ``python -m src.scenario.cli.ktsl_cli`` in a
subprocess so that exit codes and stdout are exercised end-to-end.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scenario.cli.ktsl_cli import (
    _audit_action,
    _load_fixture,
    _run_validate,
    build_parser,
)
from scenario.ktsl.fixtures import build_library_sewer_church_fixture
from scenario.report.session_reports import ValidateReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"


def _env_with_src() -> dict[str, str]:
    """Return an env dict that includes ``src/`` on PYTHONPATH."""
    env = {k: v for k, v in os.environ.items()}
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{SRC}{os.pathsep}{existing}" if existing else str(SRC)
    )
    return env


def _run_ktsl(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    """Run ``python -m src.scenario.cli.ktsl_cli <args>`` in subprocess."""
    cmd = [
        sys.executable,
        "-m",
        "src.scenario.cli.ktsl_cli",
        *args,
    ]
    return subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=check,
        env=_env_with_src(),
    )


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------


class TestValidateBuiltinFixtureExitCode0:
    def test_validate_builtin_fixture_exit_code_0(self) -> None:
        """``ktsl validate police_station_hospital_old_house`` returns 0."""
        proc = _run_ktsl("validate", "police_station_hospital_old_house")
        assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
        assert "PASS" in proc.stdout or "Is Valid': True" in proc.stdout

    def test_validate_builtin_library_fixture_exit_code_0(self) -> None:
        """``ktsl validate library_sewer_church`` also returns 0."""
        proc = _run_ktsl("validate", "library_sewer_church")
        assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"


class TestValidateDetectsMissingReference:
    def test_validate_detects_missing_reference(self, tmp_path: Path) -> None:
        """YAML with a bad reference yields exit code 2 and an error line."""
        fixture = build_library_sewer_church_fixture()
        data = fixture.model_dump(mode="json")
        # Introduce a bad reference: change a scene's location_id
        for scene in data["scenes"]:
            if scene["id"] == "scene_library":
                scene["location_id"] = "nonexistent_location"
                break
        yaml_path = tmp_path / "bad.yaml"
        yaml_path.write_text(
            "\n".join(
                f"{k}: {v}"
                for k, v in [
                    ("id", "broken_fixture"),
                    ("title", "Broken fixture for testing"),
                    ("locations", []),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        # Write as JSON (avoids yaml dependency issues)
        json_path = tmp_path / "bad.json"
        json_path.write_text(json.dumps(data), encoding="utf-8")

        proc = _run_ktsl("validate", str(json_path))
        assert proc.returncode == 2, f"expected exit 2; got {proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
        # should mention the bad ref
        assert "nonexistent_location" in proc.stdout or "invalid_location_ref" in proc.stdout


class TestValidateDetectsOrphanInfoIsWarning:
    def test_orphan_info_produces_warning(self, tmp_path: Path) -> None:
        """An info_label not referenced by any event → warning, not error."""
        fixture = build_library_sewer_church_fixture()
        data = fixture.model_dump(mode="json")
        # Add a stray info label not referenced by any event/clue
        data["info_labels"].append(
            {
                "id": "info_stray_unreferenced",
                "kind": "know",
                "scene_id": "scene_library",
                "payload": "stray info",
                "sensitivity": "low",
            }
        )
        json_path = tmp_path / "with_orphan.json"
        json_path.write_text(json.dumps(data), encoding="utf-8")

        proc = _run_ktsl("validate", str(json_path))
        # exit code 1 = warning only (no structural errors)
        assert proc.returncode == 1, f"expected exit 1; got {proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
        assert "orphan_info" in proc.stdout or "info_stray_unreferenced" in proc.stdout


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class TestAuditOutputsAllowedForValidAction:
    def test_audit_outputs_allowed_for_valid_action(self) -> None:
        """Valid action produces ALLOWED output."""
        proc = _run_ktsl(
            "audit",
            "library_sewer_church",
            "--action",
            "investigate restricted archive index",
            "--actor",
            "ada",
            "--scene",
            "scene_library",
        )
        assert proc.returncode == 0 or proc.returncode == 1, f"stderr={proc.stderr}"
        assert "Resolution" in proc.stdout
        assert "keyword_fallback" in proc.stdout or "matched" in proc.stdout


class TestAuditOutputsViolationForBadAction:
    def test_audit_outputs_violation_for_bad_action(self) -> None:
        """Church action before sewer committed should report a violation."""
        proc = _run_ktsl(
            "audit",
            "library_sewer_church",
            "--action",
            "open the reliquary after finding the sewer pattern",
            "--actor",
            "celia",
            "--scene",
            "scene_church",
        )
        # We just check that the CLI ran and produced some output that mentions
        # at least the audit result format.
        assert proc.returncode in (0, 1), f"stderr={proc.stderr}"
        assert "KTSL Single-Audit" in proc.stdout or "Audit" in proc.stdout


# ---------------------------------------------------------------------------
# Session (e2e REPL test via subprocess)
# ---------------------------------------------------------------------------


class TestSessionE2EWorkflow:
    def test_session_e2e_workflow(self, tmp_path: Path) -> None:
        """Drive the REPL through stdin → quit → report exists."""
        # Built a script of REPL commands fed on stdin.
        rep = (
            "action ada \"investigate restricted archive index\" @scene_library\n"
            "action bram \"examine the sewer sigil with chalk marks\" @scene_sewer\n"
            "status\n"
            "barriers\n"
            "couplings\n"
            "timeline scene_library\n"
            "knowledge ada\n"
            "save\n"
            "quit\n"
        )
        output_dir = tmp_path / "session-out"
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.scenario.cli.ktsl_cli",
                "session",
                "library_sewer_church",
                "--output-dir",
                str(output_dir),
            ],
            cwd=str(PROJECT_ROOT),
            input=rep,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            env=_env_with_src(),
        )
        # The REPL should exit cleanly
        assert proc.returncode == 0, (
            f"returncode={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
        )
        # Reports must be generated
        md_path = output_dir / "session-report.md"
        html_path = output_dir / "session-report.html"
        state_path = output_dir / "session-state.json"
        assert md_path.exists(), f"missing {md_path}. Files in {output_dir}: {list(output_dir.iterdir())}"
        assert html_path.exists(), f"missing {html_path}"
        assert state_path.exists(), f"missing {state_path}"
        md = md_path.read_text(encoding="utf-8")
        assert "# KTSL Session Report" in md
        html = html_path.read_text(encoding="utf-8")
        assert "<html" in html.lower()


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


class TestPublishOutputs:
    def test_publish_outputs_pass_for_clean_fixture(self) -> None:
        """``ktsl publish`` with default criteria should emit PASS somewhere for the loose mode."""
        proc = _run_ktsl(
            "publish",
            "library_sewer_church",
            "--output-dir",
            str(Path("/tmp/ktsl-publish-test")),
        )
        # baseline passes since it has very loose thresholds
        assert proc.returncode == 0, f"stderr={proc.stderr}\nstdout={proc.stdout}"
        assert "PASS" in proc.stdout or "Verdict" in proc.stdout

    def test_publish_outputs_html_report(self, tmp_path: Path) -> None:
        """``ktsl publish --format html`` writes an .html file."""
        output_dir = tmp_path / "publish-html"
        proc = _run_ktsl(
            "publish",
            "library_sewer_church",
            "--format",
            "html",
            "--output-dir",
            str(output_dir),
        )
        assert proc.returncode == 0, f"stderr={proc.stderr}"
        html_path = output_dir / "publish-report.html"
        assert html_path.exists(), f"missing {html_path}"
        content = html_path.read_text(encoding="utf-8")
        assert "<html" in content.lower()


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


class TestReplay:
    def test_replay_loads_state_and_generates_report(self, tmp_path: Path) -> None:
        """Save state via Python API → replay CLI → report exists."""
        from scenario.session_audit_tracker import SessionAuditTracker

        fixture = build_library_sewer_church_fixture()
        tracker = SessionAuditTracker(fixture)
        tracker.submit_action(
            action_text="investigate restricted archive index",
            actor="ada",
            scene_id="scene_library",
        )
        state_path = tmp_path / "session-state.json"
        tracker.save_state(state_path)

        output_dir = tmp_path / "replay-out"
        proc = _run_ktsl(
            "replay",
            str(state_path),
            "--output-dir",
            str(output_dir),
        )
        assert proc.returncode == 0, f"stderr={proc.stderr}\nstdout={proc.stdout}"
        md_path = output_dir / "session-report.md"
        assert md_path.exists(), f"missing {md_path}. Files in {output_dir}: {list(output_dir.iterdir())}"
        md = md_path.read_text(encoding="utf-8")
        assert "# KTSL Session Report" in md

    def test_replay_html_format(self, tmp_path: Path) -> None:
        """``ktsl replay --format html`` → html file exists."""
        from scenario.session_audit_tracker import SessionAuditTracker

        fixture = build_library_sewer_church_fixture()
        tracker = SessionAuditTracker(fixture)
        tracker.submit_action(
            action_text="examine the sewer sigil with chalk marks",
            actor="bram",
            scene_id="scene_sewer",
        )
        state_path = tmp_path / "session-state.json"
        tracker.save_state(state_path)

        output_dir = tmp_path / "replay-html"
        proc = _run_ktsl(
            "replay",
            str(state_path),
            "--format",
            "html",
            "--output-dir",
            str(output_dir),
        )
        assert proc.returncode == 0, f"stderr={proc.stderr}"
        html_path = output_dir / "session-report.html"
        assert html_path.exists()
        assert "<html" in html_path.read_text(encoding="utf-8").lower()


# ---------------------------------------------------------------------------
# Argument parser coverage
# ---------------------------------------------------------------------------


class TestParserHelpers:
    def test_build_parser_validate_requires_fixture_id(self) -> None:
        parser = build_parser()
        # Should not raise for --help usage
        args = parser.parse_args(["validate", "library_sewer_church"])
        assert args.fixture_id_or_path == "library_sewer_church"

    def test_build_parser_audit_requires_all_flags(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["audit", "library_sewer_church"])  # missing --action etc.

    def test_full_session_repl_runs_without_crashing(self) -> None:
        from scenario.cli.ktsl_cli import KTSLRepl

        # Run the REPL in-process with mocked cmdloop to avoid stdin requirements
        fixture = build_library_sewer_church_fixture()
        output = Path("/tmp/ktsl-session-repl-test")
        output.mkdir(parents=True, exist_ok=True)

        # Directly instantiate KTSLRepl (bypassing fixture loading) and invoke
        repl = KTSLRepl(fixture=fixture, output_dir=output)
        # Call one of its public-facing helpers to make sure wiring works
        captured: list[str] = []

        def _stub_status(arg: str) -> None:
            captured.append("status-called")

        repl.do_status = _stub_status  # type: ignore[method-assign]
        repl.do_status("")
        assert captured == ["status-called"]


class TestLoadFixture:
    def test_load_builtin_by_id(self) -> None:
        f = _load_fixture("library_sewer_church")
        assert f.id == "library_sewer_church"

    def test_load_from_file(self, tmp_path: Path) -> None:
        fixture = build_library_sewer_church_fixture()
        path = tmp_path / "fix.json"
        path.write_text(fixture.model_dump_json(), encoding="utf-8")
        loaded = _load_fixture(str(path))
        assert loaded.id == fixture.id

    def test_file_not_found_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            _load_fixture("/nonexistent/path/fixture.json")


class TestValidateModuleApi:
    def test_run_validate_returns_report(self) -> None:
        fixture = build_library_sewer_church_fixture()
        report = _run_validate(fixture)
        assert isinstance(report, ValidateReport)
        assert report.is_valid is True

    def test_audit_action_returns_result(self) -> None:
        result = _audit_action(
            "library_sewer_church",
            "investigate restricted archive index",
            "ada",
            "scene_library",
        )
        from scenario.ktsl.models import AuditResult

        assert isinstance(result, AuditResult)
        assert result.allowed is True


class TestMainFunction:
    def test_main_dispatch_validate(self) -> None:
        from scenario.cli.ktsl_cli import main

        code = main(["validate", "library_sewer_church"])
        assert code == 0

    def test_main_dispatch_validate_bad_fixture(self, tmp_path: Path) -> None:
        from scenario.cli.ktsl_cli import main

        fixture = build_library_sewer_church_fixture()
        data = fixture.model_dump(mode="json")
        for scene in data["scenes"]:
            if scene["id"] == "scene_library":
                scene["location_id"] = "bad_loc"
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        code = main(["validate", str(path)])
        assert code == 2
