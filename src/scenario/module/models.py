"""YAML 模组静态定义模型。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .types import ModuleCondition, ModuleEffect
from ..story.models import StoryStage, StoryTransition

# ModuleKTSLSpec is needed at runtime for pydantic model_rebuild() to resolve
# the forward-ref field on ModuleDefinition.  No circular-import risk since
# ktsl.models does not import this module.
from ..ktsl.models import ModuleKTSLSpec  # noqa: F401 — pydantic forward-ref resolution

NarrativeVisibility = Literal["public", "keeper"]


class ModuleScene(BaseModel):
    id: str = Field(..., min_length=1, max_length=30)
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=10)


class ModuleLink(BaseModel):
    id: str = Field(..., min_length=1, max_length=40)
    from_scene_id: str = Field(..., min_length=1, max_length=30)
    to_scene_id: str = Field(..., min_length=1, max_length=30)
    required_flags: list[str] = Field(default_factory=list, max_length=10)
    required_stages: list[str] = Field(default_factory=list, max_length=10)
    block_reason: str = Field(default="", max_length=200)


class ClockThresholdEvent(BaseModel):
    value: int = Field(..., ge=0)
    effects: list[ModuleEffect] = Field(default_factory=list)


class ModuleClock(BaseModel):
    id: str = Field(..., min_length=1, max_length=40)
    start: int = Field(default=0, ge=0)
    max_value: int = Field(default=10, ge=0)
    step_per_turn: int = Field(default=1, ge=0)
    threshold_events: list[ClockThresholdEvent] = Field(default_factory=list)


ActionCheckDifficulty = Literal["regular", "hard", "extreme"]


class ModuleActionCheck(BaseModel):
    # 加载期会用 cards 技能模板注册表做语义校验。
    skill_key: str = Field(..., min_length=1, max_length=50)
    difficulty: ActionCheckDifficulty = "regular"
    failure_reason: str = Field(default="检定失败", max_length=200)


class ModuleAction(BaseModel):
    id: str = Field(..., min_length=1, max_length=40)
    scene_id: str = Field(..., min_length=1, max_length=30)
    name: str = Field(..., min_length=1, max_length=100)
    kind: str = Field(..., min_length=1, max_length=30)
    description: str = Field(default="", max_length=500)
    aliases: list[str] = Field(default_factory=list, max_length=12)
    expected_inputs: list[str] = Field(default_factory=list, max_length=8)
    stakes: str = Field(default="", max_length=300)
    fail_forward_hint: str = Field(default="", max_length=300)
    once: bool = Field(default=True)
    required_stages: list[str] = Field(default_factory=list, max_length=10)
    conditions: list[ModuleCondition] = Field(default_factory=list)
    check: ModuleActionCheck | None = Field(default=None)
    effects_on_success: list[ModuleEffect] = Field(default_factory=list)
    effects_on_failure: list[ModuleEffect] = Field(default_factory=list)
    marks_scene_cleared: bool = Field(default=False)


class ModuleEnding(BaseModel):
    id: str = Field(..., min_length=1, max_length=40)
    scene_id: str = Field(..., min_length=1, max_length=30)
    conditions: list[ModuleCondition] = Field(default_factory=list)
    result: str = Field(..., min_length=1, max_length=200)


class ModuleNPC(BaseModel):
    """模组内可被 KP 上下文激活的 NPC 人设卡。"""

    id: str = Field(..., min_length=1, max_length=40)
    name: str = Field(..., min_length=1, max_length=100)
    role: str = Field(default="", max_length=100)
    public_description: str = Field(default="", max_length=800)
    persona: str = Field(default="", max_length=1000)
    speaking_style: str = Field(default="", max_length=500)
    goals: list[str] = Field(default_factory=list, max_length=10)
    knowledge_boundary: str = Field(default="", max_length=800)
    secrets: list[str] = Field(default_factory=list, max_length=10)
    relationships: dict[str, str] = Field(default_factory=dict)
    active_scene_ids: list[str] = Field(default_factory=list, max_length=20)
    active_stage_ids: list[str] = Field(default_factory=list, max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=20)
    visibility: NarrativeVisibility = "public"
    default_scene_id: str = Field(default="", max_length=30)
    characteristics: dict[str, int] = Field(default_factory=dict)
    skills: dict[str, int] = Field(default_factory=dict)


class ModuleLorebookEntry(BaseModel):
    """类似酒馆 World Info/Lorebook 的动态世界知识条目。"""

    id: str = Field(..., min_length=1, max_length=60)
    title: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1, max_length=1500)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    scope_scene_ids: list[str] = Field(default_factory=list, max_length=20)
    scope_stage_ids: list[str] = Field(default_factory=list, max_length=20)
    scope_action_ids: list[str] = Field(default_factory=list, max_length=20)
    npc_ids: list[str] = Field(default_factory=list, max_length=20)
    priority: int = Field(default=100, ge=0, le=1000)
    insertion_order: int = Field(default=100, ge=0, le=1000)
    enabled: bool = True
    always_on: bool = False
    visibility: NarrativeVisibility = "public"


class ModuleSafetyBoundary(BaseModel):
    """安全提示、敏感内容提示或硬性叙事边界。"""

    id: str = Field(..., min_length=1, max_length=60)
    note: str = Field(..., min_length=1, max_length=800)
    severity: Literal["note", "warning", "hard"] = "warning"
    scope_scene_ids: list[str] = Field(default_factory=list, max_length=20)
    scope_stage_ids: list[str] = Field(default_factory=list, max_length=20)


class ModuleAtmosphereProfile(BaseModel):
    """长期氛围、感官词库和张力推进规则。"""

    tone: str = Field(default="", max_length=200)
    sensory_palette: list[str] = Field(default_factory=list, max_length=12)
    pacing_hint: str = Field(default="", max_length=300)
    tension_axis: str = Field(default="", max_length=200)
    escalation_rules: list[str] = Field(default_factory=list, max_length=10)
    forbidden_reveals: list[str] = Field(default_factory=list, max_length=10)
    style_rules: list[str] = Field(default_factory=list, max_length=12)


class ModuleKPProseControls(BaseModel):
    """KP 叙事写法约束。"""

    language: str = Field(default="zh-CN", max_length=20)
    narrative_person: Literal["second", "third", "mixed"] = "second"
    tense: Literal["present", "past", "mixed"] = "present"
    paragraph_limit: int = Field(default=3, ge=1, le=8)
    horror_intensity: int = Field(default=3, ge=0, le=5)
    dice_visibility: Literal["hide_values", "summarize", "show_values"] = "hide_values"
    clue_fairness: str = Field(
        default="线索可以被遮蔽，但不能因为文风而失去可推理性。",
        max_length=300,
    )
    avoid_fourth_wall: bool = True
    style_rules: list[str] = Field(default_factory=list, max_length=12)


class ModuleNarrativeContext(BaseModel):
    """模组级只读叙事上下文配置。"""

    model_config = ConfigDict(validate_assignment=True)

    worldview_brief: str = Field(default="", max_length=1200)
    max_lore_entries: int = Field(default=6, ge=0, le=20)
    max_context_chars: int = Field(default=3000, ge=200, le=20000)
    npcs: list[ModuleNPC] = Field(default_factory=list)
    lorebook_entries: list[ModuleLorebookEntry] = Field(default_factory=list)
    safety_boundaries: list[ModuleSafetyBoundary] = Field(default_factory=list)
    atmosphere: ModuleAtmosphereProfile = Field(default_factory=ModuleAtmosphereProfile)
    prose_controls: ModuleKPProseControls = Field(default_factory=ModuleKPProseControls)


class ModuleDefinition(BaseModel):
    module_id: str = Field(..., min_length=1, max_length=30)
    title: str = Field(..., min_length=1, max_length=100)
    version: int = Field(default=1, ge=1)
    entry_scene_id: str = Field(..., min_length=1, max_length=30)
    entry_stage_id: str = Field(..., min_length=1, max_length=40)
    flags: list[str] = Field(default_factory=list)
    scenes: list[ModuleScene] = Field(default_factory=list)
    links: list[ModuleLink] = Field(default_factory=list)
    actions: list[ModuleAction] = Field(default_factory=list)
    clocks: list[ModuleClock] = Field(default_factory=list)
    story_stages: list[StoryStage] = Field(default_factory=list)
    story_transitions: list[StoryTransition] = Field(default_factory=list)
    endings: list[ModuleEnding] = Field(default_factory=list)
    narrative_context: ModuleNarrativeContext = Field(
        default_factory=ModuleNarrativeContext
    )

    # KTSL optional spec (loaded from module.yaml "ktsl_spec" block)
    ktsl_spec: Optional["ModuleKTSLSpec"] = Field(
        default=None,
        description="可选的 KTSL 协议规范；运行 wizard 时优先使用。",
    )

    def scene_map(self) -> dict[str, ModuleScene]:
        return {scene.id: scene for scene in self.scenes}

    def link_map(self) -> dict[str, ModuleLink]:
        return {link.id: link for link in self.links}

    def action_map(self) -> dict[str, ModuleAction]:
        return {action.id: action for action in self.actions}

    def clock_map(self) -> dict[str, ModuleClock]:
        return {clock.id: clock for clock in self.clocks}

    def story_stage_map(self) -> dict[str, StoryStage]:
        return {stage.id: stage for stage in self.story_stages}

    def npc_map(self) -> dict[str, ModuleNPC]:
        return {npc.id: npc for npc in self.narrative_context.npcs}

    def lorebook_entry_map(self) -> dict[str, ModuleLorebookEntry]:
        return {entry.id: entry for entry in self.narrative_context.lorebook_entries}


# Resolve forward refs for ModuleDefinition (ModuleKTSLSpec is a forward-ref).
ModuleDefinition.model_rebuild()
