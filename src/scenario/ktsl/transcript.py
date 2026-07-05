"""Anonymous transcript replay support for KTSL evidence layering.

The module is intentionally standalone: transcript fixtures are plain
dataclasses, replay output is deterministic, and KTSL scoring is delegated to
the existing deterministic fixture evaluator.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from .evaluate import RUN_MODE_ORDER, evaluate_fixture
from .models import (
    ActorKnowledgeState,
    AuditMetric,
    AuditEntry,
    CouplingMode,
    EventRecord,
    EvaluationResult,
    InfoKind,
    InfoLabel,
    KTSLFixture,
    KTSLLedger,
    MetricSummary,
    RunMode,
    SceneCard,
    SceneCoupling,
    SensitivityLevel,
    Visibility,
)


EvidenceType = Literal[
    "deterministic_fixture",
    "live_provider_audit",
    "transcript_replay",
    "blind_annotation",
]
TranscriptChannel = Literal["public", "private", "keeper"]
AnnotationDiffType = Literal["agreement", "disagreement", "manual_context"]

SUPPORTED_EVIDENCE_TYPES: tuple[EvidenceType, ...] = (
    "deterministic_fixture",
    "live_provider_audit",
    "transcript_replay",
    "blind_annotation",
)
TRANSCRIPT_TOY_NOTICE = (
    "Anonymous toy transcript replay fixture. Toy data only; not real empirical "
    "play evidence and not a live provider audit."
)
AUDIT_METRICS: tuple[AuditMetric, ...] = (
    "causal_violation",
    "unauthorized_action",
    "public_payload_leak",
    "spotlight_gap",
    "declassification",
    "retcon",
    "coupling_drift",
)


@dataclass(frozen=True)
class TranscriptScene:
    """Anonymous scene slice with player/character participation and time window."""

    id: str
    name: str
    participant_character_ids: tuple[str, ...] = ()
    participant_speaker_ids: tuple[str, ...] = ()
    time_start_minute: int = 0
    time_end_minute: int = 0
    public_summary: str = ""
    keeper_summary: str = ""

    def __post_init__(self) -> None:
        _require_text("scene.id", self.id)
        _require_text("scene.name", self.name)
        _require_non_negative_window(
            "scene", self.time_start_minute, self.time_end_minute
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "TranscriptScene":
        return cls(
            id=str(payload["id"]),
            name=str(payload.get("name", payload["id"])),
            participant_character_ids=_tuple(payload.get("participant_character_ids")),
            participant_speaker_ids=_tuple(payload.get("participant_speaker_ids")),
            time_start_minute=int(payload.get("time_start_minute", 0)),
            time_end_minute=int(payload.get("time_end_minute", 0)),
            public_summary=str(payload.get("public_summary", "")),
            keeper_summary=str(payload.get("keeper_summary", "")),
        )

    def to_scene_card(self) -> SceneCard:
        return SceneCard(
            id=self.id,
            name=self.name,
            location_id=self.id,
            participant_character_ids=list(self.participant_character_ids),
            participant_player_ids=list(self.participant_speaker_ids),
            public_summary=self.public_summary,
            keeper_summary=self.keeper_summary,
            time_start_minute=self.time_start_minute,
            time_end_minute=self.time_end_minute,
            spotlight_start_minute=self.time_start_minute,
            spotlight_end_minute=self.time_end_minute,
        )


@dataclass(frozen=True)
class TranscriptInfoLabel:
    """Anonymous information label referenced by transcript turns."""

    id: str
    kind: InfoKind
    scene_id: str
    payload: str
    sensitivity: SensitivityLevel = "public"
    public_payload: str = ""
    redaction: str = ""
    source_turn_id: str = ""
    observed_by_speaker_ids: tuple[str, ...] = ()
    known_by_character_ids: tuple[str, ...] = ()
    authorized_character_ids: tuple[str, ...] = ()
    declassified_for_character_ids: tuple[str, ...] = ()
    expected_declassified_for_character_ids: tuple[str, ...] = ()
    should_declassify: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        _require_text("info.id", self.id)
        _require_text("info.scene_id", self.scene_id)
        _require_text("info.payload", self.payload)
        _validate_choice("info.kind", self.kind, ("know", "obs"))
        _validate_choice(
            "info.sensitivity",
            self.sensitivity,
            ("public", "low", "medium", "high", "keeper"),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "TranscriptInfoLabel":
        return cls(
            id=str(payload["id"]),
            kind=str(payload["kind"]),  # type: ignore[arg-type]
            scene_id=str(payload["scene_id"]),
            payload=str(payload["payload"]),
            sensitivity=str(payload.get("sensitivity", "public")),  # type: ignore[arg-type]
            public_payload=str(payload.get("public_payload", "")),
            redaction=str(payload.get("redaction", "")),
            source_turn_id=str(payload.get("source_turn_id", "")),
            observed_by_speaker_ids=_tuple(payload.get("observed_by_speaker_ids")),
            known_by_character_ids=_tuple(payload.get("known_by_character_ids")),
            authorized_character_ids=_tuple(payload.get("authorized_character_ids")),
            declassified_for_character_ids=_tuple(
                payload.get("declassified_for_character_ids")
            ),
            expected_declassified_for_character_ids=_tuple(
                payload.get("expected_declassified_for_character_ids")
            ),
            should_declassify=bool(payload.get("should_declassify", False)),
            notes=str(payload.get("notes", "")),
        )

    def to_info_label(self) -> InfoLabel:
        return InfoLabel(
            id=self.id,
            kind=self.kind,
            scene_id=self.scene_id,
            payload=self.payload,
            sensitivity=self.sensitivity,
            public_payload=self.public_payload,
            redaction=self.redaction,
            source_event_id=_event_id(self.source_turn_id) if self.source_turn_id else "",
            source_scene_id=self.scene_id,
            observed_by_player_ids=list(self.observed_by_speaker_ids),
            known_by_character_ids=list(self.known_by_character_ids),
            authorized_character_ids=list(self.authorized_character_ids),
            declassified_for_character_ids=list(self.declassified_for_character_ids),
            expected_declassified_for_character_ids=list(
                self.expected_declassified_for_character_ids
            ),
            should_declassify=self.should_declassify,
            notes=self.notes,
        )


@dataclass(frozen=True)
class TranscriptNormalizedAction:
    """Normalized action extracted from an anonymous transcript turn."""

    action_id: str
    text: str
    required_info_ids: tuple[str, ...] = ()
    output_info_ids: tuple[str, ...] = ()
    depends_on_turn_ids: tuple[str, ...] = ()
    confidence: float = 1.0
    public_payload: str = ""
    private_payload: str = ""
    redaction: str = ""
    is_settleable: bool = True

    def __post_init__(self) -> None:
        _require_text("normalized_action.action_id", self.action_id)
        _require_text("normalized_action.text", self.text)
        if not 0 <= self.confidence <= 1:
            raise ValueError("normalized_action.confidence must be between 0 and 1")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "TranscriptNormalizedAction":
        return cls(
            action_id=str(payload["action_id"]),
            text=str(payload["text"]),
            required_info_ids=_tuple(payload.get("required_info_ids")),
            output_info_ids=_tuple(payload.get("output_info_ids")),
            depends_on_turn_ids=_tuple(payload.get("depends_on_turn_ids")),
            confidence=float(payload.get("confidence", 1.0)),
            public_payload=str(payload.get("public_payload", "")),
            private_payload=str(payload.get("private_payload", "")),
            redaction=str(payload.get("redaction", "")),
            is_settleable=bool(payload.get("is_settleable", True)),
        )


@dataclass(frozen=True)
class TranscriptManualLabel:
    """Blind/manual annotation attached to a transcript turn or fixture."""

    annotator_id: str
    label: str
    value: str
    target_turn_id: str = ""
    reason: str = ""
    confidence: float | None = None
    run_mode: RunMode = "ktsl_full"
    evidence_type: EvidenceType = "blind_annotation"

    def __post_init__(self) -> None:
        _require_text("manual_label.annotator_id", self.annotator_id)
        _require_text("manual_label.label", self.label)
        _require_text("manual_label.value", self.value)
        _validate_choice("manual_label.run_mode", self.run_mode, RUN_MODE_ORDER)
        _validate_choice(
            "manual_label.evidence_type",
            self.evidence_type,
            SUPPORTED_EVIDENCE_TYPES,
        )
        if self.evidence_type != "blind_annotation":
            raise ValueError("manual labels must use blind_annotation evidence_type")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("manual_label.confidence must be between 0 and 1")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "TranscriptManualLabel":
        return cls(
            annotator_id=str(payload["annotator_id"]),
            label=str(payload["label"]),
            value=str(payload["value"]),
            target_turn_id=str(payload.get("target_turn_id", "")),
            reason=str(payload.get("reason", "")),
            confidence=(
                None
                if payload.get("confidence") is None
                else float(payload.get("confidence"))
            ),
            run_mode=str(payload.get("run_mode", "ktsl_full")),  # type: ignore[arg-type]
            evidence_type=str(payload.get("evidence_type", "blind_annotation")),  # type: ignore[arg-type]
        )

    def with_target(self, target_turn_id: str) -> "TranscriptManualLabel":
        if self.target_turn_id:
            return self
        return TranscriptManualLabel(
            annotator_id=self.annotator_id,
            label=self.label,
            value=self.value,
            target_turn_id=target_turn_id,
            reason=self.reason,
            confidence=self.confidence,
            run_mode=self.run_mode,
            evidence_type=self.evidence_type,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_type": self.evidence_type,
            "annotator_id": self.annotator_id,
            "target_turn_id": self.target_turn_id,
            "label": self.label,
            "value": self.value,
            "reason": self.reason,
            "confidence": self.confidence,
            "run_mode": self.run_mode,
        }


@dataclass(frozen=True)
class TranscriptTurn:
    """Single anonymized transcript turn."""

    session_id: str
    turn_id: str
    speaker_id: str
    character_id: str
    channel: TranscriptChannel
    scene_id: str
    time_start_minute: int
    time_end_minute: int
    normalized_action: TranscriptNormalizedAction
    utterance: str = ""
    anonymized_summary: str = ""
    known_info_ids: tuple[str, ...] = ()
    observed_info_ids: tuple[str, ...] = ()
    manual_labels: tuple[TranscriptManualLabel, ...] = ()
    spotlight_start_minute: int | None = None
    spotlight_end_minute: int | None = None

    def __post_init__(self) -> None:
        _require_text("turn.session_id", self.session_id)
        _require_text("turn.turn_id", self.turn_id)
        _require_text("turn.speaker_id", self.speaker_id)
        _require_text("turn.character_id", self.character_id)
        _require_text("turn.scene_id", self.scene_id)
        _validate_choice("turn.channel", self.channel, ("public", "private", "keeper"))
        _require_non_negative_window("turn", self.time_start_minute, self.time_end_minute)
        if not (self.utterance or self.anonymized_summary):
            raise ValueError("turn requires utterance or anonymized_summary")
        if (
            self.spotlight_start_minute is not None
            and self.spotlight_end_minute is not None
        ):
            _require_non_negative_window(
                "turn.spotlight",
                self.spotlight_start_minute,
                self.spotlight_end_minute,
            )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "TranscriptTurn":
        return cls(
            session_id=str(payload["session_id"]),
            turn_id=str(payload["turn_id"]),
            speaker_id=str(payload["speaker_id"]),
            character_id=str(payload["character_id"]),
            channel=str(payload["channel"]),  # type: ignore[arg-type]
            scene_id=str(payload["scene_id"]),
            time_start_minute=int(payload["time_start_minute"]),
            time_end_minute=int(payload["time_end_minute"]),
            normalized_action=TranscriptNormalizedAction.from_mapping(
                payload["normalized_action"]
            ),
            utterance=str(payload.get("utterance", "")),
            anonymized_summary=str(payload.get("anonymized_summary", "")),
            known_info_ids=_tuple(payload.get("known_info_ids")),
            observed_info_ids=_tuple(payload.get("observed_info_ids")),
            manual_labels=tuple(
                TranscriptManualLabel.from_mapping(label)
                for label in payload.get("manual_labels", ())
            ),
            spotlight_start_minute=(
                None
                if payload.get("spotlight_start_minute") is None
                else int(payload["spotlight_start_minute"])
            ),
            spotlight_end_minute=(
                None
                if payload.get("spotlight_end_minute") is None
                else int(payload["spotlight_end_minute"])
            ),
        )

    def to_event_record(self) -> EventRecord:
        action = self.normalized_action
        summary = self.utterance or self.anonymized_summary
        return EventRecord(
            id=_event_id(self.turn_id),
            scene_id=self.scene_id,
            action_id=action.action_id,
            action_text=action.text or summary,
            actor=self.speaker_id,
            player_id=self.speaker_id,
            character_id=self.character_id,
            is_settleable=action.is_settleable,
            visibility=_visibility_for_channel(self.channel),
            status="committed",
            committed=True,
            required_info_ids=list(action.required_info_ids),
            observed_info_ids=list(self.observed_info_ids),
            known_info_ids=list(self.known_info_ids),
            output_info_ids=list(action.output_info_ids),
            depends_on_event_ids=[_event_id(turn_id) for turn_id in action.depends_on_turn_ids],
            public_payload=action.public_payload,
            private_payload=action.private_payload,
            redaction=action.redaction,
            time_start_minute=self.time_start_minute,
            time_end_minute=self.time_end_minute,
            spotlight_start_minute=(
                self.time_start_minute
                if self.spotlight_start_minute is None
                else self.spotlight_start_minute
            ),
            spotlight_end_minute=(
                self.time_end_minute
                if self.spotlight_end_minute is None
                else self.spotlight_end_minute
            ),
            notes=(
                f"transcript_turn={self.turn_id};channel={self.channel};"
                f"confidence={action.confidence:.2f}"
            ),
        )


@dataclass(frozen=True)
class TranscriptCoupling:
    """Optional transcript annotation describing cross-scene coupling."""

    id: str
    source_scene_id: str
    target_scene_id: str
    coupling_score: float
    mode: CouplingMode = "linked"
    condition_type: str = "required_info"
    required_info_ids: tuple[str, ...] = ()
    required_scene_ids: tuple[str, ...] = ()
    input_turn_ids: tuple[str, ...] = ()
    output_info_ids: tuple[str, ...] = ()
    barrier_policy: Literal["none", "soft", "hard"] = "none"
    expected_drift_minutes: int = 0
    rationale: str = ""

    def __post_init__(self) -> None:
        _require_text("coupling.id", self.id)
        _require_text("coupling.source_scene_id", self.source_scene_id)
        _require_text("coupling.target_scene_id", self.target_scene_id)
        if not 0 <= self.coupling_score <= 1:
            raise ValueError("coupling.coupling_score must be between 0 and 1")
        _validate_choice(
            "coupling.mode", self.mode, ("independent", "loose", "linked", "locked")
        )
        _validate_choice(
            "coupling.barrier_policy", self.barrier_policy, ("none", "soft", "hard")
        )
        if self.expected_drift_minutes < 0:
            raise ValueError("coupling.expected_drift_minutes must be non-negative")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "TranscriptCoupling":
        return cls(
            id=str(payload["id"]),
            source_scene_id=str(payload["source_scene_id"]),
            target_scene_id=str(payload["target_scene_id"]),
            coupling_score=float(payload["coupling_score"]),
            mode=str(payload.get("mode", "linked")),  # type: ignore[arg-type]
            condition_type=str(payload.get("condition_type", "required_info")),
            required_info_ids=_tuple(payload.get("required_info_ids")),
            required_scene_ids=_tuple(payload.get("required_scene_ids")),
            input_turn_ids=_tuple(payload.get("input_turn_ids")),
            output_info_ids=_tuple(payload.get("output_info_ids")),
            barrier_policy=str(payload.get("barrier_policy", "none")),  # type: ignore[arg-type]
            expected_drift_minutes=int(payload.get("expected_drift_minutes", 0)),
            rationale=str(payload.get("rationale", "")),
        )

    def to_scene_coupling(self) -> SceneCoupling:
        return SceneCoupling(
            id=self.id,
            source_scene_id=self.source_scene_id,
            target_scene_id=self.target_scene_id,
            coupling_score=self.coupling_score,
            mode=self.mode,
            condition_type=self.condition_type,  # type: ignore[arg-type]
            required_info_ids=list(self.required_info_ids),
            required_scene_ids=list(self.required_scene_ids),
            input_event_ids=[_event_id(turn_id) for turn_id in self.input_turn_ids],
            output_info_ids=list(self.output_info_ids),
            barrier_policy=self.barrier_policy,
            expected_drift_minutes=self.expected_drift_minutes,
            rationale=self.rationale,
        )


@dataclass(frozen=True)
class TranscriptFixture:
    """Anonymous transcript fixture schema for REQ-002 replay."""

    id: str
    title: str
    turns: tuple[TranscriptTurn, ...]
    description: str = ""
    scenes: tuple[TranscriptScene, ...] = ()
    info_labels: tuple[TranscriptInfoLabel, ...] = ()
    couplings: tuple[TranscriptCoupling, ...] = ()
    manual_labels: tuple[TranscriptManualLabel, ...] = ()
    evidence_type: EvidenceType = "transcript_replay"
    is_toy_fixture: bool = True
    notice: str = TRANSCRIPT_TOY_NOTICE

    def __post_init__(self) -> None:
        _require_text("fixture.id", self.id)
        _require_text("fixture.title", self.title)
        if not self.turns:
            raise ValueError("transcript fixture requires at least one turn")
        _validate_choice(
            "fixture.evidence_type", self.evidence_type, SUPPORTED_EVIDENCE_TYPES
        )
        if self.evidence_type != "transcript_replay":
            raise ValueError("transcript fixtures must use transcript_replay evidence_type")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "TranscriptFixture":
        return cls(
            id=str(payload["id"]),
            title=str(payload["title"]),
            description=str(payload.get("description", "")),
            turns=tuple(
                TranscriptTurn.from_mapping(turn) for turn in payload.get("turns", ())
            ),
            scenes=tuple(
                TranscriptScene.from_mapping(scene)
                for scene in payload.get("scenes", ())
            ),
            info_labels=tuple(
                TranscriptInfoLabel.from_mapping(info)
                for info in payload.get("info_labels", ())
            ),
            couplings=tuple(
                TranscriptCoupling.from_mapping(coupling)
                for coupling in payload.get("couplings", ())
            ),
            manual_labels=tuple(
                TranscriptManualLabel.from_mapping(label)
                for label in payload.get("manual_labels", ())
            ),
            evidence_type=str(payload.get("evidence_type", "transcript_replay")),  # type: ignore[arg-type]
            is_toy_fixture=bool(payload.get("is_toy_fixture", True)),
            notice=str(payload.get("notice", TRANSCRIPT_TOY_NOTICE)),
        )


@dataclass(frozen=True)
class AnnotationDiff:
    """Manual-vs-system annotation comparison for replay reports."""

    evidence_type: EvidenceType
    annotator_id: str
    target_turn_id: str
    event_id: str
    run_mode: RunMode
    label: str
    manual_value: str
    system_value: str
    diff_type: AnnotationDiffType
    reason: str = ""
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_type": self.evidence_type,
            "annotator_id": self.annotator_id,
            "target_turn_id": self.target_turn_id,
            "event_id": self.event_id,
            "run_mode": self.run_mode,
            "label": self.label,
            "manual_value": self.manual_value,
            "system_value": self.system_value,
            "diff_type": self.diff_type,
            "reason": self.reason,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class TranscriptReplayReport:
    """Audit-style report produced from an anonymous transcript replay."""

    fixture_id: str
    fixture_title: str
    evidence_type: EvidenceType
    notice: str
    supported_evidence_types: tuple[EvidenceType, ...]
    metrics_by_mode: dict[str, dict[str, Any]]
    hypothesis_summary: dict[str, bool]
    audit_evidence: list[dict[str, Any]]
    annotation_diffs: list[AnnotationDiff]
    events: list[dict[str, Any]]
    info_labels: list[dict[str, Any]]
    knowledge_updates: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "fixture_title": self.fixture_title,
            "evidence_type": self.evidence_type,
            "notice": self.notice,
            "supported_evidence_types": list(self.supported_evidence_types),
            "metrics_by_mode": self.metrics_by_mode,
            "hypothesis_summary": self.hypothesis_summary,
            "audit_evidence": self.audit_evidence,
            "annotation_diffs": [diff.to_dict() for diff in self.annotation_diffs],
            "events": self.events,
            "info_labels": self.info_labels,
            "knowledge_updates": self.knowledge_updates,
        }


@dataclass(frozen=True)
class TranscriptReplayResult:
    """Full replay bundle: KTSL fixture, ledger, evaluation, and report."""

    evidence_type: EvidenceType
    transcript: TranscriptFixture
    ktsl_fixture: KTSLFixture
    ledger: KTSLLedger
    evaluations: tuple[EvaluationResult, ...]
    report: TranscriptReplayReport


def anonymous_transcript_fixture_schema() -> dict[str, Any]:
    """Return a compact JSON-schema-like description of supported fixtures."""

    return {
        "evidence_type": "transcript_replay",
        "required_fixture_fields": ["id", "title", "turns"],
        "required_turn_fields": [
            "session_id",
            "turn_id",
            "speaker_id",
            "character_id",
            "channel",
            "scene_id",
            "time_start_minute",
            "time_end_minute",
            "utterance_or_anonymized_summary",
            "normalized_action",
            "known_info_ids",
            "observed_info_ids",
            "manual_labels",
        ],
        "channels": ["public", "private", "keeper"],
        "supported_evidence_types": list(SUPPORTED_EVIDENCE_TYPES),
    }


def transcript_fixture_from_dict(payload: Mapping[str, Any]) -> TranscriptFixture:
    """Parse a dict payload into the anonymous transcript fixture schema."""

    return TranscriptFixture.from_mapping(payload)


def transcript_to_ktsl_fixture(transcript: TranscriptFixture) -> KTSLFixture:
    """Convert an anonymous transcript into a deterministic KTSL fixture."""

    scenes = _scene_cards(transcript)
    info_labels = _info_labels(transcript)
    events = [turn.to_event_record() for turn in transcript.turns]
    couplings = [coupling.to_scene_coupling() for coupling in transcript.couplings]
    return KTSLFixture(
        id=transcript.id,
        title=transcript.title,
        description=transcript.description,
        scenes=scenes,
        info_labels=info_labels,
        events=events,
        couplings=couplings,
        run_modes=list(RUN_MODE_ORDER),
        simulation_notice=transcript.notice,
        seed_label="anonymous_transcript_toy" if transcript.is_toy_fixture else "transcript_replay",
        metadata={
            "evidence_type": transcript.evidence_type,
            "is_toy_fixture": transcript.is_toy_fixture,
            "source": "anonymous_transcript_fixture",
        },
    )


def replay_transcript(
    transcript: TranscriptFixture,
    run_modes: tuple[RunMode, ...] = RUN_MODE_ORDER,
) -> TranscriptReplayResult:
    """Replay a transcript fixture through existing KTSL evaluation layers."""

    ktsl_fixture = transcript_to_ktsl_fixture(transcript)
    evaluations = tuple(evaluate_fixture(ktsl_fixture, run_mode) for run_mode in run_modes)
    ledger = _ledger_from_replay(transcript, ktsl_fixture)
    report = _build_report(transcript, ktsl_fixture, ledger, evaluations)
    return TranscriptReplayResult(
        evidence_type="transcript_replay",
        transcript=transcript,
        ktsl_fixture=ktsl_fixture,
        ledger=ledger,
        evaluations=evaluations,
        report=report,
    )


def render_transcript_report_json(report: TranscriptReplayReport) -> str:
    """Render transcript replay report as deterministic JSON."""

    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


def render_transcript_report_markdown(report: TranscriptReplayReport) -> str:
    """Render transcript replay report as compact Markdown."""

    metric_names = [
        "causal_violation_count",
        "unauthorized_action_count",
        "public_payload_leak_count",
        "declassification_completeness",
        "high_coupling_time_drift_minutes",
        "spotlight_max_gap_minutes",
    ]
    lines = [
        "# KTSL Transcript Replay Report",
        "",
        f"- Fixture: `{report.fixture_id}`",
        f"- Evidence Type: `{report.evidence_type}`",
        f"- Notice: {report.notice}",
        "- Evidence Layers: "
        + ", ".join(f"`{evidence_type}`" for evidence_type in report.supported_evidence_types),
        "",
        "## Metrics",
        "",
        "| mode | " + " | ".join(metric_names) + " |",
        "| " + " | ".join(["---", *["---" for _ in metric_names]]) + " |",
    ]
    for mode in RUN_MODE_ORDER:
        if mode not in report.metrics_by_mode:
            continue
        metrics = report.metrics_by_mode[mode]
        lines.append(
            "| "
            + " | ".join([mode, *[_format_markdown_value(metrics[name]) for name in metric_names]])
            + " |"
        )

    lines.extend(
        [
            "",
            "## Annotation Diffs",
            "",
            "| turn | mode | label | manual | system | diff |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for diff in report.annotation_diffs:
        lines.append(
            "| "
            + " | ".join(
                [
                    diff.target_turn_id,
                    diff.run_mode,
                    diff.label,
                    diff.manual_value,
                    diff.system_value,
                    diff.diff_type,
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Audit Evidence",
            "",
            "| mode | metric | turn | scene | message |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for evidence in report.audit_evidence:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(evidence["run_mode"]),
                    str(evidence["metric"]),
                    str(evidence["turn_id"]),
                    str(evidence["scene_id"]),
                    _escape_table(str(evidence["message"])),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _build_report(
    transcript: TranscriptFixture,
    ktsl_fixture: KTSLFixture,
    ledger: KTSLLedger,
    evaluations: tuple[EvaluationResult, ...],
) -> TranscriptReplayReport:
    metrics_by_mode = {
        result.run_mode: _metrics_to_dict(result.metrics) for result in evaluations
    }
    audit_evidence = _audit_evidence(transcript, evaluations)
    annotation_diffs = _annotation_diffs(transcript, audit_evidence)
    return TranscriptReplayReport(
        fixture_id=transcript.id,
        fixture_title=transcript.title,
        evidence_type="transcript_replay",
        notice=transcript.notice,
        supported_evidence_types=SUPPORTED_EVIDENCE_TYPES,
        metrics_by_mode=metrics_by_mode,
        hypothesis_summary=_hypothesis_summary(metrics_by_mode),
        audit_evidence=audit_evidence,
        annotation_diffs=annotation_diffs,
        events=[
            _event_report_entry(turn, event)
            for turn, event in zip(transcript.turns, ktsl_fixture.events)
        ],
        info_labels=[
            {
                "id": info.id,
                "kind": info.kind,
                "scene_id": info.scene_id,
                "sensitivity": info.sensitivity,
                "source_event_id": info.source_event_id,
                "should_declassify": info.should_declassify,
                "expected_declassified_for_character_ids": list(
                    info.expected_declassified_for_character_ids
                ),
            }
            for info in ktsl_fixture.info_labels
        ],
        knowledge_updates=[
            {
                "character_id": character_id,
                "player_id": state.player_id,
                "known_info_ids": list(state.known_info_ids),
                "observed_info_ids": list(state.observed_info_ids),
                "authorized_info_ids": list(state.authorized_info_ids),
            }
            for character_id, state in sorted(ledger.knowledge.items())
        ],
    )


def _scene_cards(transcript: TranscriptFixture) -> list[SceneCard]:
    if transcript.scenes:
        return [scene.to_scene_card() for scene in transcript.scenes]

    by_scene: dict[str, dict[str, Any]] = {}
    for turn in transcript.turns:
        state = by_scene.setdefault(
            turn.scene_id,
            {
                "characters": [],
                "speakers": [],
                "start": turn.time_start_minute,
                "end": turn.time_end_minute,
            },
        )
        if turn.character_id not in state["characters"]:
            state["characters"].append(turn.character_id)
        if turn.speaker_id not in state["speakers"]:
            state["speakers"].append(turn.speaker_id)
        state["start"] = min(state["start"], turn.time_start_minute)
        state["end"] = max(state["end"], turn.time_end_minute)

    return [
        SceneCard(
            id=scene_id,
            name=scene_id,
            location_id=scene_id,
            participant_character_ids=state["characters"],
            participant_player_ids=state["speakers"],
            time_start_minute=state["start"],
            time_end_minute=state["end"],
            spotlight_start_minute=state["start"],
            spotlight_end_minute=state["end"],
        )
        for scene_id, state in by_scene.items()
    ]


def _info_labels(transcript: TranscriptFixture) -> list[InfoLabel]:
    declared = {info.id: info.to_info_label() for info in transcript.info_labels}
    referenced = _referenced_info_ids(transcript)
    for info_id in referenced:
        if info_id in declared:
            continue
        declared[info_id] = InfoLabel(
            id=info_id,
            kind="know",
            scene_id=_scene_for_info(info_id, transcript),
            payload=f"Anonymous transcript summary for {info_id}.",
            sensitivity="low",
            public_payload=f"Anonymous transcript summary for {info_id}.",
        )
    return list(declared.values())


def _referenced_info_ids(transcript: TranscriptFixture) -> set[str]:
    info_ids: set[str] = set()
    for turn in transcript.turns:
        info_ids.update(turn.known_info_ids)
        info_ids.update(turn.observed_info_ids)
        info_ids.update(turn.normalized_action.required_info_ids)
        info_ids.update(turn.normalized_action.output_info_ids)
    for coupling in transcript.couplings:
        info_ids.update(coupling.required_info_ids)
        info_ids.update(coupling.output_info_ids)
    return info_ids


def _scene_for_info(info_id: str, transcript: TranscriptFixture) -> str:
    for turn in transcript.turns:
        action = turn.normalized_action
        if (
            info_id in turn.known_info_ids
            or info_id in turn.observed_info_ids
            or info_id in action.required_info_ids
            or info_id in action.output_info_ids
        ):
            return turn.scene_id
    return transcript.turns[0].scene_id


def _ledger_from_replay(
    transcript: TranscriptFixture, ktsl_fixture: KTSLFixture
) -> KTSLLedger:
    return KTSLLedger(
        module_id=_module_id(transcript.id),
        scenes={scene.id: scene for scene in ktsl_fixture.scenes},
        events=list(ktsl_fixture.events),
        info_labels={info.id: info for info in ktsl_fixture.info_labels},
        couplings=list(ktsl_fixture.couplings),
        knowledge=_knowledge_from_transcript(transcript, ktsl_fixture.info_labels),
    )


def _knowledge_from_transcript(
    transcript: TranscriptFixture, info_labels: list[InfoLabel]
) -> dict[str, ActorKnowledgeState]:
    speaker_for_character = {
        turn.character_id: turn.speaker_id for turn in transcript.turns if turn.character_id
    }
    knowledge = {
        character_id: ActorKnowledgeState(
            player_id=speaker_id,
            character_id=character_id,
            known_info_ids=[],
            observed_info_ids=[],
            authorized_info_ids=[],
        )
        for character_id, speaker_id in speaker_for_character.items()
    }
    info_lookup = {info.id: info for info in info_labels}
    scene_participants = _scene_participants(transcript)

    for info in info_labels:
        for character_id in info.known_by_character_ids:
            _state(knowledge, character_id, speaker_for_character).known_info_ids.append(
                info.id
            )
        for character_id in info.authorized_character_ids:
            _state(
                knowledge, character_id, speaker_for_character
            ).authorized_info_ids.append(info.id)

    for turn in transcript.turns:
        actor_state = _state(knowledge, turn.character_id, speaker_for_character)
        actor_state.known_info_ids.extend(turn.known_info_ids)
        actor_state.observed_info_ids.extend(turn.observed_info_ids)
        for info_id in turn.normalized_action.output_info_ids:
            info = info_lookup.get(info_id)
            if turn.channel == "public":
                for character_id in scene_participants.get(turn.scene_id, (turn.character_id,)):
                    _state(
                        knowledge, character_id, speaker_for_character
                    ).observed_info_ids.append(info_id)
            elif turn.channel == "private":
                actor_state.known_info_ids.append(info_id)
            elif info is not None and info.sensitivity != "keeper":
                actor_state.known_info_ids.append(info_id)

    for state in knowledge.values():
        state.known_info_ids = _dedupe(state.known_info_ids)
        state.observed_info_ids = _dedupe(state.observed_info_ids)
        state.authorized_info_ids = _dedupe(state.authorized_info_ids)
    return knowledge


def _state(
    knowledge: dict[str, ActorKnowledgeState],
    character_id: str,
    speaker_for_character: Mapping[str, str],
) -> ActorKnowledgeState:
    if character_id not in knowledge:
        knowledge[character_id] = ActorKnowledgeState(
            player_id=speaker_for_character.get(character_id, ""),
            character_id=character_id,
        )
    return knowledge[character_id]


def _scene_participants(transcript: TranscriptFixture) -> dict[str, tuple[str, ...]]:
    participants: dict[str, list[str]] = {}
    for scene in transcript.scenes:
        participants[scene.id] = list(scene.participant_character_ids)
    for turn in transcript.turns:
        scene_participants = participants.setdefault(turn.scene_id, [])
        if turn.character_id not in scene_participants:
            scene_participants.append(turn.character_id)
    return {scene_id: tuple(character_ids) for scene_id, character_ids in participants.items()}


def _audit_evidence(
    transcript: TranscriptFixture, evaluations: tuple[EvaluationResult, ...]
) -> list[dict[str, Any]]:
    turn_lookup = {_event_id(turn.turn_id): turn for turn in transcript.turns}
    evidence: list[dict[str, Any]] = []
    for result in evaluations:
        for entry in result.audit_entries:
            turn = turn_lookup.get(entry.event_id)
            evidence.append(_audit_entry_to_evidence(result.run_mode, entry, turn))
    return evidence


def _audit_entry_to_evidence(
    run_mode: RunMode, entry: AuditEntry, turn: TranscriptTurn | None
) -> dict[str, Any]:
    return {
        "evidence_type": "transcript_replay",
        "run_mode": run_mode,
        "metric": entry.metric,
        "severity": entry.severity,
        "session_id": "" if turn is None else turn.session_id,
        "turn_id": "" if turn is None else turn.turn_id,
        "event_id": entry.event_id,
        "scene_id": entry.scene_id,
        "speaker_id": "" if turn is None else turn.speaker_id,
        "character_id": entry.character_id or ("" if turn is None else turn.character_id),
        "message": entry.message,
        "caused_by_event_ids": list(entry.caused_by_event_ids),
        "caused_by_info_ids": list(entry.caused_by_info_ids),
    }


def _annotation_diffs(
    transcript: TranscriptFixture, audit_evidence: list[dict[str, Any]]
) -> list[AnnotationDiff]:
    flags = {
        (str(evidence["run_mode"]), str(evidence["event_id"]), str(evidence["metric"]))
        for evidence in audit_evidence
    }
    labels = _manual_labels(transcript)
    diffs: list[AnnotationDiff] = []
    for label in labels:
        event_id = _event_id(label.target_turn_id)
        if label.label in AUDIT_METRICS:
            manual_value = _manual_flag_value(label.value)
            system_value = (
                "flagged"
                if (label.run_mode, event_id, label.label) in flags
                else "clear"
            )
            diff_type: AnnotationDiffType = (
                "agreement" if manual_value == system_value else "disagreement"
            )
        elif label.label == "legal_low_confidence_inference":
            manual_value = label.value
            system_value = (
                "flagged"
                if _event_has_flag(
                    flags,
                    label.run_mode,
                    event_id,
                    ("unauthorized_action", "public_payload_leak"),
                )
                else "allowed"
            )
            diff_type = "manual_context"
        else:
            manual_value = label.value
            system_value = "not_applicable"
            diff_type = "manual_context"
        diffs.append(
            AnnotationDiff(
                evidence_type="blind_annotation",
                annotator_id=label.annotator_id,
                target_turn_id=label.target_turn_id,
                event_id=event_id,
                run_mode=label.run_mode,
                label=label.label,
                manual_value=manual_value,
                system_value=system_value,
                diff_type=diff_type,
                reason=label.reason,
                confidence=label.confidence,
            )
        )
    return diffs


def _manual_labels(transcript: TranscriptFixture) -> list[TranscriptManualLabel]:
    labels: list[TranscriptManualLabel] = []
    for turn in transcript.turns:
        labels.extend(label.with_target(turn.turn_id) for label in turn.manual_labels)
    labels.extend(transcript.manual_labels)
    return labels


def _event_has_flag(
    flags: set[tuple[str, str, str]],
    run_mode: RunMode,
    event_id: str,
    metrics: tuple[AuditMetric, ...],
) -> bool:
    return any((run_mode, event_id, metric) in flags for metric in metrics)


def _manual_flag_value(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"flagged", "true", "yes", "present", "violation"}:
        return "flagged"
    if normalized in {"clear", "false", "no", "absent", "none", "legal"}:
        return "clear"
    return normalized


def _hypothesis_summary(metrics_by_mode: dict[str, dict[str, Any]]) -> dict[str, bool]:
    baseline = metrics_by_mode.get("baseline", {})
    schedule_only = metrics_by_mode.get("schedule_only", {})
    ktsl_full = metrics_by_mode.get("ktsl_full", {})
    return {
        "h1_schedule_reduces_causal_violations": int(
            schedule_only.get("causal_violation_count", 0)
        )
        < int(baseline.get("causal_violation_count", 0)),
        "h2_filter_reduces_leaks": int(ktsl_full.get("public_payload_leak_count", 0))
        < int(schedule_only.get("public_payload_leak_count", 0)),
        "h2_declassification_completeness_improves": float(
            ktsl_full.get("declassification_completeness", 0.0)
        )
        > float(schedule_only.get("declassification_completeness", 0.0)),
        "h3_coupling_reduces_drift": int(
            ktsl_full.get("high_coupling_time_drift_minutes", 0)
        )
        < int(schedule_only.get("high_coupling_time_drift_minutes", 0)),
    }


def _metrics_to_dict(metrics: MetricSummary) -> dict[str, Any]:
    return metrics.model_dump(mode="json")


def _event_report_entry(turn: TranscriptTurn, event: EventRecord) -> dict[str, Any]:
    return {
        "evidence_type": "transcript_replay",
        "session_id": turn.session_id,
        "turn_id": turn.turn_id,
        "event_id": event.id,
        "speaker_id": turn.speaker_id,
        "character_id": turn.character_id,
        "channel": turn.channel,
        "scene_id": turn.scene_id,
        "time_window": [turn.time_start_minute, turn.time_end_minute],
        "utterance_present": bool(turn.utterance),
        "anonymized_summary": turn.anonymized_summary,
        "normalized_action": {
            "action_id": turn.normalized_action.action_id,
            "text": turn.normalized_action.text,
            "confidence": turn.normalized_action.confidence,
            "required_info_ids": list(turn.normalized_action.required_info_ids),
            "output_info_ids": list(turn.normalized_action.output_info_ids),
            "depends_on_turn_ids": list(turn.normalized_action.depends_on_turn_ids),
        },
        "known_info_ids": list(turn.known_info_ids),
        "observed_info_ids": list(turn.observed_info_ids),
        "manual_labels": [
            label.with_target(turn.turn_id).to_dict() for label in turn.manual_labels
        ],
    }


def _format_markdown_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|")


def _event_id(turn_id: str) -> str:
    return turn_id if turn_id.startswith("evt_") else f"evt_{turn_id}"


def _module_id(fixture_id: str) -> str:
    return fixture_id[:30] or "transcript_replay"


def _visibility_for_channel(channel: TranscriptChannel) -> Visibility:
    if channel == "keeper":
        return "keeper"
    if channel == "private":
        return "private"
    return "public"


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _require_text(field_name: str, value: str) -> None:
    if not value:
        raise ValueError(f"{field_name} is required")


def _require_non_negative_window(
    field_name: str, start_minute: int, end_minute: int
) -> None:
    if start_minute < 0 or end_minute < 0:
        raise ValueError(f"{field_name} time window must be non-negative")
    if end_minute < start_minute:
        raise ValueError(f"{field_name} time window end must be >= start")


def _validate_choice(field_name: str, value: str, choices: tuple[str, ...]) -> None:
    if value not in choices:
        raise ValueError(f"{field_name} must be one of {', '.join(choices)}")


__all__ = [
    "AnnotationDiff",
    "EvidenceType",
    "SUPPORTED_EVIDENCE_TYPES",
    "TRANSCRIPT_TOY_NOTICE",
    "TranscriptChannel",
    "TranscriptCoupling",
    "TranscriptFixture",
    "TranscriptInfoLabel",
    "TranscriptManualLabel",
    "TranscriptNormalizedAction",
    "TranscriptReplayReport",
    "TranscriptReplayResult",
    "TranscriptScene",
    "TranscriptTurn",
    "anonymous_transcript_fixture_schema",
    "render_transcript_report_json",
    "render_transcript_report_markdown",
    "replay_transcript",
    "transcript_fixture_from_dict",
    "transcript_to_ktsl_fixture",
]
