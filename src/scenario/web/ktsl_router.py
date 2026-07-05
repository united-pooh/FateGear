"""aiohttp REST API handlers for the KTSL KP toolchain.

This module exposes the KTSL endpoints described in the toolchain design
document (§7 / §8) as plain aiohttp request handlers.  It is intentionally
self-contained — it does **not** modify ``main.py`` or ``api.py``; instead it
exports :func:`register_ktsl_routes` which an external caller can use to mount
the KTSL endpoints onto any ``web.Application`` instance.

The router keeps an in-memory store of active sessions keyed by a
``session_id`` (a short hex string from :func:`uuid.uuid4`).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from aiohttp import web

from scenario.auth import (
    AuthError,
    Principal,
    auth_error_payload,
    authorize_keeper_view,
    authorize_player_view,
    parse_authorization_header,
)
from scenario.ktsl.fixtures import get_ktsl_fixture
from scenario.ktsl.models import (
    EventRecord,
    KTSLFixture,
    ManualOverrides,
    PublishCriteria,
    SessionConfig as KtslSessionConfig,
    Visibility,
)
from scenario.publish_gate import PublishGate
from scenario.report.markdown_renderer import MarkdownRenderer
from scenario.report.session_reports import (
    BarrierStateView,
    CouplingStateView,
    EventSummary,
    KnowledgeItemView,
    SessionConfig as ReportSessionConfig,
    SessionReport,
    ValidateIssue,
    ValidateReport,
    ViolationEvent,
)
from scenario.session_audit_tracker import SessionAuditTracker

# ---------------------------------------------------------------------------
# In-memory session store (keyed by session_id hex string)
# ---------------------------------------------------------------------------

_SESSION_STORE: dict[str, SessionAuditTracker] = {}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _read_json_body(request: web.Request) -> dict[str, Any]:
    """Read and validate that the request body is a JSON object."""
    if not request.can_read_body:
        return {}
    payload = await request.json()
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("请求体必须是 JSON 对象")
    return payload


def _authorization_principal(request: web.Request) -> Principal:
    headers = getattr(request, "headers", {})
    authorization = headers.get("Authorization") if headers is not None else None
    principal = parse_authorization_header(authorization, required=True)
    if principal is None:
        raise AssertionError("required auth parsing must return a principal")
    return principal


def _auth_error_response(error: AuthError) -> web.Response:
    return web.json_response(auth_error_payload(error), status=error.status_code)


def _authorize_keeper_request(request: web.Request, *, session_id: str) -> Principal:
    principal = _authorization_principal(request)
    authorize_keeper_view(principal, session_id=session_id)
    return principal


def _authorize_knowledge_request(
    request: web.Request,
    *,
    session_id: str,
    character_id: str | None,
) -> Principal:
    principal = _authorization_principal(request)
    if character_id:
        authorize_player_view(
            principal,
            session_id=session_id,
            target_player_id=character_id,
        )
    else:
        authorize_keeper_view(principal, session_id=session_id)
    return principal


def _get_tracker_or_404(request: web.Request) -> SessionAuditTracker | None:
    """Return the tracker for *session_id* or write a 404 response and return None."""
    session_id = request.match_info.get("session_id", "")
    tracker = _SESSION_STORE.get(session_id)
    if tracker is None:
        return None
    return tracker


def _build_validate_report(fixture: KTSLFixture) -> ValidateReport:
    """Run structural validation on a fixture and return a ``ValidateReport``."""
    errors: list[ValidateIssue] = []
    warnings: list[ValidateIssue] = []

    # Gather IDs for cross-reference validation
    location_ids = {loc.id for loc in fixture.locations}
    scene_ids = {sc.id for sc in fixture.scenes}
    info_ids = {info.id for info in fixture.info_labels}
    clue_ids = {clue.id for clue in fixture.clues}
    event_ids = {ev.id for ev in fixture.events}
    barrier_ids = {b.id for b in fixture.barriers}

    # SceneCard.location_id must exist
    for sc in fixture.scenes:
        if sc.location_id and sc.location_id not in location_ids:
            errors.append(
                ValidateIssue(
                    level="error",
                    code="missing_location",
                    message=f"Scene '{sc.id}' references unknown location_id '{sc.location_id}'.",
                    resource_id=sc.id,
                )
            )

    # SceneCard.barrier_id must exist
    for sc in fixture.scenes:
        if sc.barrier_id and sc.barrier_id not in barrier_ids:
            errors.append(
                ValidateIssue(
                    level="error",
                    code="missing_barrier",
                    message=f"Scene '{sc.id}' references unknown barrier_id '{sc.barrier_id}'.",
                    resource_id=sc.id,
                )
            )

    # SceneCard.clue_ids must exist
    for sc in fixture.scenes:
        for cid in sc.clue_ids:
            if cid not in clue_ids:
                errors.append(
                    ValidateIssue(
                        level="error",
                        code="missing_clue",
                        message=f"Scene '{sc.id}' references unknown clue_id '{cid}'.",
                        resource_id=sc.id,
                    )
                )

    # SceneCard.info_ids must exist
    for sc in fixture.scenes:
        for iid in sc.info_ids:
            if iid not in info_ids:
                errors.append(
                    ValidateIssue(
                        level="error",
                        code="missing_info",
                        message=f"Scene '{sc.id}' references unknown info_id '{iid}'.",
                        resource_id=sc.id,
                    )
                )

    # ClueRecord.info_id must exist
    for clue in fixture.clues:
        if clue.info_id not in info_ids:
            errors.append(
                ValidateIssue(
                    level="error",
                    code="clue_missing_info",
                    message=f"Clue '{clue.id}' references unknown info_id '{clue.info_id}'.",
                    resource_id=clue.id,
                )
            )

    # EventRecord.barrier_id must exist when set
    for ev in fixture.events:
        if ev.barrier_id and ev.barrier_id not in barrier_ids:
            errors.append(
                ValidateIssue(
                    level="error",
                    code="event_missing_barrier",
                    message=f"Event '{ev.id}' references unknown barrier_id '{ev.barrier_id}'.",
                    resource_id=ev.id,
                )
            )

    # BarrierCheckpoint.required_event_ids must exist
    for barrier in fixture.barriers:
        for eid in barrier.required_event_ids:
            if eid not in event_ids:
                warnings.append(
                    ValidateIssue(
                        level="warning",
                        code="barrier_missing_event",
                        message=f"Barrier '{barrier.id}' requires unknown event_id '{eid}'.",
                        resource_id=barrier.id,
                    )
                )

    # BarrierCheckpoint.scene_ids must exist
    for barrier in fixture.barriers:
        for sid in barrier.scene_ids:
            if sid not in scene_ids:
                warnings.append(
                    ValidateIssue(
                        level="warning",
                        code="barrier_missing_scene",
                        message=f"Barrier '{barrier.id}' references unknown scene_id '{sid}'.",
                        resource_id=barrier.id,
                    )
                )

    # SceneCoupling.source/target scene must exist
    for coupling in fixture.couplings:
        if coupling.source_scene_id not in scene_ids:
            errors.append(
                ValidateIssue(
                    level="error",
                    code="coupling_missing_scene",
                    message=f"Coupling '{coupling.id}' references unknown source_scene_id '{coupling.source_scene_id}'.",
                    resource_id=coupling.id,
                )
            )
        if coupling.target_scene_id not in scene_ids:
            errors.append(
                ValidateIssue(
                    level="error",
                    code="coupling_missing_scene",
                    message=f"Coupling '{coupling.id}' references unknown target_scene_id '{coupling.target_scene_id}'.",
                    resource_id=coupling.id,
                )
            )

    # SceneCoupling.input_event_ids must exist
    for coupling in fixture.couplings:
        for eid in coupling.input_event_ids:
            if eid not in event_ids:
                warnings.append(
                    ValidateIssue(
                        level="warning",
                        code="coupling_missing_event",
                        message=f"Coupling '{coupling.id}' references unknown input_event_id '{eid}'.",
                        resource_id=coupling.id,
                    )
                )

    # Detect isolated info (not referenced by any event or clue)
    referenced_info: set[str] = set()
    for ev in fixture.events:
        referenced_info.update(ev.required_info_ids)
        referenced_info.update(ev.output_info_ids)
        referenced_info.update(ev.observed_info_ids)
        referenced_info.update(ev.known_info_ids)
    for clue in fixture.clues:
        referenced_info.add(clue.info_id)
        referenced_info.update(clue.required_info_ids)
        referenced_info.update(clue.output_info_ids)
    for barrier in fixture.barriers:
        referenced_info.update(barrier.required_info_ids)

    for info in fixture.info_labels:
        if info.id not in referenced_info:
            warnings.append(
                ValidateIssue(
                    level="warning",
                    code="orphan_info",
                    message=f"Info '{info.id}' is not referenced by any event, clue, or barrier.",
                    resource_id=info.id,
                )
            )

    is_valid = not errors
    return ValidateReport(
        fixture_id=fixture.id,
        fixture_title=fixture.title,
        validated_at=_now_iso(),
        is_valid=is_valid,
        issues=errors + warnings,
    )


class FixtureLoadError(ValueError):
    """Raised when a fixture cannot be loaded from the request payload."""

    def __init__(self, message: str, fixture_id: str = "") -> None:
        super().__init__(message)
        self.fixture_id = fixture_id


def _load_fixture(payload: dict[str, Any]) -> KTSLFixture:
    """Load a KTSLFixture from either ``fixture_id`` or ``fixture_yaml``.

    Raises :class:`FixtureLoadError` on failure so handlers can translate it
    into an appropriate HTTP response.
    """
    fixture_id = payload.get("fixture_id")
    fixture_yaml = payload.get("fixture_yaml")

    if fixture_id:
        try:
            return get_ktsl_fixture(str(fixture_id))
        except KeyError:
            raise FixtureLoadError(
                f"Unknown fixture: {fixture_id}",
                fixture_id=str(fixture_id),
            )
    elif fixture_yaml is not None:
        data = json.loads(str(fixture_yaml))
        return KTSLFixture.model_validate(data)
    else:
        raise FixtureLoadError("missing fixture_id or fixture_yaml in request body")


def _build_session_report(tracker: SessionAuditTracker) -> SessionReport:
    """Compose a fully-populated ``SessionReport`` from the tracker's current state."""
    summary = tracker.get_session_summary()
    metrics = tracker.get_current_metrics()
    barriers = tracker.get_barrier_states()
    couplings = tracker.get_coupling_states()

    # Violation timeline
    violation_timeline: list[ViolationEvent] = []
    for v in tracker._state.violations:
        # Find the matching event to get index / action_text
        matching_event: EventRecord | None = None
        for ev in tracker._state.event_log:
            if ev.id == v.event_id:
                matching_event = ev
                break
        idx = matching_event.commit_index if matching_event and matching_event.commit_index is not None else 0
        action = matching_event.action_text if matching_event else ""
        actor_name = matching_event.actor if matching_event else (v.character_id or "")
        violation_timeline.append(
            ViolationEvent(
                event_id=v.event_id,
                event_index=idx or 0,
                actor=actor_name,
                action_text=action,
                scene_id=v.scene_id,
                severity=v.severity,
                metric=v.metric,
                message=v.message,
            )
        )

    # Final knowledge map
    knowledge_map: dict[str, list[KnowledgeItemView]] = {}
    for char_id, actor_state in tracker._state.knowledge_state.items():
        views: list[KnowledgeItemView] = []
        for item in actor_state.acquired:
            views.append(
                KnowledgeItemView(
                    info_id=item.info_id,
                    kind=item.kind,
                    sensitivity=item.sensitivity,
                    content_summary=item.content_summary,
                    source_event_id=item.source_event_id,
                    source_scene_id=item.source_scene_id,
                    acquired_at_minute=item.acquired_at_minute,
                )
            )
        if views:
            knowledge_map[char_id] = views

    # Scene timelines
    scene_timelines: dict[str, list[EventSummary]] = {}
    for ev in tracker._state.event_log:
        scene_timelines.setdefault(ev.scene_id, []).append(
            EventSummary(
                event_id=ev.id,
                event_index=ev.commit_index or 0,
                actor=ev.actor,
                action_text=ev.action_text,
                time_minute=ev.time_start_minute,
                output_info_ids=list(ev.output_info_ids),
                status=ev.status,
            )
        )

    barrier_views = [
        BarrierStateView(
            barrier_id=b.barrier_id,
            status=b.status,
            required_event_ids=b.required_event_ids,
            satisfied_event_ids=b.satisfied_event_ids,
            required_info_ids=b.required_info_ids,
            satisfied_info_ids=b.satisfied_info_ids,
        )
        for b in barriers
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
        for c in couplings
    ]

    # Convert the ktsl SessionConfig to the report-package SessionConfig
    ktsl_cfg = tracker._state.config
    report_cfg = ReportSessionConfig(
        session_id=ktsl_cfg.session_id,
        fixture_id=ktsl_cfg.fixture_id,
        started_at=ktsl_cfg.started_at,
        kp_name=ktsl_cfg.kp_name,
        default_visibility=ktsl_cfg.default_visibility,
        allow_override=ktsl_cfg.allow_override,
        notes=ktsl_cfg.notes,
    )

    return SessionReport(
        fixture_id=summary.fixture_id,
        fixture_title=summary.fixture_title,
        started_at=summary.started_at,
        ended_at=_now_iso(),
        session_config=report_cfg,
        total_events=summary.total_events,
        total_committed=summary.total_committed,
        total_blocked=0,
        total_overridden=summary.total_overridden,
        metrics=metrics,
        violation_timeline=violation_timeline,
        final_knowledge_map=knowledge_map,
        scene_timelines=scene_timelines,
        barrier_final_states=barrier_views,
        coupling_final_states=coupling_views,
    )


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_validate(request: web.Request) -> web.Response:
    """POST /ktsl/validate — structural validation of a fixture.

    Body: ``{"fixture_id": "..."}`` or ``{"fixture_yaml": "..."}``
    """
    payload = await _read_json_body(request)

    try:
        fixture = _load_fixture(payload)
    except FixtureLoadError as exc:
        return web.json_response(
            {
                "error": "unknown fixture",
                "fixture_id": exc.fixture_id,
            },
            status=400,
        )
    except Exception as exc:
        return web.json_response(
            {"error": f"fixture load failed: {exc}"},
            status=400,
        )

    report = _build_validate_report(fixture)
    errors = [i for i in report.issues if i.level == "error"]
    warnings = [i for i in report.issues if i.level == "warning"]

    return web.json_response(
        {
            "valid": report.is_valid,
            "issues": [i.model_dump() for i in report.issues],
            "error_count": len(errors),
            "warning_count": len(warnings),
        }
    )


