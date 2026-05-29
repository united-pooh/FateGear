"""自然语言意图归一化模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RawPlayerIntent(BaseModel):
    player_id: str = Field(..., min_length=1, max_length=30)
    text: str = Field(..., min_length=1, max_length=500)


class NormalizedIntentResult(BaseModel):
    player_id: str
    raw_text: str
    accepted: bool = False
    intent_payload: dict[str, object] | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    matched_kind: str = ""
    matched_id: str = ""
    clarification_question: str = ""
    candidates: list[str] = Field(default_factory=list)
