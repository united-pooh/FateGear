"""叙事上下文选择结果模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SelectedNPCContext(BaseModel):
    npc_id: str
    name: str
    role: str = ""
    public_description: str = ""
    persona: str = ""
    speaking_style: str = ""
    goals: list[str] = Field(default_factory=list)
    knowledge_boundary: str = ""
    secrets: list[str] = Field(default_factory=list)
    visibility: str = "public"
    selection_reason: str = ""


class SelectedLorebookEntry(BaseModel):
    entry_id: str
    title: str
    content: str
    visibility: str = "public"
    priority: int = 100
    insertion_order: int = 100
    selection_reason: str = ""
    scope_action_ids: list[str] = Field(default_factory=list)


class SelectedSafetyBoundary(BaseModel):
    boundary_id: str
    note: str
    severity: str = "warning"
    selection_reason: str = ""


class SelectedAtmosphereContext(BaseModel):
    tone: str = ""
    sensory_palette: list[str] = Field(default_factory=list)
    pacing_hint: str = ""
    tension_axis: str = ""
    escalation_rules: list[str] = Field(default_factory=list)
    forbidden_reveals: list[str] = Field(default_factory=list)
    style_rules: list[str] = Field(default_factory=list)


class SelectedProseControls(BaseModel):
    language: str = "zh-CN"
    narrative_person: str = "second"
    tense: str = "present"
    paragraph_limit: int = 3
    horror_intensity: int = 3
    dice_visibility: str = "hide_values"
    clue_fairness: str = "线索可以被遮蔽，但不能因为文风而失去可推理性。"
    avoid_fourth_wall: bool = True
    style_rules: list[str] = Field(default_factory=list)


class NarrativeContextLayer(BaseModel):
    """选中的只读叙事上下文。"""

    worldview_brief: str = ""
    selected_npcs: list[SelectedNPCContext] = Field(default_factory=list)
    selected_lorebook_entries: list[SelectedLorebookEntry] = Field(
        default_factory=list
    )
    selected_safety_boundaries: list[SelectedSafetyBoundary] = Field(
        default_factory=list
    )
    atmosphere: SelectedAtmosphereContext = Field(
        default_factory=SelectedAtmosphereContext
    )
    prose_controls: SelectedProseControls = Field(default_factory=SelectedProseControls)
    selected_ids: list[str] = Field(default_factory=list)
    skipped_ids: dict[str, str] = Field(default_factory=dict)
    budget_used_chars: int = 0
    max_context_chars: int = 3000
    channel: str = "keeper"

    def has_content(self) -> bool:
        return bool(
            self.worldview_brief
            or self.selected_npcs
            or self.selected_lorebook_entries
            or self.selected_safety_boundaries
            or self.atmosphere.tone
            or self.atmosphere.sensory_palette
            or self.prose_controls.style_rules
        )