async def handle_create_session(request: web.Request) -> web.Response:
    """POST /ktsl/session — create a new audit session.

    Body: ``{"fixture_id": "..., "config": {...}}``
    """
    payload = await _read_json_body(request)

    try:
        fixture = _load_fixture(payload)
    except FixtureLoadError as exc:
        return web.json_response(
            {
                "error": "unknown fixture",
                "fixture_id": exc.fixture_id,
            },
            status=400,
        )

    config_data = payload.get("config") or {}
    config = KtslSessionConfig(
        session_id=str(uuid4().hex),
        fixture_id=fixture.id,
        started_at=_now_iso(),
        **{k: v for k, v in config_data.items() if k in KtslSessionConfig.model_fields},
    )

    tracker = SessionAuditTracker(fixture, config=config)
    _SESSION_STORE[config.session_id] = tracker

    return web.json_response(
        {
            "session_id": config.session_id,
            "fixture_id": fixture.id,
            "fixture_title": fixture.title,
        },
        status=201,
    )


async def handle_submit_event(request: web.Request) -> web.Response:
    """POST /ktsl/{session_id}/events — submit an action and audit it.

    Body: ``{"action": "...", "actor": "...", "scene_id": "...", "visibility": "...", "manual_overrides": {...}}``
    """
    session_id = request.match_info["session_id"]
    tracker = _SESSION_STORE.get(session_id)
    if tracker is None:
        return web.json_response(
            {"error": "session not found", "session_id": session_id},
            status=404,
        )

    payload = await _read_json_body(request)

    action_text = payload.get("action") or payload.get("action_text") or ""
    actor = payload.get("actor") or ""
    scene_id = payload.get("scene_id") or ""
    visibility_raw = payload.get("visibility")
    visibility: Visibility | None = None
    if visibility_raw is not None:
        visibility = visibility_raw  # type: ignore[assignment]

    manual_raw = payload.get("manual_overrides")
    overrides: ManualOverrides | None = None
    if manual_raw is not None and isinstance(manual_raw, dict):
        overrides = ManualOverrides.model_validate(manual_raw)

    result = tracker.submit_action(
        action_text=str(action_text),
        actor=str(actor),
        scene_id=str(scene_id),
        visibility=visibility,
        manual_overrides=overrides,
    )

    return web.json_response(result.model_dump(mode="json"))


