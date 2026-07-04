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
