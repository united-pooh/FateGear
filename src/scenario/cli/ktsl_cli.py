"""KTSL KP toolchain CLI (Phase 5).

Provides five subcommands:
    ktsl validate     Structural integrity check of a KTSL fixture
    ktsl audit        Single-action audit with committed-event prefill
    ktsl session      Interactive REPL for a full session
    ktsl publish      Publish-gate evaluation with multi-mode thresholds
    ktsl replay       Regenerate reports from a saved session-state JSON

The CLI is intentionally self-contained: it wires together modules from
``src.scenario.ktsl`` and ``src.scenario.report`` without touching the main
FastAPI entry point (``main.py``).

Run with:
    python -m src.scenario.cli.ktsl_cli <subcommand> [args]
"""

from __future__ import annotations

import argparse
import cmd
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scenario.ktsl.fixtures import (
    KTSL_FIXTURE_IDS,
    get_ktsl_fixture,
    list_ktsl_fixtures,
)
from scenario.ktsl.models import (
    BarrierState,
    CouplingState,
    KTSLFixture,
    KnowledgeItem,
    MetricSummary,
    RunMode,
    SessionConfig,
    SessionSummary,
)
from scenario.publish_gate import PublishGate
from scenario.report.html_renderer import HTMLRenderer
from scenario.report.markdown_renderer import MarkdownRenderer
from scenario.report.session_reports import (
    BarrierStateView,
    CouplingStateView,
    EventSummary,
    KnowledgeItemView,
    ModuleStaticCheck,
    PublishReport,
    PublishGateResult,
    SessionReport,
    SessionConfig as ReportSessionConfig,
    ValidateIssue,
    ValidateReport,
    ViolationEvent,
)
from scenario.session_audit_tracker import SessionAuditTracker

# ---------------------------------------------------------------------------
# Helpers: fixture loading, time, renderer dispatch
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_fixture(fixture_id_or_path: str) -> KTSLFixture:
    """Load *fixture_id_or_path* — builtin id or YAML file path."""
    # 1. Builtin id
    try:
        return get_ktsl_fixture(fixture_id_or_path)
    except KeyError:
        pass
    # 2. YAML file or JSON file
    path = Path(fixture_id_or_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Unknown fixture id and no file at path: {fixture_id_or_path}"
        )
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]

        data = yaml.safe_load(text)
    except ImportError:
        data = json.loads(text)
    return KTSLFixture.model_validate(data)


def _to_report_session_config(cfg: Any) -> Any:
    """Convert a ``ktsl.models.SessionConfig`` to the report-side duplicate."""
    if cfg is None:
        return None
    if isinstance(cfg, ReportSessionConfig):
        return cfg
    try:
        return ReportSessionConfig(**cfg.model_dump())
    except AttributeError:
        return ReportSessionConfig.model_validate(cfg)


