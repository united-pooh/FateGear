"""确定性的自然语言意图归一化器。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..module.models import ModuleAction, ModuleDefinition, ModuleScene
from ..session.state import SessionMapState
from .models import NormalizedIntentResult

if TYPE_CHECKING:
    from ..runtime.engine import SceneRuntime


@dataclass(frozen=True)
class _Match:
    kind: str
    item_id: str
    label: str
    confidence: float


class IntentNormalizer:
    """把短自然语言输入归一化为当前 runtime 支持的结构化意图。"""

    _MOVE_HINTS = ("去", "到", "进入", "前往", "移动", "走向", "返回", "回到")
    _OBSERVE_TERMS = (
        "观察",
        "查看周围",
        "看看周围",
        "看周围",
        "环顾",
        "环视",
        "环绕四周",
        "四周",
        "周围环境",
        "确认情况",
        "什么情况",
        "现在情况",
        "打量",
        "感知",
        "听听",
        "闻闻",
    )

    def normalize(
        self,
        *,
        runtime: "SceneRuntime",
        session: SessionMapState,
        module: ModuleDefinition,
        player_id: str,
        raw_text: str,
    ) -> NormalizedIntentResult:
        if player_id not in session.player_states:
            raise KeyError(f"未知玩家: {player_id}")
        text = raw_text.strip()
        normalized_text = self._normalize_text(text)
        if not normalized_text:
            return self._clarify(
                player_id=player_id,
                raw_text=raw_text,
                question="请描述你想去哪里，或想调查/操作什么。",
                candidates=[],
            )

        move_matches = self._match_moves(
            runtime=runtime,
            session=session,
            module=module,
            player_id=player_id,
            normalized_text=normalized_text,
        )
        action_matches = self._match_actions(
            runtime=runtime,
            session=session,
            player_id=player_id,
            normalized_text=normalized_text,
        )
        matches = sorted(
            [*move_matches, *action_matches],
            key=lambda item: (-item.confidence, item.kind, item.item_id),
        )
        if len(matches) == 1:
            return self._accepted(
                player_id=player_id,
                raw_text=raw_text,
                match=matches[0],
            )
        if len(matches) > 1 and matches[0].confidence > matches[1].confidence:
            return self._accepted(
                player_id=player_id,
                raw_text=raw_text,
                match=matches[0],
            )
        observe_score = self._observe_match_score(normalized_text)
        if observe_score > 0 and not matches:
            return self._accepted(
                player_id=player_id,
                raw_text=raw_text,
                match=_Match(
                    kind="observe",
                    item_id="observe",
                    label="观察当前环境",
                    confidence=observe_score,
                ),
            )
        return self._clarify(
            player_id=player_id,
            raw_text=raw_text,
            question="这个意图有些含糊，请明确你要移动到哪个场景、执行哪个动作，或说你想观察环境。",
            candidates=[match.label for match in matches] or self._available_labels(
                runtime=runtime,
                session=session,
                module=module,
                player_id=player_id,
            ),
        )

    def _match_moves(
        self,
        *,
        runtime: "SceneRuntime",
        session: SessionMapState,
        module: ModuleDefinition,
        player_id: str,
        normalized_text: str,
    ) -> list[_Match]:
        scene_map = module.scene_map()
        reachable_ids = runtime.list_reachable_scenes(session, player_id)
        matches: list[_Match] = []
        for scene_id in reachable_ids:
            scene = scene_map[scene_id]
            score = self._scene_match_score(scene, normalized_text)
            if score <= 0:
                continue
            if any(hint in normalized_text for hint in self._MOVE_HINTS):
                score = min(1.0, score + 0.1)
            matches.append(
                _Match(
                    kind="move",
                    item_id=scene.id,
                    label=f"移动到「{scene.name}」",
                    confidence=score,
                )
            )
        return matches

    def _match_actions(
        self,
        *,
        runtime: "SceneRuntime",
        session: SessionMapState,
        player_id: str,
        normalized_text: str,
    ) -> list[_Match]:
        matches: list[_Match] = []
        for action in runtime.list_available_actions(session, player_id):
            score = self._action_match_score(action, normalized_text)
            if score <= 0:
                continue
            matches.append(
                _Match(
                    kind="action",
                    item_id=action.id,
                    label=f"执行「{action.name}」",
                    confidence=score,
                )
            )
        return matches

    def _scene_match_score(self, scene: ModuleScene, normalized_text: str) -> float:
        terms = [scene.id, scene.name, *scene.tags]
        return self._best_term_score(terms, normalized_text, exact_score=0.9)

    def _action_match_score(self, action: ModuleAction, normalized_text: str) -> float:
        terms = [
            action.id,
            action.name,
            action.kind,
            *action.aliases,
            *action.expected_inputs,
        ]
        return self._best_term_score(terms, normalized_text, exact_score=0.95)

    def _observe_match_score(self, normalized_text: str) -> float:
        return self._best_term_score(
            list(self._OBSERVE_TERMS),
            normalized_text,
            exact_score=0.82,
        )

    def _best_term_score(
        self,
        terms: list[str],
        normalized_text: str,
        *,
        exact_score: float,
    ) -> float:
        best = 0.0
        for term in terms:
            normalized_term = self._normalize_text(term)
            if not normalized_term:
                continue
            if normalized_text == normalized_term:
                best = max(best, exact_score)
            elif normalized_term in normalized_text:
                best = max(best, exact_score - 0.15)
        return best

    def _accepted(
        self,
        *,
        player_id: str,
        raw_text: str,
        match: _Match,
    ) -> NormalizedIntentResult:
        if match.kind == "move":
            payload: dict[str, object] = {
                "type": "move",
                "target_scene_id": match.item_id,
            }
        elif match.kind == "action":
            payload = {"type": "action", "action_id": match.item_id}
        else:
            payload = {"type": "observe", "text": raw_text}
        return NormalizedIntentResult(
            player_id=player_id,
            raw_text=raw_text,
            accepted=True,
            intent_payload=payload,
            confidence=match.confidence,
            matched_kind=match.kind,
            matched_id=match.item_id,
            candidates=[match.label],
        )

    def _clarify(
        self,
        *,
        player_id: str,
        raw_text: str,
        question: str,
        candidates: list[str],
    ) -> NormalizedIntentResult:
        return NormalizedIntentResult(
            player_id=player_id,
            raw_text=raw_text,
            accepted=False,
            clarification_question=question,
            candidates=candidates,
        )

    def _available_labels(
        self,
        *,
        runtime: "SceneRuntime",
        session: SessionMapState,
        module: ModuleDefinition,
        player_id: str,
    ) -> list[str]:
        scene_map = module.scene_map()
        move_labels = [
            f"移动到「{scene_map[scene_id].name}」"
            for scene_id in runtime.list_reachable_scenes(session, player_id)
        ]
        action_labels = [
            f"执行「{action.name}」"
            for action in runtime.list_available_actions(session, player_id)
        ]
        return [*move_labels, *action_labels, "观察当前环境"]

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", "", text).lower()
