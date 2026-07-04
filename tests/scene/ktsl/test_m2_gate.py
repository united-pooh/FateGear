"""M2 gate: submit_intent blocked by SubmitCheckStage when KTSL is active."""
from __future__ import annotations

import pytest

from scenario.ktsl.fixtures import build_library_sewer_church_fixture
from scenario.ktsl.models import KTSLLedger
from scenario.ktsl.wizard import build_spec_from_fixture
from scenario.runtime.contracts import KTSLBlockError
from scenario.runtime.engine import SceneRuntime
from tests.scene.card_fixtures import build_player_cards


@pytest.fixture
def ktsl_ledger() -> KTSLLedger:
    fixture = build_library_sewer_church_fixture()
    spec = build_spec_from_fixture(fixture)
    return KTSLLedger.from_module_spec(
        module_id="paper_library_sewer_church", spec=spec
    )


class TestM2Gate:
    def test_submit_blocked_when_strict_and_empty_text(
        self, ktsl_ledger: KTSLLedger
    ) -> None:
        """Strict-mode KTSL session blocks FreeformIntent with empty text.

        The KTSL ``SubmitCheckStage`` runs when ``session.ktsl_ledger`` is
        not ``None`` and rejects whitespace-only action text under strict
        mode (the same logical condition as truly empty text).  Pydantic's
        ``FreeformIntent.text`` has ``min_length=1`` so a literal ``""``
        would fail schema validation before reaching the stage; using ``" "``
        exercises the same blocked path.
        """
        runtime = SceneRuntime(roll_provider=lambda: 1)
        session = runtime.create_session(
            "generic_mvp",
            ["p1"],
            player_cards=build_player_cards(["p1"]),
        )

        # Attach the KTSL ledger so the submit-check runs.
        session.ktsl_ledger = ktsl_ledger

        with pytest.raises(KTSLBlockError) as exc_info:
            runtime.submit_intent(
                session.session_id,
                player_id="p1",
                intent={"type": "freeform", "text": " "},
            )
        assert "empty" in str(exc_info.value).lower()

    def test_submit_succeeds_without_ledger(self) -> None:
        """When no KTSL ledger is attached, the submit path is unrestricted."""
        runtime = SceneRuntime(roll_provider=lambda: 1)
        session = runtime.create_session(
            "generic_mvp",
            ["p1"],
            player_cards=build_player_cards(["p1"]),
        )

        # ktsl_ledger defaults to None; submitting must not raise.
        runtime.submit_intent(
            session.session_id,
            player_id="p1",
            intent={"type": "freeform", "text": "look around"},
        )
        # The pending intent is cached for the current turn.
        assert "p1" in session.pending_intents
