"""KP free-text input to EventRecord adapter.

Translates KP runtime input (natural-language action text) into a structured
``EventRecord`` that the existing ``schedule`` / ``filter`` / ``coupling``
pipeline can consume.
"""

from __future__ import annotations

import re
from hashlib import sha1

from .ktsl.models import (
    ActionParseResult,
    ClueRecord,
    EventRecord,
    InfoLabel,
    KTSLFixture,
    ManualOverrides,
)


_WORD_RE = re.compile(r"[a-zA-Z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Tokenize input into word tokens.

    - ASCII words → direct split.
    - Chinese runs → char bigrams + trigrams (jieba-free, zero-dep).
    """
    tokens: list[str] = []
    for match in _WORD_RE.finditer(text.lower()):
        token = match.group(0)
        if len(token) == 1:
            tokens.append(token)
            continue
        # bigrams + trigrams for any non-trivial token
        if len(token) == 2:
            tokens.append(token)
        elif len(token) == 3:
            tokens.append(token)
            tokens.append(token[:2])
            tokens.append(token[1:])
        else:
            tokens.append(token)
            for i in range(len(token) - 1):
                tokens.append(token[i : i + 2])
            for i in range(len(token) - 2):
                tokens.append(token[i : i + 3])
    return tokens


def _ngram_set(text: str) -> set[str]:  # noqa: D401
    return set(_tokenize(text))


# sensitivity levels that require explicit authorization
_SENSITIVE_LEVELS = {"medium", "high", "keeper"}

# matching threshold (matches design doc §6.3)
_MATCH_THRESHOLD = 0.3


class RuntimeEventAdapter:
    """Translate KP free-text input into an EventRecord."""

    def __init__(self, fixture: "KTSLFixture") -> None:
        self._fixture = fixture
        self._scene_clues: dict[str, list[ClueRecord]] = {}
        self._info_lookup: dict[str, InfoLabel] = {}
        for clue in fixture.clues:
            self._scene_clues.setdefault(clue.scene_id, []).append(clue)
        for info in fixture.info_labels:
            self._info_lookup[info.id] = info

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_action(
        self,
        action_text: str,
        actor: str,
        scene_id: str,
        committed_event_ids: set[str],
    ) -> ActionParseResult:
        """Match *action_text* against fixture clues in *scene_id*.

        Returns ``ActionParseResult`` with ``resolution`` one of
        ``"matched"``, ``"keyword_fallback"``, or ``"unresolved"``.
        """
        clues = self._scene_clues.get(scene_id, [])
        if not clues:
            return ActionParseResult(resolution="unresolved")

        action_lower = action_text.lower()
        action_ngrams = _ngram_set(action_text)
        candidates: list[tuple[str, float]] = []

        for clue in clues:
            # Exact substring match → matched
            title_lower = clue.title.lower()
            if title_lower and title_lower in action_lower:
                score = 1.0
            else:
                title_ngrams = _ngram_set(clue.title)
                hint_ngrams = _ngram_set(clue.public_hint)
                clue_ngrams = title_ngrams | hint_ngrams
                if not clue_ngrams:
                    score = 0.0
                else:
                    hits = len(action_ngrams & clue_ngrams)
                    score = hits / len(clue_ngrams)

            candidates.append((clue.id, round(score, 6)))

        # sort by score desc
        candidates.sort(key=lambda c: c[1], reverse=True)
        top_clue_id, top_score = candidates[0]

        if top_score < _MATCH_THRESHOLD:
            return ActionParseResult(
                resolution="unresolved",
                score=top_score,
                candidate_clues=candidates,
            )

        clue = next(c for c in clues if c.id == top_clue_id)

        # title exact/strong hit → matched
        resolution = (
            "matched"
            if top_score >= 0.6
            else "keyword_fallback"
        )

        event = self._build_event(clue, actor, scene_id, committed_event_ids)
        return ActionParseResult(
            resolution=resolution,
            event_record=event,
            matched_clue_id=clue.id,
            score=top_score,
            candidate_clues=candidates,
        )

    def resolve_manual(
        self,
        draft: EventRecord,
        overrides: ManualOverrides,
    ) -> EventRecord:
        """Overlay *overrides* onto *draft* and return a new EventRecord."""
        data = draft.model_dump()
        if overrides.output_info_ids:
            data["output_info_ids"] = list(overrides.output_info_ids)
        if overrides.required_info_ids:
            data["required_info_ids"] = list(overrides.required_info_ids)
        if overrides.barrier_id:
            data["barrier_id"] = overrides.barrier_id
        if overrides.causal_dependency_ids:
            data["causal_dependency_ids"] = list(overrides.causal_dependency_ids)
        if overrides.depends_on_event_ids:
            data["depends_on_event_ids"] = list(overrides.depends_on_event_ids)
        data["status"] = "committed"
        data["committed"] = True
        return EventRecord.model_validate(data)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_event(
        self,
        clue: ClueRecord,
        actor: str,
        scene_id: str,
        committed_event_ids: set[str],
    ) -> EventRecord:
        digest = sha1(
            f"{clue.id}:{scene_id}:{actor}:{len(committed_event_ids)}".encode()
        ).hexdigest()[:12]
        event_id = f"runtime_{digest}"

        # determine visibility from scene card (fallback public)
        visibility = "public"
        for scene in self._fixture.scenes:
            if scene.id == scene_id:
                # every scene has info_ids; visibility is scene-level concept —
                # default public unless explicitly tagged otherwise.
                break

        # character_id is inferred from participant list
        character_id = actor
        for scene in self._fixture.scenes:
            if scene.id == scene_id:
                if actor in scene.participant_character_ids:
                    character_id = actor
                elif actor in (scene.participant_player_ids or []):
                    idx = scene.participant_player_ids.index(actor)
                    if idx < len(scene.participant_character_ids):
                        character_id = scene.participant_character_ids[idx]
                break

        return EventRecord(
            id=event_id,
            scene_id=scene_id,
            action_id=f"runtime_action_{digest}",
            action_text=clue.title,
            actor=actor,
            character_id=character_id,
            is_settleable=clue.is_settleable,
            visibility=visibility,
            status="committed",
            committed=True,
            barrier_id="",
            required_info_ids=list(clue.required_info_ids),
            observed_info_ids=[],
            known_info_ids=[],
            output_info_ids=list(clue.output_info_ids),
            causal_dependency_ids=[],
            depends_on_event_ids=[],
        )