def _save_report(content: str, output_dir: Path, filename: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / filename
    out.write_text(content, encoding="utf-8")
    return out


def _render_publish_report(
    gate_result: PublishGateResult,
    fixture: KTSLFixture,
    criteria: Any,
    output_format: str,
) -> str:
    """Convert PublishGateResult into a rendered string (md or html)."""
    from scenario.ktsl.models import ModeThresholds as _MT

    thresholds: dict[RunMode, _MT] = {}
    if hasattr(criteria, "thresholds"):
        thresholds = criteria.thresholds

    # Build PublishReport from plain dicts (avoid pydantic model coercion issues)
    per_mode_payload = []
    for m in gate_result.per_mode:
        per_mode_payload.append({
            "mode": m.mode,
            "passed": m.passed,
            "metrics": m.metrics.model_dump(),
            "failures": list(m.failures),
            "warnings": list(m.warnings),
        })
    thresholds_payload: dict[str, dict[str, Any]] = {}
    for mode, mt in thresholds.items():
        thresholds_payload[mode] = mt.model_dump()
    report = PublishReport(
        fixture_id=gate_result.fixture_id,
        fixture_title=fixture.title,
        evaluated_at=gate_result.evaluated_at,
        criteria_version=gate_result.criteria_version,
        overall_pass=gate_result.overall_pass,
        per_mode=per_mode_payload,
        thresholds=thresholds_payload,
    )
    if output_format == "html":
        return HTMLRenderer().render_publish(report)
    return MarkdownRenderer().render_publish(report)


# ---------------------------------------------------------------------------
# validate: structural integrity check
# ---------------------------------------------------------------------------


def _run_validate(fixture: KTSLFixture) -> ValidateReport:
    """Execute all structural checks and return a ValidateReport."""
    issues: list[ValidateIssue] = []

    valid_ids = set()
    for loc in fixture.locations:
        valid_ids.add(loc.id)
    for scene in fixture.scenes:
        valid_ids.add(scene.id)
    for info in fixture.info_labels:
        valid_ids.add(info.id)
    for clue in fixture.clues:
        valid_ids.add(clue.id)
    for event in fixture.events:
        valid_ids.add(event.id)
    for barrier in fixture.barriers:
        valid_ids.add(barrier.id)
    for coupling in fixture.couplings:
        valid_ids.add(coupling.id)
    for truth in fixture.keeper_truths:
        valid_ids.add(truth.id)
    for dep in fixture.causal_dependencies:
        valid_ids.add(dep.id)

    # 1. SceneCard.location_id references valid location
    for scene in fixture.scenes:
        if scene.location_id and scene.location_id not in {
            loc.id for loc in fixture.locations
        }:
            issues.append(
                ValidateIssue(
                    level="error",
                    code="invalid_location_ref",
                    message=f"Scene '{scene.id}' references unknown location '{scene.location_id}'",
                    resource_id=scene.id,
                )
            )

    # 2. EventRecord.info_id / clue_id references
    referenced_info_ids: set[str] = set()
    for event in fixture.events:
        for info_id in event.output_info_ids:
            referenced_info_ids.add(info_id)
            if info_id not in {i.id for i in fixture.info_labels}:
                issues.append(
                    ValidateIssue(
                        level="error",
                        code="invalid_info_ref",
                        message=f"Event '{event.id}' outputs unknown info '{info_id}'",
                        resource_id=event.id,
                    )
                )
        for info_id in event.required_info_ids:
            referenced_info_ids.add(info_id)
            if info_id not in {i.id for i in fixture.info_labels}:
                issues.append(
                    ValidateIssue(
                        level="error",
                        code="invalid_info_ref",
                        message=f"Event '{event.id}' requires unknown info '{info_id}'",
                        resource_id=event.id,
                    )
                )
        for info_id in event.observed_info_ids:
            referenced_info_ids.add(info_id)
        for info_id in event.known_info_ids:
            referenced_info_ids.add(info_id)

    # 3. ClueRecord.info_id references valid info
    for clue in fixture.clues:
        if clue.info_id and clue.info_id not in {i.id for i in fixture.info_labels}:
            issues.append(
                ValidateIssue(
                    level="error",
                    code="invalid_info_ref",
                    message=f"Clue '{clue.id}' references unknown info '{clue.info_id}'",
                    resource_id=clue.id,
                )
            )
        for info_id in clue.output_info_ids:
            referenced_info_ids.add(info_id)
            if info_id not in {i.id for i in fixture.info_labels}:
                issues.append(
                    ValidateIssue(
                        level="error",
                        code="invalid_info_ref",
                        message=f"Clue '{clue.id}' outputs unknown info '{info_id}'",
                        resource_id=clue.id,
                    )
                )
        for info_id in clue.required_info_ids:
            referenced_info_ids.add(info_id)
            if info_id not in {i.id for i in fixture.info_labels}:
                issues.append(
                    ValidateIssue(
                        level="error",
                        code="invalid_info_ref",
                        message=f"Clue '{clue.id}' requires unknown info '{info_id}'",
                        resource_id=clue.id,
                    )
                )

    # 4. Barrier references valid scene / location / event / info
    # Barriers may reference scene_ids or location_ids (both are valid).
    valid_scene_or_loc_ids = {s.id for s in fixture.scenes} | {loc.id for loc in fixture.locations}
    for barrier in fixture.barriers:
        for sid in barrier.scene_ids:
            if sid not in valid_scene_or_loc_ids:
                issues.append(
                    ValidateIssue(
                        level="error",
                        code="invalid_scene_ref",
                        message=f"Barrier '{barrier.id}' references unknown scene/location '{sid}'",
                        resource_id=barrier.id,
                    )
                )
        for eid in barrier.required_event_ids:
            if eid not in {e.id for e in fixture.events}:
                issues.append(
                    ValidateIssue(
                        level="error",
                        code="invalid_event_ref",
                        message=f"Barrier '{barrier.id}' requires unknown event '{eid}'",
                        resource_id=barrier.id,
                    )
                )
        for info_id in barrier.required_info_ids:
            if info_id not in {i.id for i in fixture.info_labels}:
                issues.append(
                    ValidateIssue(
                        level="error",
                        code="invalid_info_ref",
                        message=f"Barrier '{barrier.id}' requires unknown info '{info_id}'",
                        resource_id=barrier.id,
                    )
                )

    # 5. Coupling references valid source/target scenes + events + info
    for coupling in fixture.couplings:
        if coupling.source_scene_id not in {s.id for s in fixture.scenes}:
            issues.append(
                ValidateIssue(
                    level="error",
                    code="invalid_scene_ref",
                    message=f"Coupling '{coupling.id}' has unknown source scene '{coupling.source_scene_id}'",
                    resource_id=coupling.id,
                )
            )
        if coupling.target_scene_id not in {s.id for s in fixture.scenes}:
            issues.append(
                ValidateIssue(
                    level="error",
                    code="invalid_scene_ref",
                    message=f"Coupling '{coupling.id}' has unknown target scene '{coupling.target_scene_id}'",
                    resource_id=coupling.id,
                )
            )
        for eid in coupling.input_event_ids:
            if eid not in {e.id for e in fixture.events}:
                issues.append(
                    ValidateIssue(
                        level="error",
                        code="invalid_event_ref",
                        message=f"Coupling '{coupling.id}' references unknown event '{eid}'",
                        resource_id=coupling.id,
                    )
                )
        for info_id in coupling.required_info_ids:
            if info_id not in {i.id for i in fixture.info_labels}:
                issues.append(
                    ValidateIssue(
                        level="error",
                        code="invalid_info_ref",
                        message=f"Coupling '{coupling.id}' requires unknown info '{info_id}'",
                        resource_id=coupling.id,
                    )
                )

    # 6. Orphan info_ids (not referenced by any event/clue)
    for info in fixture.info_labels:
        if info.id not in referenced_info_ids:
            issues.append(
                ValidateIssue(
                    level="warning",
                    code="orphan_info",
                    message=f"Info '{info.id}' is not referenced by any event or clue",
                    resource_id=info.id,
                )
            )

    # 7. Circular dependency (among causal_dependencies' event chains)
    # Build graph: event_id -> depends_on_event_ids
    dep_graph: dict[str, list[str]] = {}
    for event in fixture.events:
        if event.depends_on_event_ids:
            dep_graph[event.id] = list(event.depends_on_event_ids)
        else:
            dep_graph[event.id] = []

    def _has_cycle(node: str, visited: set[str], stack: set[str]) -> bool:
        visited.add(node)
        stack.add(node)
        for neighbor in dep_graph.get(node, []):
            if neighbor in stack:
                return True
            if neighbor not in visited and neighbor in dep_graph:
                if _has_cycle(neighbor, visited, stack):
                    return True
        stack.discard(node)
        return False

    cycle_found = False
    visited_global: set[str] = set()
    for node in dep_graph:
        if node not in visited_global:
            if _has_cycle(node, visited_global, set()):
                cycle_found = True
                break
    if cycle_found:
        issues.append(
            ValidateIssue(
                level="error",
                code="circular_dependency",
                message="Circular dependency detected among event depends_on_event_ids chain",
            )
        )

    # 8. Deadlock barrier (all events in the chain can never be committed)
    # Simplification: a barrier requiring an event with a cyclic dep or a
    # required_info_id that can only come from an unsatisfiable event.
    for barrier in fixture.barriers:
        for eid in barrier.required_event_ids:
            event = next((e for e in fixture.events if e.id == eid), None)
            if event is None:
                continue
            # If the event has no output_info_ids and the barrier requires info
            # → impossible to satisfy (the event can never produce the info).
            if barrier.required_info_ids and not event.output_info_ids:
                issues.append(
                    ValidateIssue(
                        level="error",
                        code="deadlock_barrier",
                        message=(
                            f"Barrier '{barrier.id}' requires event '{eid}' "
                            f"but that event produces no info"
                        ),
                        resource_id=barrier.id,
                    )
                )

    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]
    is_valid = not errors
    return ValidateReport(
        fixture_id=fixture.id,
        fixture_title=fixture.title,
        validated_at=_now_iso(),
        is_valid=is_valid,
        issues=issues,
    )