async def handle_get_state(request: web.Request) -> web.Response:
    """GET /ktsl/{session_id}/state"""
    session_id = request.match_info.get("session_id", "")
    try:
        _authorize_keeper_request(request, session_id=session_id)
    except AuthError as exc:
        return _auth_error_response(exc)

    tracker = _get_tracker_or_404(request)
    if tracker is None:
        return web.json_response(
            {"error": "session not found", "session_id": session_id},
            status=404,
        )

    metrics = tracker.get_current_metrics()
    barriers = tracker.get_barrier_states()
    couplings = tracker.get_coupling_states()

    return web.json_response(
        {
            "metrics": metrics.model_dump(),
            "barriers": [b.model_dump() for b in barriers],
            "couplings": [c.model_dump() for c in couplings],
            "event_count": len(tracker._state.event_log),
        }
    )


async def handle_get_timeline(request: web.Request) -> web.Response:
    """GET /ktsl/{session_id}/timeline?scene_id=xxx"""
    session_id = request.match_info.get("session_id", "")
    try:
        _authorize_keeper_request(request, session_id=session_id)
    except AuthError as exc:
        return _auth_error_response(exc)

    tracker = _get_tracker_or_404(request)
    if tracker is None:
        return web.json_response(
            {"error": "session not found", "session_id": session_id},
            status=404,
        )

    scene_id = request.query.get("scene_id")
    if scene_id:
        events = tracker.get_scene_timeline(scene_id)
    else:
        events = list(tracker._state.event_log)

    scenes: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        scenes.setdefault(ev.scene_id, []).append(
            {
                "event_id": ev.id,
                "actor": ev.actor,
                "action_text": ev.action_text,
                "scene_id": ev.scene_id,
                "status": ev.status,
                "output_info_ids": ev.output_info_ids,
                "depends_on_event_ids": ev.depends_on_event_ids,
                "required_info_ids": ev.required_info_ids,
                "time_start_minute": ev.time_start_minute,
                "time_end_minute": ev.time_end_minute,
            }
        )

    return web.json_response({"scenes": scenes})


