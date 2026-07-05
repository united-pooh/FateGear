from __future__ import annotations

import json

from scenario.ktsl.transcript import (
    TranscriptCoupling,
    TranscriptFixture,
    TranscriptInfoLabel,
    TranscriptManualLabel,
    TranscriptNormalizedAction,
    TranscriptScene,
    TranscriptTurn,
    render_transcript_report_json,
    render_transcript_report_markdown,
    replay_transcript,
)


def _anonymous_toy_transcript() -> TranscriptFixture:
    return TranscriptFixture(
        id="toy_transcript_req_002",
        title="Anonymous toy transcript for REQ-002",
        description=(
            "Toy data only: public overhearing, private declassification, "
            "cross-scene drift, and one legal low-confidence inference."
        ),
        scenes=(
            TranscriptScene(
                id="archive_public",
                name="Public archive room",
                participant_character_ids=("char_a", "char_b"),
                participant_speaker_ids=("speaker_a", "speaker_b"),
                time_start_minute=0,
                time_end_minute=25,
            ),
            TranscriptScene(
                id="cellar_threshold",
                name="Cellar threshold",
                participant_character_ids=("char_b",),
                participant_speaker_ids=("speaker_b",),
                time_start_minute=50,
                time_end_minute=60,
            ),
        ),
        info_labels=(
            TranscriptInfoLabel(
                id="info_archive_index",
                kind="obs",
                scene_id="archive_public",
                payload="An anonymized public shelf index points to a sealed room.",
                sensitivity="low",
                public_payload="Public shelf index mentions a sealed room.",
                observed_by_speaker_ids=("speaker_a", "speaker_b"),
            ),
            TranscriptInfoLabel(
                id="info_private_sigil",
                kind="know",
                scene_id="archive_public",
                payload="A private keeper note says the sigil identifies the cellar lock.",
                sensitivity="high",
                public_payload="",
                redaction="A private symbol clue is redacted.",
                known_by_character_ids=("char_a",),
                authorized_character_ids=("char_a",),
                expected_declassified_for_character_ids=("char_b",),
                should_declassify=True,
            ),
            TranscriptInfoLabel(
                id="info_sigil_public",
                kind="know",
                scene_id="archive_public",
                payload="The private sigil clue is summarized as a public lock hint.",
                sensitivity="low",
                public_payload="A safe summary points to the cellar lock.",
                known_by_character_ids=("char_a", "char_b"),
                authorized_character_ids=("char_a", "char_b"),
            ),
        ),
        turns=(
            TranscriptTurn(
                session_id="anon_session_001",
                turn_id="turn_public_overhear",
                speaker_id="speaker_a",
                character_id="char_a",
                channel="public",
                scene_id="archive_public",
                time_start_minute=0,
                time_end_minute=3,
                spotlight_start_minute=0,
                spotlight_end_minute=3,
                anonymized_summary="A public archive index is read aloud.",
                normalized_action=TranscriptNormalizedAction(
                    action_id="read_public_index",
                    text="Read the public shelf index aloud.",
                    output_info_ids=("info_archive_index",),
                    confidence=1.0,
                ),
                observed_info_ids=("info_archive_index",),
                manual_labels=(
                    TranscriptManualLabel(
                        annotator_id="blind_annotator_a",
                        label="public_overhearing",
                        value="observed_by_table",
                        reason="Both anonymous players could hear the public index.",
                    ),
                ),
            ),
            TranscriptTurn(
                session_id="anon_session_001",
                turn_id="turn_private_keeper_note",
                speaker_id="speaker_a",
                character_id="char_a",
                channel="private",
                scene_id="archive_public",
                time_start_minute=5,
                time_end_minute=9,
                spotlight_start_minute=5,
                spotlight_end_minute=9,
                anonymized_summary="The keeper privately gives character A a sigil clue.",
                normalized_action=TranscriptNormalizedAction(
                    action_id="receive_private_sigil",
                    text="Receive a private sigil clue.",
                    output_info_ids=("info_private_sigil",),
                    private_payload="Private sigil lock clue.",
                    redaction="Private clue redacted from public transcript.",
                    confidence=1.0,
                ),
            ),
            TranscriptTurn(
                session_id="anon_session_001",
                turn_id="turn_low_confidence_inference",
                speaker_id="speaker_b",
                character_id="char_b",
                channel="public",
                scene_id="cellar_threshold",
                time_start_minute=50,
                time_end_minute=56,
                spotlight_start_minute=1,
                spotlight_end_minute=4,
                anonymized_summary=(
                    "Character B makes a cautious, low-confidence inference "
                    "from public and declassified hints."
                ),
                normalized_action=TranscriptNormalizedAction(
                    action_id="infer_cellar_lock",
                    text="Infer that the cellar lock is relevant.",
                    required_info_ids=("info_archive_index", "info_sigil_public"),
                    depends_on_turn_ids=("turn_private_declassification",),
                    confidence=0.42,
                ),
                known_info_ids=("info_sigil_public",),
                observed_info_ids=("info_archive_index",),
                manual_labels=(
                    TranscriptManualLabel(
                        annotator_id="blind_annotator_a",
                        label="legal_low_confidence_inference",
                        value="legal",
                        reason=(
                            "The action uses public/declassified context, "
                            "not the private sigil payload."
                        ),
                        confidence=0.42,
                        run_mode="ktsl_full",
                    ),
                    TranscriptManualLabel(
                        annotator_id="blind_annotator_b",
                        label="causal_violation",
                        value="clear",
                        reason="Human annotator judged the narrative time window legal.",
                        run_mode="baseline",
                    ),
                ),
            ),
            TranscriptTurn(
                session_id="anon_session_001",
                turn_id="turn_private_declassification",
                speaker_id="speaker_a",
                character_id="char_a",
                channel="public",
                scene_id="archive_public",
                time_start_minute=15,
                time_end_minute=20,
                spotlight_start_minute=15,
                spotlight_end_minute=20,
                anonymized_summary=(
                    "Character A declassifies the private sigil as a safe public hint."
                ),
                normalized_action=TranscriptNormalizedAction(
                    action_id="declassify_sigil_hint",
                    text="Share only the safe public sigil summary.",
                    required_info_ids=("info_private_sigil",),
                    output_info_ids=("info_sigil_public",),
                    depends_on_turn_ids=("turn_private_keeper_note",),
                    public_payload="The lock clue can be discussed safely now.",
                    confidence=1.0,
                ),
                known_info_ids=("info_private_sigil",),
                manual_labels=(
                    TranscriptManualLabel(
                        annotator_id="blind_annotator_a",
                        label="private_declassification",
                        value="complete",
                        reason="Private clue was summarized without revealing raw payload.",
                        run_mode="ktsl_full",
                    ),
                ),
            ),
        ),
        couplings=(
            TranscriptCoupling(
                id="coupling_archive_to_cellar",
                source_scene_id="archive_public",
                target_scene_id="cellar_threshold",
                coupling_score=0.92,
                mode="locked",
                condition_type="required_info",
                required_info_ids=("info_sigil_public",),
                input_turn_ids=("turn_private_declassification",),
                expected_drift_minutes=30,
                rationale="The cellar threshold should wait for the safe lock hint.",
            ),
        ),
        manual_labels=(
            TranscriptManualLabel(
                annotator_id="blind_annotator_c",
                target_turn_id="turn_private_declassification",
                label="public_payload_leak",
                value="clear",
                reason="Blind annotation says the declassified summary is safe.",
                run_mode="ktsl_full",
            ),
        ),
    )