def _exit_code_from_issues(report: ValidateReport) -> int:
    levels = {i.level for i in report.issues}
    if "error" in levels:
        return 2
    if "warning" in levels:
        return 1
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Run ``ktsl validate <fixture_id_or_path>``."""
    fixture = _load_fixture(args.fixture_id_or_path)
    report = _run_validate(fixture)

    md = MarkdownRenderer().render_validate(report)
    print(md)

    out_dir = Path(args.output_dir) if args.output_dir else None
    if out_dir is not None:
        _save_report(md, out_dir, "validate-report.md")
        print(f"\n[Saved] {out_dir / 'validate-report.md'}")

    return _exit_code_from_issues(report)


# ---------------------------------------------------------------------------
# audit: single-action audit
# ---------------------------------------------------------------------------


def _audit_action(
    fixture_id_or_path: str,
    action: str,
    actor: str,
    scene: str,
) -> Any:
    """Return the AuditResult for one action (committed events pre-filled)."""
    fixture = _load_fixture(fixture_id_or_path)
    config = SessionConfig(fixture_id=fixture.id, allow_override=False)
    tracker = SessionAuditTracker(fixture, config=config)
    return tracker.submit_action(
        action_text=action,
        actor=actor,
        scene_id=scene,
    )


def cmd_audit(args: argparse.Namespace) -> int:
    """Run ``ktsl audit --action ... --actor ... --scene ...``."""
    fixture = _load_fixture(args.fixture_id_or_path)
    config = SessionConfig(fixture_id=fixture.id, allow_override=False)
    tracker = SessionAuditTracker(fixture, config=config)

    result = tracker.submit_action(
        action_text=args.action,
        actor=args.actor,
        scene_id=args.scene,
    )

    # Pretty-print the audit result
    lines: list[str] = []
    lines.append("# KTSL Single-Action Audit")
    lines.append("")
    lines.append(f"**Fixture**: `{fixture.id}` ({fixture.title})")
    lines.append(f"**Action**: {args.action}")
    lines.append(f"**Actor**: {args.actor}")
    lines.append(f"**Scene**: {args.scene}")
    lines.append(f"**Resolution**: {result.resolution}")
    lines.append(f"**Allowed**: {result.allowed}")
    lines.append("")
    if result.event_record:
        lines.append(f"**Event ID**: `{result.event_record.id}`")
    if result.matched_clue_id:
        lines.append(f"**Matched Clue**: `{result.matched_clue_id}`")
    if result.violations:
        lines.append(f"## Violations ({len(result.violations)})")
        for v in result.violations:
            lines.append(f"- [{v.severity.upper()}] {v.metric}: {v.message}")
    if result.warnings:
        lines.append(f"## Warnings ({len(result.warnings)})")
        for w in result.warnings:
            lines.append(f"- {w}")
    if result.updated_metrics:
        lines.append("")
        lines.append("## Updated Metrics")
        m = result.updated_metrics
        for field_name in (
            "causal_violation_count",
            "unauthorized_action_count",
            "public_payload_leak_count",
            "spotlight_max_gap_minutes",
            "declassification_completeness",
            "retcon_count",
            "high_coupling_time_drift_minutes",
            "committed_event_count",
            "blocked_event_count",
        ):
            lines.append(f"- {field_name} = {getattr(m, field_name, None)}")

    print("\n".join(lines))

    out_dir = Path(args.output_dir) if args.output_dir else None
    if out_dir is not None:
        content = "\n".join(lines)
        _save_report(content, out_dir, "audit-result.md")
        print(f"\n[Saved] {out_dir / 'audit-result.md'}")

    # exit code: 0 for clean, 1 for violations (warn-only)
    return 1 if result.violations else 0


# ---------------------------------------------------------------------------
# session: interactive REPL
# ---------------------------------------------------------------------------


KTSL_REPL_BANNER = r"""
 __  __   ___   ___   __      ___