async def handle_get_report(request: web.Request) -> web.Response:
    """GET /ktsl/{session_id}/report?format=md|html"""
    session_id = request.match_info.get("session_id", "")
    try:
        _authorize_keeper_request(request, session_id=session_id)
    except AuthError as exc:
        return _auth_error_response(exc)

    tracker = _get_tracker_or_404(request)
    if tracker is None:
        return web.json_response(
            {"error": "session not found", "session_id": session_id},
            status=404,
        )

    fmt = request.query.get("format", "md")
    report = _build_session_report(tracker)

    if fmt == "html":
        try:
            from scenario.report.html_renderer import HTMLRenderer
            renderer = HTMLRenderer()
            content = renderer.render_session(report)
        except ImportError:
            # jinja2 may not be installed; fall back to markdown
            content = MarkdownRenderer.render_session(report)
            fmt = "md"
    else:
        content = MarkdownRenderer.render_session(report)

    return web.json_response(
        {
            "format": fmt,
            "content": content,
            "fixture_id": report.fixture_id,
            "generated_at": _now_iso(),
        }
    )


async def handle_get_knowledge(request: web.Request) -> web.Response:
    """GET /ktsl/{session_id}/knowledge?character_id=xxx"""
    session_id = request.match_info.get("session_id", "")
    character_id = request.query.get("character_id")
    try:
        _authorize_knowledge_request(
            request,
            session_id=session_id,
            character_id=character_id,
        )
    except AuthError as exc:
        return _auth_error_response(exc)

    tracker = _get_tracker_or_404(request)
    if tracker is None:
        return web.json_response(
            {"error": "session not found", "session_id": session_id},
            status=404,
        )

    knowledge_map: dict[str, list[dict[str, Any]]] = {}

    if character_id:
        items = tracker.get_knowledge_summary(character_id)
        knowledge_map[character_id] = [item.model_dump() for item in items]
    else:
        for char_id in tracker._state.knowledge_state:
            items = tracker.get_knowledge_summary(char_id)
            if items:
                knowledge_map[char_id] = [item.model_dump() for item in items]

    return web.json_response({"knowledge_map": knowledge_map})