def test_transcript_replay_converts_to_ktsl_consumable_models() -> None:
    replay = replay_transcript(_anonymous_toy_transcript())

    assert replay.evidence_type == "transcript_replay"
    assert replay.ktsl_fixture.simulation_notice.startswith("Anonymous toy")
    assert {event.id for event in replay.ktsl_fixture.events} == {
        "evt_turn_public_overhear",
        "evt_turn_private_keeper_note",
        "evt_turn_low_confidence_inference",
        "evt_turn_private_declassification",
    }
    private_info = replay.ledger.info_labels["info_private_sigil"]
    assert private_info.sensitivity == "high"
    assert private_info.should_declassify is True
    assert "char_a" in replay.ledger.knowledge
    assert "info_private_sigil" in replay.ledger.knowledge["char_a"].known_info_ids
    assert "info_archive_index" in replay.ledger.knowledge["char_b"].observed_info_ids


def test_toy_transcript_replay_covers_req_002_metrics() -> None:
    replay = replay_transcript(_anonymous_toy_transcript())
    metrics = replay.report.metrics_by_mode

    assert metrics["baseline"]["causal_violation_count"] == 1
    assert metrics["schedule_only"]["causal_violation_count"] == 0
    assert metrics["schedule_only"]["public_payload_leak_count"] == 1
    assert metrics["ktsl_full"]["public_payload_leak_count"] == 0
    assert metrics["ktsl_full"]["declassification_completeness"] == 1.0
    assert metrics["schedule_only"]["high_coupling_time_drift_minutes"] == 30
    assert metrics["ktsl_full"]["high_coupling_time_drift_minutes"] == 0
    assert replay.report.hypothesis_summary["h1_schedule_reduces_causal_violations"]
    assert replay.report.hypothesis_summary["h2_filter_reduces_leaks"]
    assert replay.report.hypothesis_summary["h3_coupling_reduces_drift"]


def test_transcript_report_renderers_include_evidence_type_and_annotation_diffs() -> None:
    replay = replay_transcript(_anonymous_toy_transcript())

    payload = json.loads(render_transcript_report_json(replay.report))
    assert payload["evidence_type"] == "transcript_replay"
    assert payload["supported_evidence_types"] == [
        "deterministic_fixture",
        "live_provider_audit",
        "transcript_replay",
        "blind_annotation",
    ]
    assert "Toy data only" in payload["notice"]
    assert {
        diff["label"] for diff in payload["annotation_diffs"]
    } >= {"legal_low_confidence_inference", "causal_violation"}
    assert any(
        evidence["turn_id"] == "turn_low_confidence_inference"
        and evidence["metric"] == "causal_violation"
        for evidence in payload["audit_evidence"]
    )

    markdown = render_transcript_report_markdown(replay.report)
    assert "# KTSL Transcript Replay Report" in markdown
    assert "Evidence Type: `transcript_replay`" in markdown
    assert "`blind_annotation`" in markdown
    assert "turn_low_confidence_inference" in markdown
    assert "legal_low_confidence_inference" in markdown


def test_annotation_diff_examples_keep_manual_and_system_findings_separate() -> None:
    replay = replay_transcript(_anonymous_toy_transcript())

    causal_diff = next(
        diff
        for diff in replay.report.annotation_diffs
        if diff.label == "causal_violation"
        and diff.target_turn_id == "turn_low_confidence_inference"
    )
    assert causal_diff.evidence_type == "blind_annotation"
    assert causal_diff.manual_value == "clear"
    assert causal_diff.system_value == "flagged"
    assert causal_diff.diff_type == "disagreement"

    low_confidence_diff = next(
        diff
        for diff in replay.report.annotation_diffs
        if diff.label == "legal_low_confidence_inference"
    )
    assert low_confidence_diff.manual_value == "legal"
    assert low_confidence_diff.system_value == "allowed"
    assert low_confidence_diff.diff_type == "manual_context"
