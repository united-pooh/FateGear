"""Report data models for the KTSL KP toolchain.

This module defines the data contracts consumed by MarkdownRenderer and
HTMLRenderer in the sibling package. All models are pure Pydantic models
with zero dependencies on rendering or on Layer 4 orchestration.

Design notes:
- Models here mirror the contracts described in the toolchain design doc
  (docs/superpowers/specs/2026-07-04-ktsl-kp-toolchain-design.md §5).
- For the Phase 3+4 implementation we are intentionally self-contained:
  types that the Phase 1+2 worker may also add to ``ktsl.models`` (such as
  ``KnowledgeItem``, ``SessionConfig``, ``PublishGateResult``) are duplicated
  here to avoid mid-flight git-merge conflicts on ``models.py``.
  The duplicate definitions share the same schema so downstream consumers
  can treat the two versions as wire-compatible.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Re-exported primitives from ktsl.models (single source of truth).
# ---------------------------------------------------------------------------
from scenario.ktsl.models import (  # noqa: E402
    BarrierStatus,
    CommitStatus,
    CouplingMode,
    InfoKind,
    MetricSummary,
    RunMode,
    SensitivityLevel,
)

# ---------------------------------------------------------------------------
# Layer 4 (duplicated) models — kept here for self-containment.
# ---------------------------------------------------------------------------


class SessionConfig(BaseModel):
    """ktsl session session-declaration config (annotation manual calibration)."""

    session_id: str = Field(default="", max_length=80)
    fixture_id: str
    started_at: str = ""  # ISO timestamp
    kp_name: str = Field(default="", max_length=60)
    default_visibility: Literal["public", "private", "keeper"] = "public"
    allow_override: bool = True
    notes: str = Field(default="", max_length=2000)


class KnowledgeItem(BaseModel):
    """One cell in a character's knowledge map."""

    info_id: str
    kind: InfoKind  # know / obs
    sensitivity: SensitivityLevel
    content_summary: str  # InfoLabel.public_payload or truncated payload
    source_event_id: str  # acquired from which event
    source_scene_id: str
    acquired_at_minute: int = 0


# ---------------------------------------------------------------------------
# Layer 4 PublishGate result models.
# ---------------------------------------------------------------------------


class ModeThresholds(BaseModel):
    """Per-RunMode threshold configuration."""

    max_causal_violations: int | None = None
    max_unauthorized_actions: int | None = None
    max_public_payload_leaks: int | None = None
    max_spotlight_gap_minutes: int | None = None
    min_declassification_completeness: float | None = None
    max_retcons: int | None = None
    max_high_coupling_drift_minutes: int | None = None


class PublishCriteria(BaseModel):
    """Publish gate configuration (mirrors publish-criteria.yaml)."""

    version: str = "1.0.0"
    fixture_id: str = ""
    description: str = Field(default="", max_length=1000)
    thresholds: dict[RunMode, ModeThresholds] = Field(default_factory=dict)


class ModeResult(BaseModel):
    """Single RunMode simulation result used in publish report."""

    mode: RunMode
    passed: bool
    metrics: MetricSummary
    failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PublishGateResult(BaseModel):
    """Full publish gate verdict."""

    overall_pass: bool
    per_mode: list[ModeResult]
    evaluated_at: str  # ISO timestamp
    fixture_id: str
    criteria_version: str


# ---------------------------------------------------------------------------
# Layer 3 — Report view models (used only by the report subsystem).
# ---------------------------------------------------------------------------


class ViolationEvent(BaseModel):
    """A single violation event record."""

    event_id: str
    event_index: int  # S001, S002…
    actor: str
    action_text: str
    scene_id: str
    severity: Literal["info", "warning", "error"]
    metric: Literal[
        "causal_violation",
        "unauthorized_action",
        "public_payload_leak",
        "spotlight_gap",
        "declassification",
        "retcon",
        "coupling_drift",
    ]
    message: str
    overridden: bool = False


class EventSummary(BaseModel):
    """Per-scene timeline entry."""

    event_id: str
    event_index: int
    actor: str
    action_text: str
    time_minute: int = 0
    output_info_ids: list[str] = Field(default_factory=list)
    status: CommitStatus = "committed"


class KnowledgeItemView(BaseModel):
    """Report-oriented knowledge map entry (richer display fields)."""

    info_id: str
    kind: InfoKind
    sensitivity: SensitivityLevel
    content_summary: str
    source_event_id: str
    source_scene_id: str
    acquired_at_minute: int = 0
    leaked: bool = False  # True if this info was propagated outside authorized set


class SceneTimelineView(BaseModel):
    """One scene's timeline plus progress indicator."""

    scene_id: str
    scene_name: str = ""
    events: list[EventSummary] = Field(default_factory=list)
    total_events: int = 0
    committed_events: int = 0


class BarrierStateView(BaseModel):
    """Final state of a barrier."""

    barrier_id: str
    status: BarrierStatus
    required_event_ids: list[str] = Field(default_factory=list)
    satisfied_event_ids: list[str] = Field(default_factory=list)
    required_info_ids: list[str] = Field(default_factory=list)
    satisfied_info_ids: list[str] = Field(default_factory=list)


class CouplingStateView(BaseModel):
    """Final state of a coupling."""

    coupling_id: str
    source_scene_id: str
    target_scene_id: str
    mode: CouplingMode
    drift_minutes: int = 0
    active: bool = True


class SessionReport(BaseModel):
    """Complete session report data structure."""

    fixture_id: str
    fixture_title: str
    started_at: str
    ended_at: str
    session_config: SessionConfig | None = None
    total_events: int
    total_committed: int
    total_blocked: int
    total_overridden: int
    metrics: MetricSummary
    violation_timeline: list[ViolationEvent] = Field(default_factory=list)
    final_knowledge_map: dict[str, list[KnowledgeItemView]] = Field(default_factory=dict)
    scene_timelines: dict[str, list[EventSummary]] = Field(default_factory=dict)
    barrier_final_states: list[BarrierStateView] = Field(default_factory=list)
    coupling_final_states: list[CouplingStateView] = Field(default_factory=list)


class PublishReport(BaseModel):
    """Complete publish gate report data structure."""

    fixture_id: str
    fixture_title: str
    evaluated_at: str
    criteria_version: str
    overall_pass: bool
    per_mode: list[ModeResult]
    # Convenience: thresholds used (for MD/HTML rendering of threshold column)
    thresholds: dict[RunMode, ModeThresholds] = Field(default_factory=dict)


class ValidateIssue(BaseModel):
    """A single validation finding."""

    level: Literal["error", "warning", "info"]
    code: str  # e.g. "circular_dependency", "deadlock_barrier", "orphan_info"
    message: str
    resource_id: str = ""  # affected fixture resource (optional)


class ValidateReport(BaseModel):
    """Complete fixture validation report."""

    fixture_id: str
    fixture_title: str = ""
    validated_at: str = ""
    is_valid: bool
    issues: list[ValidateIssue] = Field(default_factory=list)


class ModuleStaticCheck(BaseModel):
    """Static check result used by `ktsl validate`."""

    fixture_id: str
    checks_passed: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