async def handle_destroy_session(request: web.Request) -> web.Response:
    """DELETE /ktsl/{session_id}"""
    session_id = request.match_info["session_id"]
    tracker = _SESSION_STORE.pop(session_id, None)
    if tracker is None:
        return web.json_response(
            {"error": "session not found", "session_id": session_id},
            status=404,
        )
    return web.json_response({"destroyed": True, "session_id": session_id})


async def handle_publish(request: web.Request) -> web.Response:
    """POST /ktsl/publish — evaluate a fixture against publish criteria.

    Body: ``{"fixture_id": "...", "criteria": {...}}``
    """
    payload = await _read_json_body(request)

    try:
        fixture = _load_fixture(payload)
    except FixtureLoadError as exc:
        return web.json_response(
            {
                "error": "unknown fixture",
                "fixture_id": exc.fixture_id,
            },
            status=400,
        )

    gate = PublishGate(fixture)

    criteria_raw = payload.get("criteria")
    if criteria_raw is not None:
        criteria = PublishCriteria.model_validate(criteria_raw)
    elif payload.get("criteria_path"):
        criteria_path = Path(str(payload["criteria_path"]))
        if not criteria_path.exists():
            return web.json_response(
                {"error": f"criteria file not found: {criteria_path}"},
                status=400,
            )
        criteria = PublishGate.load_criteria(criteria_path)
    else:
        criteria = PublishGate.default_criteria(fixture.id)

    result = gate.evaluate(criteria)
    return web.json_response(result.model_dump(mode="json"))


