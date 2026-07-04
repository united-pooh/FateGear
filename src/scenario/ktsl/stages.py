"""Turn stage implementations used by the KTSL pipeline."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .models import InfoLabel, ModuleKTSLSpec


class SchemaValidationIssue(BaseModel):
    """Single validation problem in a ModuleKTSLSpec."""

    field: str
    message: str
    severity: Literal["error", "warning"] = "error"


class SchemaValidationReport(BaseModel):
    """Result of validating a ModuleKTSLSpec."""

    is_valid: bool
    issues: list[SchemaValidationIssue] = Field(default_factory=list)


class SchemaValidatorStage:
    """Validates a ModuleKTSLSpec for required fields and contradictions.

    Checks performed:
    - Every info_label with sensitivity >= medium must have a non-empty redaction.
    - Every info_label with sensitivity >= high must have a public_payload.
    - Every scene must have at least one participant_character_id.
    """

    def validate(self, spec: ModuleKTSLSpec) -> SchemaValidationReport:
        issues: list[SchemaValidationIssue] = []

        for info in spec.info_labels:
            if info.sensitivity in {"medium", "high", "keeper"} and not info.redaction:
                issues.append(
                    SchemaValidationIssue(
                        field=f"info_labels.{info.info_id}.redaction",
                        message=(
                            f"Sensitive info '{info.info_id}' "
                            f"(sensitivity={info.sensitivity}) requires redaction text."
                        ),
                    )
                )
            if info.sensitivity in {"high", "keeper"} and not info.public_payload:
                issues.append(
                    SchemaValidationIssue(
                        field=f"info_labels.{info.info_id}.public_payload",
                        message=(
                            f"High-sensitivity info '{info.info_id}' "
                            f"needs a public_payload."
                        ),
                    )
                )

        for scene in spec.scenes:
            if not scene.participant_character_ids:
                issues.append(
                    SchemaValidationIssue(
                        field=f"scenes.{scene.scene_id}.participant_character_ids",
                        message=f"Scene '{scene.scene_id}' has no participants.",
                    )
                )

        return SchemaValidationReport(is_valid=not issues, issues=issues)


class SubmitIntervention(BaseModel):
    """A single problem detected during submit-time pre-check."""

    actor: str
    reason_code: str
    reason: str


class SubmitCheckResult(BaseModel):
    """Outcome of the submit-time pre-check."""

    status: Literal["continue", "blocked"]
    interventions: list[SubmitIntervention] = Field(default_factory=list)
    parse_resolution: str = "unresolved"


class SubmitCheckStage:
    """Lightweight submit-time check (single-player; no cross-player info).

    1. Empty action text + strict → block with reason ``empty_action``.
    2. Iterates ``required_info_ids``; if any label in ``ledger_info_labels``
       has sensitivity >= medium AND the actor is not authorized → block.
    3. Iterates ``dependencies``; any event id not in ``committed_event_ids``
       → block.

    Returns a :class:`SubmitCheckResult` with status and interventions.
    When ``session.ktsl_ledger is None`` it should never be called.
    """

    # Sensitivity levels that require explicit authorization.
    _SENSITIVE_LEVELS = {"medium", "high", "keeper"}

    def __init__(
        self,
        *,
        info_labels: dict[str, InfoLabel] | None = None,
        causal_dependencies: list[Any] | None = None,
    ) -> None:
        self._info_labels = info_labels or {}
        self._causal_dependencies = causal_dependencies or []

    def check(
        self,
        *,
        action_text: str,
        actor: str,
        scene_id: str,
        committed_event_ids: set[str],
        ledger_info_labels: dict[str, InfoLabel] | None = None,
        strict: bool = False,
        required_info_ids: list[str] | None = None,
        dependencies: list[str] | None = None,
    ) -> SubmitCheckResult:
        interventions: list[SubmitIntervention] = []
        labels = ledger_info_labels or self._info_labels or {}
        req_info = required_info_ids or []
        deps = dependencies or []

        # 1. Empty-action check in strict mode
        if strict and not action_text.strip():
            return SubmitCheckResult(
                status="blocked",
                interventions=[
                    SubmitIntervention(
                        actor=actor,
                        reason_code="empty_action",
                        reason="Action description is empty.",
                    )
                ],
                parse_resolution="blocked_by_precheck",
            )

        # 2. Per-info-label authorization check
        for info_id in req_info:
            label = labels.get(info_id)
            if label is None:
                continue
            if label.sensitivity in self._SENSITIVE_LEVELS:
                authorized = (
                    actor in label.authorized_character_ids
                    or actor in label.known_by_character_ids
                )
                if not authorized:
                    interventions.append(
                        SubmitIntervention(
                            actor=actor,
                            reason_code="info_unauthorized",
                            reason=(
                                f"Info '{info_id}' (sensitivity={label.sensitivity}) "
                                f"not authorized for '{actor}'."
                            ),
                        )
                    )

        # 3. Causal-pending check (deps must be in committed_event_ids)
        for dep in deps:
            if dep not in committed_event_ids:
                interventions.append(
                    SubmitIntervention(
                        actor=actor,
                        reason_code="unmet_dependency",
                        reason=f"Dependency event '{dep}' not committed.",
                    )
                )

        if interventions:
            return SubmitCheckResult(
                status="blocked",
                interventions=interventions,
                parse_resolution="blocked_by_precheck",
            )
        return SubmitCheckResult(status="continue", parse_resolution="ok")


# ---------------------------------------------------------------------------
# M3 runtime stages (plug into resolve_turn_locked pipeline)
# ---------------------------------------------------------------------------


class StageIntervention(BaseModel):
    """One intervention emitted by a runtime pipeline stage."""

    actor: str
    reason_code: str
    reason: str
    kind: str = "block"  # block | redact | wait | info


# ---------------------------------------------------------------------------
# ScheduleGateStage
# ---------------------------------------------------------------------------


class ScheduleGateStage:
    """Verify barrier/causal pending state before committing this scene's events.

    If a barrier with ``required_event_ids`` exists whose required events are
    not yet committed, the stage returns ``status="wait"`` so the pipeline
    driver can choose to skip or delay this scene's events.
    """

    def run(self, ctx: Any) -> "StageResult":
        from .stage_context import StageResult

        ledger = ctx.ledger
        scene = ctx.scene

        barriers = list(getattr(ledger, "barriers", []) or [])
        scene_id = getattr(scene, "id", None)

        # Only barriers in an actively-raised state (waiting/blocked) are enforced;
        # "open" barriers are considered not yet in force and are skipped so the
        # pipeline never deadlocks in the early M3 rollout.
        for barrier in barriers:
            if barrier.scene_ids and scene_id and scene_id not in barrier.scene_ids:
                continue
            if barrier.status in ("satisfied", "open"):
                continue

            committed_event_ids = {
                e.id for e in (getattr(ledger, "events", []) or []) if e.committed
            }
            unmet = [
                eid for eid in (barrier.required_event_ids or [])
                if eid not in committed_event_ids
            ]
            if unmet:
                return StageResult(
                    status="wait",
                    interventions=[
                        StageIntervention(
                            actor=scene_id or "?",
                            reason_code="barrier_unmet",
                            reason=f"Barrier '{barrier.id}' unmet: {unmet}",
                            kind="wait",
                        )
                    ],
                )

        return StageResult(status="continue")


# ---------------------------------------------------------------------------
# FilterStage
# ----------------------------------------------------------------------------


class FilterStage:
    """Apply info-label authorization per character on the current event.

    Iterates the current event's ``output_info_ids``; when the linked
    ``InfoLabel`` has elevated sensitivity (>= medium) AND the acting
    character lacks authorization, a ``redact`` intervention is emitted.
    """

    _SENSITIVE_LEVELS = {"medium", "high", "keeper"}

    def run(self, ctx: Any) -> "StageResult":
        from .stage_context import StageResult

        ledger = ctx.ledger
        event = ctx.scratch.get("resolve_event")
        if event is None:
            return StageResult(status="continue")

        character = getattr(event, "character_id", None) or getattr(event, "actor", None)
        if not character:
            return StageResult(status="continue")

        labels = getattr(ledger, "info_labels", {}) or {}
        interventions: list[StageIntervention] = []

        for info_id in getattr(event, "output_info_ids", []) or []:
            label = labels.get(info_id)
            if label is None:
                continue
            sensitivity = getattr(label, "sensitivity", "public")
            if sensitivity not in self._SENSITIVE_LEVELS:
                continue
            authorized = (
                character in getattr(label, "authorized_character_ids", [])
                or character in getattr(label, "known_by_character_ids", [])
            )
            if not authorized:
                interventions.append(
                    StageIntervention(
                        actor=character,
                        reason_code="info_unauthorized",
                        reason=(
                            f"Info '{info_id}' (sensitivity={sensitivity}) "
                            f"not authorized for '{character}'."
                        ),
                        kind="redact",
                    )
                )

        return StageResult(status="continue", interventions=interventions)


# ---------------------------------------------------------------------------
# CouplingDriftStage
# ---------------------------------------------------------------------------


class CouplingDriftStage:
    """Compute scene-coupling drift; report but never block.

    Walks through the ledger's high-coupling links and accumulates
    time-drift between their source/target committed events.  Emits an
    ``info`` intervention whenever cumulative drift is positive.
    """

    HIGH_COUPLING_THRESHOLD = 0.75

    def run(self, ctx: Any) -> "StageResult":
        from .stage_context import StageResult

        ledger = ctx.ledger
        couplings = list(getattr(ledger, "couplings", []) or [])

        committed_events = [
            e for e in (getattr(ledger, "events", []) or []) if e.committed
        ]
        if not committed_events or not couplings:
            return StageResult(status="continue")

        committed_by_scene: dict[str, list[Any]] = {}
        for ev in committed_events:
            committed_by_scene.setdefault(ev.scene_id, []).append(ev)

        drift_minutes = 0
        for coupling in couplings:
            if coupling.coupling_score < self.HIGH_COUPLING_THRESHOLD:
                continue
            source_ends = [
                e.time_end_minute
                for e in committed_by_scene.get(coupling.source_scene_id, [])
            ]
            target_starts = [
                e.time_start_minute
                for e in committed_by_scene.get(coupling.target_scene_id, [])
            ]
            if source_ends and target_starts:
                drift_minutes += max(0, min(target_starts) - max(source_ends))

        interventions: list[StageIntervention] = []
        if drift_minutes > 0:
            interventions.append(
                StageIntervention(
                    actor=getattr(ctx.scene, "id", "?"),
                    reason_code="coupling_drift",
                    reason=f"Coupling drift accumulated: {drift_minutes} min",
                    kind="info",
                )
            )
        return StageResult(status="continue", interventions=interventions)


# ---------------------------------------------------------------------------
# AuditStage
# ---------------------------------------------------------------------------


class AuditStage:
    """Append audit-counter summary to ``ctx.scratch["audit_summary"]``.

    AuditStage never blocks — it is the final observability stage before
    commit.  Task 14's log writer consumes ``ctx.scratch["audit_summary"]``.
    """

    def run(self, ctx: Any) -> "StageResult":
        from .stage_context import StageResult

        ledger = ctx.ledger
        events = list(getattr(ledger, "events", []) or [])

        counters = {
            "causal_violations": 0,
            "unauthorized_actions": 0,
            "public_payload_leaks": 0,
            "committed_events": sum(1 for e in events if getattr(e, "committed", False)),
            "pending_events": sum(1 for e in events if not getattr(e, "committed", False)),
        }
        ctx.scratch["audit_summary"] = counters
        return StageResult(status="continue")