|  |/ /  / __| | __|  \ \    / / |
| ' <  | (_ | | _|    \ \/\/ /| |
|_|\_\  \___| |___|    \_/\_/ |_|

  KTSL KP Toolchain — interactive session REPL
  Type 'help' for commands, 'quit' to exit and generate reports.
"""


class KTSLRepl(cmd.Cmd):
    """Interactive session REPL driven by SessionAuditTracker."""

    intro = KTSL_REPL_BANNER
    prompt = "(ktsl) "

    def __init__(
        self,
        fixture: KTSLFixture,
        output_dir: Path,
        allow_override: bool = True,
    ) -> None:
        super().__init__()
        self._tracker = SessionAuditTracker(
            fixture,
            config=SessionConfig(
                fixture_id=fixture.id,
                started_at=_now_iso(),
                allow_override=allow_override,
            ),
        )
        self._fixture = fixture
        self._output_dir = output_dir
        self._ended_at: str = ""

    # ---- commands ----

    def do_action(self, arg: str) -> None:
        """Submit an action:  action <actor> "<action text>" [@<scene_id>]"""
        actor, text, scene_id = _parse_action_line(arg)
        if actor is None:
            print("Usage: action <actor> \"<action text>\" [@<scene_id>]")
            return
        result = self._tracker.submit_action(
            action_text=text,
            actor=actor,
            scene_id=scene_id,
        )
        status_icon = "OK" if result.allowed else "BLOCKED"
        print(f"[{status_icon}] {result.resolution}  event={result.event_record.id if result.event_record else '?'}"
              f"  violations={len(result.violations)}")

    def do_status(self, arg: str) -> None:
        """Print current metrics snapshot."""
        metrics = self._tracker.get_current_metrics()
        summary = self._tracker.get_session_summary()
        print(f"Fixture: {summary.fixture_id} ({summary.fixture_title})")
        print(f"Events: total={summary.total_events}  committed={summary.total_committed}")
        print(f"  causal_violations={metrics.causal_violation_count}")
        print(f"  unauthorized_actions={metrics.unauthorized_action_count}")
        print(f"  public_payload_leaks={metrics.public_payload_leak_count}")
        print(f"  spotlight_max_gap_min={metrics.spotlight_max_gap_minutes}")
        print(f"  declassification_completeness={metrics.declassification_completeness:.2f}")
        print(f"  retcons={metrics.retcon_count}")
        print(f"  high_coupling_drift_min={metrics.high_coupling_time_drift_minutes}")

    def do_timeline(self, arg: str) -> None:
        """Show committed events for a scene:  timeline <scene_id>"""
        scene_id = arg.strip()
        if not scene_id:
            print("Usage: timeline <scene_id>")
            return
        events = self._tracker.get_scene_timeline(scene_id)
        if not events:
            print(f"No events for scene '{scene_id}'.")
            return
        for ev in events:
            info_part = f" -> [{', '.join(ev.output_info_ids)}]" if ev.output_info_ids else ""
            print(f"  #{ev.commit_index or '?':>3} [{ev.status}] {ev.actor}: {ev.action_text}{info_part}")

    def do_knowledge(self, arg: str) -> None:
        """Show knowledge items for a character:  knowledge <character_id>"""
        character_id = arg.strip()
        if not character_id:
            print("Usage: knowledge <character_id>")
            return
        items = self._tracker.get_knowledge_summary(character_id)
        if not items:
            print(f"No knowledge items for '{character_id}'.")
            return
        for item in items:
            leak = " [LEAKED]" if (item.sensitivity not in {"public", "low"}) else ""
            print(f"  [{item.kind}] {item.info_id} ({item.sensitivity}): {item.content_summary[:80]}{leak}")

    def do_barriers(self, arg: str) -> None:
        """Print current barrier states."""
        barriers = self._tracker.get_barrier_states()
        if not barriers:
            print("No barriers configured.")
            return
        for b in barriers:
            print(f"  {b.barrier_id}: {b.status}  "
                  f"events({len(b.satisfied_event_ids)}/{len(b.required_event_ids)})  "
                  f"info({len(b.satisfied_info_ids)}/{len(b.required_info_ids)})")

    def do_couplings(self, arg: str) -> None:
        """Print current coupling states."""
        couplings = self._tracker.get_coupling_states()
        if not couplings:
            print("No couplings configured.")
            return
        for c in couplings:
            active = "ON" if c.active else "--"
            print(f"  {c.coupling_id} [{active}] {c.source_scene_id} -> {c.target_scene_id} "
                  f"({c.mode}, drift={c.drift_minutes}min)")

    def do_save(self, arg: str) -> None:
        """Save session state to a file:  save [<path>]"""
        path_str = arg.strip() or str(self._output_dir / "session-state.json")
        path = Path(path_str)
        self._tracker.save_state(path)
        print(f"Saved -> {path}")

    def do_override(self, arg: str) -> None:
        """Force-submit an unresolved event by committing directly:  override <event_id>"""
        event_id = arg.strip()
        if not event_id:
            print("Usage: override <event_id>")
            return
        # Use ManualOverrides to build a forced commit of a custom event.
        from scenario.ktsl.models import ManualOverrides

        # Emit a synthetic action that becomes a manual commit
        result = self._tracker.submit_action(
            action_text=f"forced override: {event_id}",
            actor="__kp__",
            scene_id="manual_override",
            manual_overrides=ManualOverrides(
                required_info_ids=[],
                output_info_ids=[],
            ),
        )
        print(f"[override] commit_index={result.event_record.commit_index}")

    def do_quit(self, arg: str) -> bool:
        """Exit REPL and generate MD + HTML reports."""
        self._ended_at = _now_iso()
        self._generate_reports()
        print(f"Reports written to {self._output_dir}")
        return True  # exits cmd.Cmd.cmdloop()

    # Alias: do_exit == do_quit
    do_exit = do_quit

    def do_EOF(self, arg: str) -> bool:
        """Ctrl-D triggers the same path as quit."""
        print()
        return self.do_quit(arg)

    # ---- internal ----

    def _generate_reports(self) -> None:
        """Build SessionReport from tracker state and write md + html."""
        summary = self._tracker.get_session_summary()
        started_at = summary.started_at or _now_iso()
        ended_at = self._ended_at

        # Violation timeline
        violations_timeline: list[ViolationEvent] = []
        for i, ve in enumerate(self._tracker._state.violations, start=1):
            violations_timeline.append(
                ViolationEvent(
                    event_id=ve.id,
                    event_index=i,
                    actor=ve.character_id or "__kp__",
                    action_text="audit-violation",
                    scene_id=ve.scene_id or "manual",
                    severity=ve.severity,
                    metric=ve.metric,
                    message=ve.message,
                    overridden=False,
                )
            )

        # Final knowledge map
        knowledge_map: dict[str, list[KnowledgeItemView]] = {}
        for cid, actor_state in self._tracker._state.knowledge_state.items():
            items: list[KnowledgeItemView] = []
            for item in actor_state.acquired:
                items.append(
                    KnowledgeItemView(
                        info_id=item.info_id,
                        kind=item.kind,
                        sensitivity=item.sensitivity,
                        content_summary=item.content_summary,
                        source_event_id=item.source_event_id,
                        source_scene_id=item.source_scene_id,
                        acquired_at_minute=item.acquired_at_minute,
                        leaked=item.sensitivity not in {"public", "low"},
                    )
                )
            knowledge_map[cid] = items

        # Scene timelines
        scene_timelines: dict[str, list[EventSummary]] = {}
        for event in self._tracker._state.event_log:
            summary_entry = EventSummary(
                event_id=event.id,
                event_index=event.commit_index or 0,
                actor=event.actor,
                action_text=event.action_text,
                time_minute=event.time_end_minute,
                output_info_ids=list(event.output_info_ids),
                status=event.status,
            )
            scene_timelines.setdefault(event.scene_id, []).append(summary_entry)

        # Barrier states
        barrier_views = [
            BarrierStateView(
                barrier_id=b.barrier_id,
                status=b.status,
                required_event_ids=b.required_event_ids,
                satisfied_event_ids=b.satisfied_event_ids,
                required_info_ids=b.required_info_ids,
                satisfied_info_ids=b.satisfied_info_ids,
            )
            for b in self._tracker.get_barrier_states()
        ]
        coupling_views = [
            CouplingStateView(
                coupling_id=c.coupling_id,
                source_scene_id=c.source_scene_id,
                target_scene_id=c.target_scene_id,
                mode=c.mode,
                drift_minutes=c.drift_minutes,
                active=c.active,
            )
            for c in self._tracker.get_coupling_states()
        ]

        report = SessionReport(
            fixture_id=summary.fixture_id,
            fixture_title=summary.fixture_title,
            started_at=started_at,
            ended_at=ended_at,
            session_config=_to_report_session_config(self._tracker._state.config),
            total_events=summary.total_events,
            total_committed=summary.total_committed,
            total_blocked=0,
            total_overridden=summary.total_overridden,
            metrics=self._tracker.get_current_metrics(),
            violation_timeline=violations_timeline,
            final_knowledge_map=knowledge_map,
            scene_timelines=scene_timelines,
            barrier_final_states=barrier_views,
            coupling_final_states=coupling_views,
        )

        md = MarkdownRenderer().render_session(report)
        html = HTMLRenderer().render_session(report)
        _save_report(md, self._output_dir, "session-report.md")
        _save_report(html, self._output_dir, "session-report.html")


def _parse_action_line(arg: str) -> tuple[Optional[str], Optional[str], str]:
    """Parse ``<actor> "<action>" [@<scene_id>]`` → (actor, text, scene_id)."""
    arg = arg.strip()
    if not arg:
        return None, None, ""

    # Read actor (first token)
    parts = arg.split(None, 1)
    if len(parts) < 2:
        return None, None, ""
    actor = parts[0]
    rest = parts[1].strip()

    scene_id = ""
    # Extract optional @scene_id suffix
    scene_split = rest.rsplit("@", 1)
    if len(scene_split) == 2:
        action_text_part = scene_split[0].strip()
        scene_id = scene_split[1].strip()
    else:
        action_text_part = rest

    # Strip quotes from action text
    if (
        len(action_text_part) >= 2
        and action_text_part[0] == '"'
        and action_text_part[-1] == '"'
    ):
        action_text = action_text_part[1:-1]
    else:
        action_text = action_text_part

    # Default scene: pick the scene that lists this character
    if not scene_id:
        fixture = getattr(_parse_action_line, "_last_fixture", None)
        if fixture is not None:
            for scene in fixture.scenes:
                if actor in scene.participant_character_ids:
                    scene_id = scene.id
                    break
            if not scene_id and fixture.scenes:
                scene_id = fixture.scenes[0].id

    return actor, action_text, scene_id


def cmd_session(args: argparse.Namespace) -> int:
    """Run ``ktsl session <fixture_id_or_path>``."""
    fixture = _load_fixture(args.fixture_id_or_path)
    _parse_action_line._last_fixture = fixture  # type: ignore[attr-defined]
    output_dir = Path(args.output_dir)
    repl = KTSLRepl(fixture=fixture, output_dir=output_dir)
    try:
        repl.cmdloop()
    except KeyboardInterrupt:
        print("\nInterrupted.")
    return 0


# ---------------------------------------------------------------------------
# publish: publish-gate evaluation
# ---------------------------------------------------------------------------


def cmd_publish(args: argparse.Namespace) -> int:
    """Run ``ktsl publish <fixture_id_or_path> [--criteria ...] [--format md|html]``."""
    fixture = _load_fixture(args.fixture_id_or_path)
    gate = PublishGate(fixture)
    if args.criteria:
        criteria = PublishGate.load_criteria(Path(args.criteria))
    else:
        criteria = PublishGate.default_criteria(fixture.id)
    result = gate.evaluate(criteria)

    content = _render_publish_report(
        gate_result=result,
        fixture=fixture,
        criteria=criteria,
        output_format=args.format,
    )
    print(content)

    output_dir = Path(args.output_dir)
    ext = "html" if args.format == "html" else "md"
    out = _save_report(content, output_dir, f"publish-report.{ext}")
    print(f"\n[Saved] {out}")
    return 0 if result.overall_pass else 1


# ---------------------------------------------------------------------------
# replay: regenerate report from saved state
# ---------------------------------------------------------------------------


def cmd_replay(args: argparse.Namespace) -> int:
    """Run ``ktsl replay <state.json> [--format md|html]``."""
    state_path = Path(args.state_path)
    if not state_path.exists():
        print(f"[ERROR] State file not found: {state_path}", file=sys.stderr)
        return 2

    from scenario.ktsl.fixtures import list_ktsl_fixtures

    # Peek fixture_id
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    fixture_id = payload.get("fixture_id", "")

    # Find fixture object for title
    fixture: Optional[KTSLFixture] = None
    for f in list_ktsl_fixtures():
        if f.id == fixture_id:
            fixture = f
            break
    if fixture is None:
        # Build a minimum stub fixture just so renderers work
        fixture = get_ktsl_fixture(KTSL_FIXTURE_IDS[0])

    tracker = SessionAuditTracker(fixture)
    tracker.load_state(state_path)

    ended_at = _now_iso()
    summary = tracker.get_session_summary()

    violations_timeline: list[ViolationEvent] = []
    for i, ve in enumerate(tracker._state.violations, start=1):
        violations_timeline.append(
            ViolationEvent(
                event_id=ve.id,
                event_index=i,
                actor=ve.character_id or "__kp__",
                action_text="audit-violation",
                scene_id=ve.scene_id or "manual",
                severity=ve.severity,
                metric=ve.metric,
                message=ve.message,
                overridden=False,
            )
        )

    knowledge_map: dict[str, list[KnowledgeItemView]] = {}
    for cid, actor_state in tracker._state.knowledge_state.items():
        items = [
            KnowledgeItemView(
                info_id=item.info_id,
                kind=item.kind,
                sensitivity=item.sensitivity,
                content_summary=item.content_summary,
                source_event_id=item.source_event_id,
                source_scene_id=item.source_scene_id,
                acquired_at_minute=item.acquired_at_minute,
                leaked=item.sensitivity not in {"public", "low"},
            )
            for item in actor_state.acquired
        ]
        knowledge_map[cid] = items

    scene_timelines: dict[str, list[EventSummary]] = {}
    for event in tracker._state.event_log:
        entry = EventSummary(
            event_id=event.id,
            event_index=event.commit_index or 0,
            actor=event.actor,
            action_text=event.action_text,
            time_minute=event.time_end_minute,
            output_info_ids=list(event.output_info_ids),
            status=event.status,
        )
        scene_timelines.setdefault(event.scene_id, []).append(entry)

    barrier_views = [
        BarrierStateView(
            barrier_id=b.barrier_id,
            status=b.status,
            required_event_ids=b.required_event_ids,
            satisfied_event_ids=b.satisfied_event_ids,
            required_info_ids=b.required_info_ids,
            satisfied_info_ids=b.satisfied_info_ids,
        )
        for b in tracker.get_barrier_states()
    ]
    coupling_views = [
        CouplingStateView(
            coupling_id=c.coupling_id,
            source_scene_id=c.source_scene_id,
            target_scene_id=c.target_scene_id,
            mode=c.mode,
            drift_minutes=c.drift_minutes,
            active=c.active,
        )
        for c in tracker.get_coupling_states()
    ]

    report = SessionReport(
        fixture_id=summary.fixture_id,
        fixture_title=summary.fixture_title,
        started_at=summary.started_at,
        ended_at=ended_at,
        session_config=_to_report_session_config(tracker._state.config),
        total_events=summary.total_events,
        total_committed=summary.total_committed,
        total_blocked=0,
        total_overridden=summary.total_overridden,
        metrics=tracker.get_current_metrics(),
        violation_timeline=violations_timeline,
        final_knowledge_map=knowledge_map,
        scene_timelines=scene_timelines,
        barrier_final_states=barrier_views,
        coupling_final_states=coupling_views,
    )

    if args.format == "html":
        content = HTMLRenderer().render_session(report)
    else:
        content = MarkdownRenderer().render_session(report)

    print(content[:1000] + ("..." if len(content) > 1000 else ""))

    output_dir = Path(args.output_dir)
    ext = "html" if args.format == "html" else "md"
    out = _save_report(content, output_dir, f"session-report.{ext}")
    print(f"\n[Saved] {out}")
    return 0


# ---------------------------------------------------------------------------
# analyst: render KTSL decision audit from log dir
# ---------------------------------------------------------------------------


def cmd_analyst(args: argparse.Namespace) -> int:
    """Render KTSL decision audit for a session."""
    from scenario.report.analyst_renderer import AnalystRenderer

    base = Path(args.log_base)
    renderer = AnalystRenderer(log_base=base)

    if args.focus:
        output = renderer.render_focus(
            args.session_id, args.focus, turn=args.turn
        )
    else:
        output = renderer.render_table(
            args.session_id, turn=args.turn
        )

    if args.export:
        import zipfile

        session_dir = base / "session" / args.session_id / "ktsl"
        export_path = Path(args.export)
        if not session_dir.exists():
            print(f"[ERROR] No KTSL logs at {session_dir}", file=sys.stderr)
            return 2
        with zipfile.ZipFile(export_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in session_dir.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(base))
        print(f"[exported to {export_path}]")
        return 0

    print(output)
    return 0


# ---------------------------------------------------------------------------
# Public API wrappers (used by subprocess tests and `if __name__ == '__main__'`)
# ---------------------------------------------------------------------------


def validate_fixture(fixture_id_or_path: str) -> int:
    """Load and validate *fixture_id_or_path*; return exit code (0/1/2)."""
    fixture = _load_fixture(fixture_id_or_path)
    report = _run_validate(fixture)
    print(MarkdownRenderer().render_validate(report))
    return _exit_code_from_issues(report)


def audit_action(
    fixture_id_or_path: str,
    action: str,
    actor: str,
    scene: str,
) -> Any:
    return _audit_action(fixture_id_or_path, action, actor, scene)


def session_repl(
    fixture_id_or_path: str,
    output_dir: str = "./ktsl-output",
) -> None:
    fixture = _load_fixture(fixture_id_or_path)
    _parse_action_line._last_fixture = fixture  # type: ignore[attr-defined]
    repl = KTSLRepl(fixture=fixture, output_dir=Path(output_dir))
    repl.cmdloop()


def publish_fixture(
    fixture_id_or_path: str,
    criteria: str | None = None,
    output_format: str = "md",
    output_dir: str = "./ktsl-output",
) -> None:
    fixture = _load_fixture(fixture_id_or_path)
    gate = PublishGate(fixture)
    crit = PublishGate.load_criteria(Path(criteria)) if criteria else PublishGate.default_criteria(fixture.id)
    result = gate.evaluate(crit)
    print(
        _render_publish_report(gate_result=result, fixture=fixture, criteria=crit, output_format=output_format)
    )


def replay_session(
    state_path: str,
    output_format: str = "md",
    output_dir: str = "./ktsl-output",
) -> None:
    args = argparse.Namespace(
        state_path=state_path,
        format=output_format,
        output_dir=output_dir,
    )
    cmd_replay(args)


# ---------------------------------------------------------------------------
# entrypoint: argparse wiring
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ktsl",
        description="KTSL KP Toolchain — fixture validation, auditing, session, and publishing.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- validate ---
    p_validate = sub.add_parser("validate", help="Run structural checks on a fixture.")
    p_validate.add_argument("fixture_id_or_path", help="Builtin fixture id or YAML path.")
    p_validate.add_argument(
        "--output-dir",
        "-O",
        default=None,
        help="Optional output directory for markdown report.",
    )
    p_validate.set_defaults(func=cmd_validate)

    # --- audit ---
    p_audit = sub.add_parser("audit", help="Run a single-action audit.")
    p_audit.add_argument("fixture_id_or_path", help="Builtin fixture id or YAML path.")
    p_audit.add_argument("--action", required=True, help="Action text to audit.")
    p_audit.add_argument("--actor", required=True, help="Actor name/character id.")
    p_audit.add_argument("--scene", required=True, help="Scene id for the action.")
    p_audit.add_argument("--output-dir", "-O", default=None)
    p_audit.set_defaults(func=cmd_audit)

    # --- session ---
    p_session = sub.add_parser("session", help="Interactive session REPL.")
    p_session.add_argument("fixture_id_or_path", help="Builtin fixture id or YAML path.")
    p_session.add_argument(
        "--output-dir",
        "-O",
        default="./ktsl-output",
        help="Directory for generated reports (default: ./ktsl-output).",
    )
    p_session.set_defaults(func=cmd_session)

    # --- publish ---
    p_publish = sub.add_parser("publish", help="Evaluate fixture against publish criteria.")
    p_publish.add_argument("fixture_id_or_path", help="Builtin fixture id or YAML path.")
    p_publish.add_argument("--criteria", default=None, help="YAML path for criteria.")
    p_publish.add_argument(
        "--format",
        default="md",
        choices=["md", "html"],
        help="Output format.",
    )
    p_publish.add_argument("--output-dir", "-O", default="./ktsl-output")
    p_publish.set_defaults(func=cmd_publish)

    # --- replay ---
    p_replay = sub.add_parser("replay", help="Regenerate session report from saved state.")
    p_replay.add_argument("state_path", help="Path to session-state.json.")
    p_replay.add_argument("--format", default="md", choices=["md", "html"])
    p_replay.add_argument("--output-dir", "-O", default="./ktsl-output")
    p_replay.set_defaults(func=cmd_replay)

    # --- analyst ---
    p_analyst = sub.add_parser(
        "analyst",
        help="Render KTSL decision audit from log/session/<session_id>/ktsl/.",
    )
    p_analyst.add_argument("session_id", help="Session ID to audit.")
    p_analyst.add_argument(
        "--log-base",
        default=".",
        help="Base log directory (default: '.').",
    )
    p_analyst.add_argument(
        "--turn",
        type=int,
        default=None,
        help="Focus on a single turn (default: all turns).",
    )
    p_analyst.add_argument(
        "--focus",
        choices=["causal", "knowledge", "interventions", "wait", "modes", "metrics"],
        default=None,
        help="Focus a specific audit perspective.",
    )
    p_analyst.add_argument(
        "--export",
        default=None,
        help="Export the audit bundle as a ZIP archive.",
    )
    p_analyst.set_defaults(func=cmd_analyst)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse argv and dispatch to the selected subcommand handler."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