async def handle_replay(request: web.Request) -> web.Response:
    """POST /ktsl/replay — load a session state and produce a report.

    Body: ``{"state_json": "/path/to/session-state.json"}``
    Query: ``?format=md|html``
    """
    payload = await _read_json_body(request)

    state_path_raw = payload.get("state_json") or payload.get("state_path")
    if not state_path_raw:
        return web.json_response(
            {"error": "missing state_json (path to session state file)"},
            status=400,
        )
    state_path = Path(str(state_path_raw))
    if not state_path.exists():
        return web.json_response(
            {"error": f"state file not found: {state_path}"},
            status=400,
        )

    # Load requires a fixture; we read fixture_id from the save payload.
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    fixture_id = raw.get("fixture_id", "")
    try:
        fixture = get_ktsl_fixture(fixture_id)
    except KeyError:
        return web.json_response(
            {"error": "unknown fixture", "fixture_id": fixture_id},
            status=400,
        )

    tracker = SessionAuditTracker(fixture)
    tracker.load_state(state_path)

    fmt = request.query.get("format", "md")
    report = _build_session_report(tracker)

    if fmt == "html":
        try:
            from scenario.report.html_renderer import HTMLRenderer
            renderer = HTMLRenderer()
            content = renderer.render_session(report)
        except ImportError:
            content = MarkdownRenderer.render_session(report)
            fmt = "md"
    else:
        content = MarkdownRenderer.render_session(report)

    return web.json_response(
        {
            "format": fmt,
            "content": content,
            "fixture_id": report.fixture_id,
            "generated_at": _now_iso(),
        }
    )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_ktsl_routes(app: web.Application) -> None:
    """Register all KTSL routes onto an existing aiohttp application.

    This function is the single public entry-point of the module.  It can be
    called from any external bootstrap code (e.g. ``main.py`` or a separate
    ``ktsl_server.py`` entry-point) without modifying the existing
    ``create_app`` function.
    """
    # Ensure the app has our session store (mounted in app dict for namespacing)
    if "ktsl_session_store" not in app:
        app["ktsl_session_store"] = _SESSION_STORE

    app.add_routes(
        [
            web.post("/ktsl/validate", handle_validate),
            web.post("/ktsl/session", handle_create_session),
            web.post("/ktsl/{session_id}/events", handle_submit_event),
            web.get("/ktsl/{session_id}/state", handle_get_state),
            web.get("/ktsl/{session_id}/timeline", handle_get_timeline),
            web.get("/ktsl/{session_id}/report", handle_get_report),
            web.get("/ktsl/{session_id}/knowledge", handle_get_knowledge),
            web.delete("/ktsl/{session_id}", handle_destroy_session),
            web.post("/ktsl/publish", handle_publish),
            web.post("/ktsl/replay", handle_replay),
        ]
    )


# ---------------------------------------------------------------------------
# Standalone app factory (convenience for tests / standalone server)
# ---------------------------------------------------------------------------


def create_ktsl_app() -> web.Application:
    """Return a standalone aiohttp app with only the KTSL routes mounted."""
    app = web.Application()
    register_ktsl_routes(app)
    return app
