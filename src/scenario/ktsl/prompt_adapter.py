"""KTSLPromptAdapter: reads KTSLLedger, writes prompt sections (no state held)."""
from __future__ import annotations

from typing import Any


class KTSLPromptAdapter:
    """Adapts KTSLLedger into prompt-friendly dicts for Plan/Render agents."""

    def build_plan_context(
        self, ledger: Any, scene: Any, intents: Any
    ) -> dict[str, Any]:
        """Produce a plan-prompt KTSL context block from the current ledger."""
        if ledger is None:
            return {}
        coupling_summary: dict[str, Any] = {}
        if hasattr(ledger, "scenes") and hasattr(ledger, "couplings"):
            for sid, sc in (ledger.scenes or {}).items():
                mode = "independent"
                score = 0.0
                for c in (ledger.couplings or []):
                    if (
                        c.source_scene_id == sid
                        or c.target_scene_id == sid
                    ):
                        mode = c.mode if c.mode != "independent" else mode
                        score = max(score, c.coupling_score)
                coupling_summary[sid] = {
                    "mode": mode,
                    "coupling_score": score,
                }
        return {
            "coupling_summary": coupling_summary,
            "barrier_debt": [],
            "wait_warnings": [],
            "pending_causal_edges": [],
        }

    def build_render_context(
        self,
        ledger: Any,
        decisions: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Produce render-prompt KTSL filter info."""
        if ledger is None:
            return {}
        decisions = decisions or []
        per_character: dict[str, list[Any]] = {}
        for d in decisions:
            cid = getattr(d, "character_id", None)
            if cid is None:
                continue
            per_character.setdefault(cid, []).append(d)
        return {"per_character_filter": per_character}

    def build_redaction_notice(self, decision: Any) -> str:
        """Produce a redacted-narration notice for a blocked character→info access.

        Delegates to the ``redaction`` prompt template so the KP-facing text
        stays consistent with paper §7.74 guidelines.
        """
        from .prompt_templates import render_redaction_notice

        character_name = getattr(decision, "character_id", None) or "?"
        info_id = getattr(decision, "info_id", None) or "?"
        return render_redaction_notice(
            character_name=character_name,
            info_id=info_id,
        )
