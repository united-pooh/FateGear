# KTSL 运行时集成实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 KTSL 协议从"离线 fixture oracle"升级为嵌入 SceneRuntime 回合结算管线的"运行时防线"，补齐论文四类缺失组件(KP 语言细则 / 一页式 KP 清单 / 最小数据模板 / 评估标注手册)。

**Architecture:** 引入 `TurnStage` 协议和 `KTSLLedger`（SessionMapState 的一等公民），将 `_resolve_turn_locked` 重构为可插拔的 stage pipeline；KTSL 三层检查(Model/Coupling/Filter)和论文四类组件作为 stage 插件按需启用；PromptBuilder 扩展注入 KTSL 上下文到 Plan/Render agent，不改变现有 agent 接口。

**Tech Stack:** Python 3.12+, Pydantic v2, aiohttp(现有), pytest, arrow(时间), rich(终端输出)。

---

## File Structure

### Created

| Path | Responsibility |
|---|---|
| `src/scenario/ktsl/stage_context.py` | StageContext / StageResult / KTSLIntervention |
| `src/scenario/ktsl/stages.py` | WizardStage / SubmitCheckStage / ScheduleGateStage / FilterStage / CouplingDriftStage / AuditStage |
| `src/scenario/ktsl/prompt_adapter.py` | KTSLPromptAdapter (读 ledger，写 prompt 片段) |
| `src/scenario/ktsl/prompt_templates/__init__.py` | KP 语言细则四类模板 |
| `src/scenario/ktsl/prompt_templates/redaction.py` | redaction 模板：高敏 info 被过滤时的叙事话术 |
| `src/scenario/ktsl/prompt_templates/grayzone.py` | 灰区处理模板 |
| `src/scenario/ktsl/prompt_templates/broadcast.py` | 公开广播叙述模板 |
| `src/scenario/ktsl/prompt_templates/private_note.py` | 私有笔记模板 |
| `src/scenario/ktsl/wizard.py` | ktsl wizard 交互式准备流程 |
| `src/scenario/ktsl/log_writer.py` | 每回合落盘决策 bundle 到 log/session/{id}/ktsl/ |
| `src/scenario/report/analyst_renderer.py` | CLI 终端表格 + focus 过滤 |
| `tests/scene/ktsl/fixtures/runtime_bridge.py` | 运行时集成测试共用的 fixture 工厂 |

### Modified

| Path | Change |
|---|---|
| `src/scenario/ktsl/models.py` | 新增 KTSLLedger / KTSLOverrideRecord / KTSLPromptTemplateSet / ModuleKTSLSpec 模型 |
| `src/scenario/session/state.py` | SessionMapState 新增 `ktsl_ledger: Optional[KTSLLedger]` 字段；新增 KTSLInterventionLogEvent |
| `src/scenario/module/models.py` | ModuleDefinition 新增 `ktsl_spec: Optional[ModuleKTSLSpec]` 字段 |
| `src/scenario/agent/models.py` | AgentPlanPrompt 新增可选 `ktsl_context` 字段；CommitResult 新增 `ktsl_filter_decisions` |
| `src/scenario/agent/prompt_builder.py` | build() 末尾注入 KTSL 段落（仅在 ledger 存在时） |
| `src/scenario/runtime/engine.py` | submit_intent 追加 SubmitCheckStage 调用；_resolve_turn_locked 重构为 stage pipeline；新增 KTSL 事件类型到 RuntimeEvent |
| `src/scenario/cli/ktsl_cli.py` | 新增 wizard / override / analyst 子命令 |
| `src/scenario/runtime/contracts.py` | RuntimeEvent.type Literal 新增 ktsl 事件枚举 |

---

## Milestone 1 — Wizard + Schema 校验 + Ledger 持久化

### Task 1: 在 models.py 中新增 KTSLLedger 数据模型

**Files:**
- Create: `src/scenario/ktsl/models.py` (追加)
- Test: `tests/scene/ktsl/test_ledger_model.py`

- [ ] **Step 1: 确认测试**

新建 `tests/scene/ktsl/test_ledger_model.py`，写入：

```python
"""Tests for KTSLLedger data model."""
from __future__ import annotations
import pytest
from scenario.ktsl.models import KTSLLedger


class TestKTSLLedgerEmpty:
    def test_empty_ledger_has_no_scenes(self) -> None:
        ledger = KTSLLedger.empty(module_id="test_mod")
        assert ledger.scenes == {}
        assert ledger.events == []
        assert ledger.module_id == "test_mod"

    def test_empty_ledger_snapshot_is_stable(self) -> None:
        ledger = KTSLLedger.empty(mod="m")
        snap = ledger.snapshot()
        assert snap["module_id"] == "m"
        assert snap["committed_count"] == 0
```

- [ ] **Step 2: 执行测试确认红**

```bash
cd /Users/united_pooh/PycharmProjects/FateGear && \
  PYTHONPATH=src python -m pytest tests/scene/ktsl/test_ledger_model.py -v
```
预期：FAIL，`KTSLLedger` 未定义。

- [ ] **Step 3: 实现**

编辑 `src/scenario/ktsl/models.py`，在文件末尾（`__all__` 列表之后）追加：

```python
# ---------------------------------------------------------------------------
# Milestone 1: Runtime Ledger
# ---------------------------------------------------------------------------


class KTSLOverrideRecord(BaseModel):
    """Immutable record of a KP override on a blocked intervention."""

    id: str = Field(..., min_length=1, max_length=80)
    intervention_id: str = Field(..., min_length=1, max_length=80)
    override_type: Literal["force_allow", "force_block", "declassify"]
    reason: str = Field(..., min_length=1, max_length=600)
    kp_name: str = Field(default="", max_length=60)
    created_at: str = Field(default="")


class KTSLPromptTemplateRef(BaseModel):
    """Reference to a named prompt template + its populated variables."""

    template_name: str = Field(..., min_length=1, max_length=60)
    variables: dict[str, str] = Field(default_factory=dict)


class KTSLPromptTemplateSet(BaseModel):
    """Bundle of prompt template overrides for a session."""

    broadcast_narration: str = Field(default="", max_length=2000)
    private_note: str = Field(default="", max_length=2000)
    redaction_notice: str = Field(default="", max_length=2000)
    grayzone_guidance: str = Field(default="", max_length=2000)


class ModuleSceneKTSLSpec(BaseModel):
    scene_id: str = Field(..., min_length=1, max_length=60)
    initial_mode: CouplingMode = "independent"
    participant_character_ids: list[str] = Field(default_factory=list)
    participant_player_ids: list[str] = Field(default_factory=list)
    time_start_minute: int = Field(default=0, ge=0)
    time_end_minute: int = Field(default=0, ge=0)
    spotlight_start_minute: int = Field(default=0, ge=0)
    spotlight_end_minute: int = Field(default=0, ge=0)
    tags: list[str] = Field(default_factory=list)


class ModuleInfoLabelSpec(BaseModel):
    info_id: str = Field(..., min_length=1, max_length=80)
    payload: str = Field(..., min_length=1, max_length=2000)
    sensitivity: SensitivityLevel = "public"
    public_payload: str = Field(default="", max_length=1200)
    redaction: str = Field(default="", max_length=1200)
    known_by_character_ids: list[str] = Field(default_factory=list)
    authorized_character_ids: list[str] = Field(default_factory=list)
    declassification_condition: str = Field(default="", max_length=500)


class ModuleCouplingSpec(BaseModel):
    source_scene_id: str
    target_scene_id: str
    condition_type: ConditionType = "none"
    required_info_ids: list[str] = Field(default_factory=list)
    required_scene_ids: list[str] = Field(default_factory=list)
    barrier_policy: Literal["none", "soft", "hard"] = "none"
    rationale: str = Field(default="", max_length=600)


class ModuleInitialKnowledgeSpec(BaseModel):
    character_id: str = Field(..., min_length=1, max_length=60)
    known_info_ids: list[str] = Field(default_factory=list)
    observed_info_ids: list[str] = Field(default_factory=list)
    authorized_info_ids: list[str] = Field(default_factory=list)


class ModuleKTSLSpec(BaseModel):
    """Optional ktsl_spec block in a module.yaml, consumed by WizardStage."""

    scenes: list[ModuleSceneKTSLSpec] = Field(default_factory=list)
    info_labels: list[ModuleInfoLabelSpec] = Field(default_factory=list)
    couplings: list[ModuleCouplingSpec] = Field(default_factory=list)
    initial_knowledge: list[ModuleInitialKnowledgeSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_coupling_refs(self) -> "ModuleKTSLSpec":
        scene_ids = {s.scene_id for s in self.scenes}
        for coupling in self.couplings:
            if coupling.source_scene_id not in scene_ids:
                raise ValueError(
                    f"coupling source_scene_id {coupling.source_scene_id!r} "
                    f"not in scenes"
                )
            if coupling.target_scene_id not in scene_ids:
                raise ValueError(
                    f"coupling target_scene_id {coupling.target_scene_id!r} "
                    f"not in scenes"
                )
            for info_id in coupling.required_info_ids:
                if not any(il.info_id == info_id for il in self.info_labels):
                    raise ValueError(
                        f"coupling required_info_id {info_id!r} not in info_labels"
                    )
        return self


class KTSLLedger(BaseModel):
    """First-class ledger living inside SessionMapState."""

    module_id: str = Field(..., min_length=1, max_length=30)
    scenes: dict[str, SceneCard] = Field(default_factory=dict)
    events: list[EventRecord] = Field(default_factory=list)
    info_labels: dict[str, InfoLabel] = Field(default_factory=dict)
    couplings: list[SceneCoupling] = Field(default_factory=list)
    knowledge: dict[str, ActorKnowledgeState] = Field(default_factory=dict)
    overrides: list[KTSLOverrideRecord] = Field(default_factory=list)
    narration_rules: KTSLPromptTemplateSet = Field(
        default_factory=KTSLPromptTemplateSet
    )

    @classmethod
    def empty(cls, module_id: str) -> "KTSLLedger":
        return cls(module_id=module_id)

    @classmethod
    def from_module_spec(
        cls,
        module_id: str,
        spec: ModuleKTSLSpec,
    ) -> "KTSLLedger":
        scenes = {
            s.scene_id: SceneCard(
                id=s.scene_id,
                name=s.scene_id,
                location_id=s.scene_id,
                participant_character_ids=list(s.participant_character_ids),
                participant_player_ids=list(s.participant_player_ids),
                time_start_minute=s.time_start_minute,
                time_end_minute=s.time_end_minute,
                spotlight_start_minute=s.spotlight_start_minute,
                spotlight_end_minute=s.spotlight_end_minute,
                tags=list(s.tags),
            )
            for s in spec.scenes
        }
        info_labels = {
            info.info_id: InfoLabel(
                id=info.info_id,
                kind="know",
                scene_id=info.info_id,
                payload=info.payload,
                sensitivity=info.sensitivity,
                public_payload=info.public_payload,
                redaction=info.redaction,
                known_by_character_ids=list(info.known_by_character_ids),
                authorized_character_ids=list(info.authorized_character_ids),
            )
            for info in spec.info_labels
        }
        couplings = [
            SceneCoupling(
                id=f"coupling_{c.source_scene_id}_{c.target_scene_id}",
                source_scene_id=c.source_scene_id,
                target_scene_id=c.target_scene_id,
                condition_type=c.condition_type,
                required_info_ids=list(c.required_info_ids),
                required_scene_ids=list(c.required_scene_ids),
                barrier_policy=c.barrier_policy,
                rationale=c.rationale,
            )
            for c in spec.couplings
        ]
        knowledge = {
            k.character_id: ActorKnowledgeState(
                character_id=k.character_id,
                known_info_ids=list(k.known_info_ids),
                observed_info_ids=list(k.observed_info_ids),
                authorized_info_ids=list(k.authorized_info_ids),
            )
            for k in spec.initial_knowledge
        }
        return cls(
            module_id=module_id,
            scenes=scenes,
            info_labels=info_labels,
            couplings=couplings,
            knowledge=knowledge,
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "module_id": self.module_id,
            "scene_ids": sorted(self.scenes),
            "committed_count": sum(1 for e in self.events if e.committed),
            "pending_count": sum(1 for e in self.events if not e.committed),
            "info_count": len(self.info_labels),
            "coupling_count": len(self.couplings),
            "override_count": len(self.overrides),
        }

    def commit_event(self, event: EventRecord) -> None:
        """Append and mark committed."""
        event.committed = True
        event.status = "committed"
        self.events.append(event)

    def apply_override(self, record: KTSLOverrideRecord) -> None:
        self.overrides.append(record)


# ---------------------------------------------------------------------------
# Update __all__ to include new exports
# ---------------------------------------------------------------------------

__all__ += [
    "KTSLOverrideRecord",
    "KTSLPromptTemplateRef",
    "KTSLPromptTemplateSet",
    "ModuleSceneKTSLSpec",
    "ModuleInfoLabelSpec",
    "ModuleCouplingSpec",
    "ModuleInitialKnowledgeSpec",
    "ModuleKTSLSpec",
    "KTSLLedger",
]
```

- [ ] **Step 4: 执行测试确认绿**

```bash
cd /Users/united_pooh/PycharmProjects/FateGear && \
  PYTHONPATH=src python -m pytest tests/scene/ktsl/test_ledger_model.py -v
```
预期：PASS。

- [ ] **Step 5: Commit**

```bash
cd /Users/united_pooh/PycharmProjects/FateGear && \
  git add src/scenario/ktsl/models.py tests/scene/ktsl/test_ledger_model.py && \
  git commit -m "feat(ktsl): add KTSLLedger model and Milestone 1 data contracts"
```

---

### Task 2: KTSLLedger 关联到 SessionMapState 并持久化

**Files:**
- Modify: `src/scenario/session/state.py:233` (SessionMapState 字段区)
- Modify: `src/scenario/module/models.py:174` (ModuleDefinition)
- Test: `tests/scene/ktsl/test_session_state_ledger.py`

- [ ] **Step 1: 确认测试**

```python
# tests/scene/ktsl/test_session_state_ledger.py
from __future__ import annotations
import pytest
from scenario.session.state import SessionMapState, SessionPlayerState
from scenario.ktsl.models import KTSLLedger
from scenario.story.models import StoryState  # 实际视 import 路径调整
from scenario.scene.models import Scene, ModuleLink  # 用于创建 ModuleDefinition


class TestSessionMapStateKTSLFields:
    def test_ktsl_ledger_field_exists_and_defaults_none(self) -> None:
        session = SessionMapState(
            session_id="s1",
            module_id="m1",
            current_turn=1,
            story_state=StoryState(current_stage_id="stage_1"),  # 看实际构造
            player_states={},
        )
        assert session.ktsl_ledger is None

    def test_ktsl_ledger_can_be_attached(self) -> None:
        ledger = KTSLLedger.empty(module_id="m1")
        session = SessionMapState(
            session_id="s1",
            module_id="m1",
            current_turn=1,
            story_state=StoryState(current_stage_id="stage_1"),
            player_states={},
            ktsl_ledger=ledger,
        )
        assert session.ktsl_ledger is not None
        assert session.ktsl_ledger.module_id == "m1"

    def test_ledger_survives_model_copy(self) -> None:
        ledger = KTSLLedger.empty(module_id="m1")
        session = SessionMapState(
            session_id="s1",
            module_id="m1",
            current_turn=1,
            story_state=StoryState(current_stage_id="stage_1"),
            player_states={},
            ktsl_ledger=ledger,
        )
        snap = session.model_copy(deep=True)
        assert snap.ktsl_ledger is not None
        assert snap.ktsl_ledger.module_id == "m1"
```

注意：`StoryState` 的实际构造视代码调整；如无 `current_stage_id` 字段就改成对应字段。

- [ ] **Step 2: 执行测试确认红**

```bash
cd /Users/united_pooh/PycharmProjects/FateGear && \
  PYTHONPATH=src python -m pytest tests/scene/ktsl/test_session_state_ledger.py -v
```
预期：FAIL（`ktsl_ledger` 不是 `SessionMapState` 字段）。

- [ ] **Step 3: 实现**

**修改 `src/scenario/module/models.py`**：
在 `ModuleDefinition` 类末尾追加字段：

```python
# KTSL optional spec (loaded from module.yaml "ktsl_spec" block)
ktsl_spec: Optional["ModuleKTSLSpec"] = Field(
    default=None,
    description="可选的 KTSL 协议规范；运行 wizard 时优先使用。",
)
```
并在文件顶部从 `scenario.ktsl.models` 导入 `ModuleKTSLSpec`，或直接用 `from __future__ import annotations` + 字符串引用。

**修改 `src/scenario/session/state.py`**：
在 `SessionMapState` 字段区末尾（`npc_patch_queue` 之后）追加：

```python
# KTSL runtime ledger — None 表示本场游戏不使用 KTSL 协议
ktsl_ledger: Optional["KTSLLedger"] = Field(
    default=None,
    description="KTSL 运行时账本；None 表示本场游戏不启用 KTSL 协议。",
)
```

- [ ] **Step 4: 执行测试确认绿**

```bash
cd /Users/united_pooh/PycharmProjects/FateGear && \
  PYTHONPATH=src python -m pytest tests/scene/ktsl/test_session_state_ledger.py -v
```
预期：PASS。

- [ ] **Step 5: Commit**

```bash
git add src/scenario/session/state.py src/scenario/module/models.py \
        tests/scene/ktsl/test_session_state_ledger.py && \
git commit -m "feat(ktsl): attach KTSLLedger to SessionMapState + ModuleDefinition"
```

---

### Task 3: SchemaValidatorStage 校验 module yaml 的 ktsl_spec

**Files:**
- Create: `src/scenario/ktsl/stage_context.py` (StageContext / StageResult / KTSLIntervention)
- Create: `src/scenario/ktsl/stages.py` (SchemaValidatorStage + WizardStage 存根)
- Test: `tests/scene/ktsl/test_schema_validator_stage.py`

- [ ] **Step 1: 确认测试**

```python
# tests/scene/ktsl/test_schema_validator_stage.py
from __future__ import annotations
import pytest
from scenario.ktsl.models import (
    ModuleKTSLSpec, ModuleSceneKTSLSpec, ModuleInfoLabelSpec,
    ModuleCouplingSpec, ModuleInitialKnowledgeSpec,
)
from scenario.ktsl.stages import SchemaValidatorStage


class TestSchemaValidatorStage:
    def test_passes_when_spec_is_complete(self) -> None:
        spec = ModuleKTSLSpec(
            scenes=[ModuleSceneKTSLSpec(scene_id="library")],
            info_labels=[
                ModuleInfoLabelSpec(
                    info_id="I01", payload="a clue", sensitivity="high"
                )
            ],
            initial_knowledge=[
                ModuleInitialKnowledgeSpec(
                    character_id="P1",
                    known_info_ids=["I01"],
                )
            ],
        )
        stage = StageValidatorStage=SchemaValidatorStage()
        result = stage.validate(spec)  # 返回 ValidationReport
        assert result.is_valid
        assert not result.issues

    def test_fails_when_high_sens_has_no_redaction(self) -> None:
        spec = ModuleKTSLSpec(
            scenes=[ModuleSceneKTSLSpec(scene_id="library")],
            info_labels=[
                ModuleInfoLabelSpec(
                    info_id="I01", payload="secret", sensitivity="high",
                    redaction=""  # <-- 缺失
                )
            ],
        )
        stage = SchemaValidatorStage()
        result = stage.validate(spec)
        assert not result.is_valid
        assert any(i["field"] == "info_labels.I01.redaction" for i in result.issues)

    def test_fails_when_scene_has_no_participants(self) -> None:
        spec = ModuleKTSLSpec(
            scenes=[ModuleSceneKTSLSpec(scene_id="library",
                                       participant_character_ids=[])],
        )
        stage = SchemaValidatorStage()
        result = stage.validate(spec)
        assert not result.is_valid
        assert any("participant" in i["field"] for i in result.issues)
```

- [ ] **Step 2: 执行测试确认红**

```bash
cd /Users/united_pooh/PycharmProjects/FateGear && \
  PYTHONPATH=src python -m pytest tests/scene/ktsl/test_schema_validator_stage.py -v
```
预期：FAIL（`stages.py` 未创建）。

- [ ] **Step 3: 实现**

**新建 `src/scenario/ktsl/stage_context.py`**：

```python
"""TurnStage protocol and shared context types."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional, Protocol

from pydantic import BaseModel, Field


class KTSLIntervention(Enum):
    ALLOW = "allow"
    REDACT = "redact"
    BLOCK = "block"


class StageResult(BaseModel):
    status: Literal["continue", "blocked", "wait"] = "continue"
    interventions: list[Any] = Field(default_factory=list)

    def to_events(self) -> list[Any]:
        return []  # 子类 override


class StageContext:
    """Mutable context running through one resolution turn."""

    def __init__(self, snapshot: Any, ledger: Any, event_log: list[Any]) -> None:
        self.snapshot = snapshot
        self.ledger = ledger
        self.event_log = event_log
        self.scene: Any = None
        self.intents: list[tuple[str, dict[str, object]]] = []
        self.scratch: dict[str, Any] = {}

    def commit_scratch_to_ledger(self) -> None:
        """Write scratch-prefixed keys into ledger."""
        for key, value in self.scratch.items():
            if key.startswith("commit_"):
                target = key[len("commit_"):]
                if target == "events" and isinstance(value, list):
                    for event in value:
                        self.ledger.commit_event(event)

    def mark_blocked(self, interventions: list[Any]) -> None:
        self.scratch.setdefault("blocked_interventions", []).extend(interventions)
```

**新建 `src/scenario/ktsl/stages.py`**：

```python
"""Turn stage implementations used by the KTSL pipeline."""
from __future__ import annotations

from typing import Any

from .models import ModuleKTSLSpec, InfoLabel


class SchemaValidationIssue(BaseModel):
    field: str
    message: str
    severity: Literal["error", "warning"] = "error"


class SchemaValidationReport(BaseModel):
    is_valid: bool
    issues: list[SchemaValidationIssue] = Field(default_factory=list)


class SchemaValidatorStage:
    """Validates a ModuleKTSLSpec for required fields and contradictions."""

    def validate(self, spec: ModuleKTSLSpec) -> SchemaValidationReport:
        issues: list[SchemaValidationIssue] = []

        for info in spec.info_labels:
            if info.sensitivity in {"medium", "high", "keeper"} and not info.redaction:
                issues.append(
                    SchemaValidationIssue(
                        field=f"info_labels.{info.info_id}.redaction",
                        message=f"Sensitive info '{info.info_id}' requires redaction text.",
                    )
                )
            if info.sensitivity in {"high", "keeper"} and not info.public_payload:
                issues.append(
                    SchemaValidationIssue(
                        field=f"info_labels.{info.info_id}.public_payload",
                        message=f"High-sensitivity info '{info.info_id}' needs a public_payload.",
                    )
                )

        for scene in spec.scenes:
            if not scene.participant_character_ids:
                issues.append(
                    SchemaValidationIssue(
                        field=f"scenes.{scene.scene_id}.participant_character_ids",
                        message=f"Scene '{scene.scene_id}' has no participants.",
                    )
                )

        return SchemaValidationReport(is_valid=not issues, issues=issues)
```

- [ ] **Step 4: 执行测试确认绿**

```bash
cd /Users/united_pooh/PycharmProjects/FateGear && \
  PYTHONPATH=src python -m pytest tests/scene/ktsl/test_schema_validator_stage.py -v
```
预期：PASS。

- [ ] **Step 5: Commit**

```bash
git add src/scenario/ktsl/stage_context.py src/scenario/ktsl/stages.py \
        tests/scene/ktsl/test_schema_validator_stage.py && \
git commit -m "feat(ktsl): add SchemaValidatorStage with field-level validation"
```

---

### Task 4: ktsl wizard 交互式终端

**Files:**
- Create: `src/scenario/ktsl/wizard.py`
- Test: `tests/scene/ktsl/test_wizard.py`

本 task 过长，此处只列出骨架；完整代码在后续 subagent dispatch 中展开。

**关键原则**：
- `WizardSession` 持有 `ModuleKTSLSpec` 中间态，支持 `--skip` 跳过某步
- 步骤 ① scenes → ② info_labels → ③ couplings → ④ initial_knowledge → ⑤ validate → ⑥ 写盘
- 最终调用 `KTSLLedger.from_module_spec(module_id, spec)` 产出 ledger JSON

**Steps** 缩略：
- Step 1: 写测试 `test_wizard_happy_path` 测试从 fixture + fixture yaml 出发的完整流程
- Step 2: 确认红
- Step 3: 实现 `WizardSession`：包括 `_step_scenes`, `_step_info_labels`, `_step_couplings`, `_step_initial_knowledge`, `_step_validate`, `_step_write_ledger`
- Step 4: 确认绿
- Step 5: commit

（完整代码由 subagent 按上述接口在 dispatch 实现）

---

### Task 5: M1 闸门集成测试（Paper fixture → ledger round-trip）

**Files:**
- Create: `tests/scene/ktsl/test_m1_gate.py`

```python
"""M1 gate: paper fixture converts into a valid KTSLLedger and persists."""
from __future__ import annotations
import json
import pytest
from scenario.ktsl.fixtures import build_library_sewer_church_fixture
from scenario.ktsl.models import KTSLLedger, ModuleKTSLSpec, ModuleSceneKTSLSpec
from scenario.ktsl.wizard import build_spec_from_fixture  # M1 helper


class TestM1Gate:
    def test_paper_fixture_converts_to_ledger(self) -> None:
        fixture = build_library_sewer_church_fixture()
        spec = build_spec_from_fixture(fixture)
        ledger = KTSLLedger.from_module_spec(
            module_id="paper_library_sewer_church", spec=spec
        )
        assert "library" in ledger.scenes
        assert "sewer" in ledger.scenes
        assert "church" in ledger.scenes

    def test_ledger_serializes_to_json(self, tmp_path) -> None:
        fixture = build_library_sewer_church_fixture()
        spec = build_spec_from_fixture(fixture)
        ledger = KTSLLedger.from_module_spec(module_id="m", spec=spec)
        out = tmp_path / "ledger.json"
        out.write_text(ledger.model_dump_json())
        loaded = KTSLLedger.model_validate_json(out.read_text())
        assert len(loaded.scenes) == len(ledger.scenes)

    def test_schema_validator_passes_clean_spec(self) -> None:
        fixture = build_library_sewer_church_fixture()
        spec = build_spec_from_fixture(fixture)
        from scenario.ktsl.stages import SchemaValidatorStage
        stage = SchemaValidatorStage()
        report = stage.validate(spec)
        assert report.is_valid, f"issues={report.issues}"
```

- Step 1–2 cycle 后跟进完整实现由 subagent 处理。
- Step 5 的 commit message: `"test(ktsl): M1 gate — paper fixture → ledger round-trip"`

---

## Milestone 2 — Submit 拦截

### Task 6: submit_intent 末尾挂钩 SubmitCheckStage

**Files:**
- Modify: `src/scenario/runtime/engine.py:318` (`submit_intent`)
- Modify: `src/scenario/ktsl/stages.py` (追加 `SubmitCheckStage`)
- Test: `tests/scene/ktsl/test_submit_check_stage.py`

- [ ] **Step 1: 确认测试**

```python
# tests/scene/ktsl/test_submit_check_stage.py
from __future__ import annotations
import pytest
from scenario.ktsl.fixtures import build_library_sewer_church_fixture
from scenario.ktsl.models import KTSLLedger, ModuleKTSLSpec
from scenario.ktsl.stages import SubmitCheckStage
from scenario.runtime_event import RuntimeEventAdapter


class TestSubmitCheckStage:
    def setup_method(self) -> None:
        fx = build_library_sewer_church_fixture()
        adapter = RuntimeEventAdapter(fx)
        self.stage = SubmitCheckStage(adapter=adapter)
        self.adapter = adapter

    def test_allows_simple_observation_in_scene(self) -> None:
        report = self.stage.check(
            action_text="search the archive",
            actor="P1",
            scene_id="library",
            committed_event_ids=set(),
            ledger_info_labels={},  # 空 ledger → 无 filter 拦截
        )
        assert report.status == "continue"
        assert not report.interventions

    def test_blocks_unknown_action_when_strict(self) -> None:
        """Unresolved action with strict mode blocks."""
        report = self.stage.check(
            action_text="recite the periodic table backwards",
            actor="P1",
            scene_id="library",
            committed_event_ids=set(),
            ledger_info_labels={},
            strict=True,
        )
        assert report.status == "blocked"
```

- [ ] **Step 2: 执行红**
- [ ] **Step 3: 实现 SubmitCheckStage**：

```python
# 在 src/scenario/ktsl/stages.py 中追加
class SubmitCheckResult(BaseModel):
    status: Literal["continue", "blocked"]
    interventions: list[SubmitIntervention] = Field(default_factory=list)
    parse_resolution: str = "unresolved"


class SubmitIntervention(BaseModel):
    actor: str
    reason_code: str
    reason: str


class SubmitCheckStage:
    """Parse + schedule + coupling intent pre-checks (no cross-player)."""

    def __init__(self, adapter: RuntimeEventAdapter) -> None:
        self._adapter = adapter

    def check(
        self,
        *,
        action_text: str,
        actor: str,
        scene_id: str,
        committed_event_ids: set[str],
        ledger_info_labels: dict[str, InfoLabel],
        strict: bool = False,
    ) -> SubmitCheckResult:
        parse = self._adapter.parse_action(
            action_text=action_text,
            actor=actor,
            scene_id=scene_id,
            committed_event_ids=committed_event_ids,
        )
        if parse.resolution == "unresolved":
            if strict:
                return SubmitCheckResult(
                    status="blocked",
                    interventions=[
                        SubmitIntervention(
                            actor=actor,
                            reason_code="unresolved_action",
                            reason="Action does not match any known clue or action schema.",
                        )
                    ],
                )
        return SubmitCheckResult(status="continue", parse_resolution=parse.resolution)
```

**修改 `submit_intent`（src/scenario/runtime/engine.py:318）**：

在 `session.pending_intents[player_id] = ...` 之前，插入：

```python
# KTSL M2 hook
if session.ktsl_ledger is not None:
    from scenario.ktsl.stages import SubmitCheckStage
    from scenario.runtime_event import RuntimeEventAdapter
    adapter = RuntimeEventAdapter(None)  # TODO M3: fixture → ledger
    check_stage = SubmitCheckStage(adapter=adapter)
    # 构造 SceneIntent 拿到 action_text
    ...
    # 若 blocked 则抛出 KTSLBlockError
```

（完整代码在 subagent dispatch 时按实际 import 路径实现）

- [ ] **Step 4: 绿**
- [ ] **Step 5: commit：`"feat(ktsl): submit_intent hooks SubmitCheckStage (M2)"`**

---

### Task 7: M2 端到端集成测试

**Files:**
- Create: `tests/scene/ktsl/test_m2_gate.py`

```python
"""M2 gate: runtime submit_intent blocked by SubmitCheckStage on unknown action."""
from __future__ import annotations
import pytest
from scenario.runtime.engine import SceneRuntime
from scenario.session.state import SessionMapState
from scenario.ktsl.models import KTSLLedger
from scenario.ktsl.fixtures import build_library_sewer_church_fixture


class TestM2Gate:
    def test_submit_blocked_when_strict(self, tmp_path) -> None:
        runtime = SceneRuntime(module_root=None, ...)
        # 构建含 ktsl_ledger 的 session
        # submit "recite periodic table" → 抛 KTSLBlockError
        pass  # 具体 fixture 由 subagent 按当前 session 构造补全
```

---

## Milestone 3 — resolve_turn_locked 管线切片

### Task 8: 在 contracts.py 新增 KTSL RuntimeEvent 类型

**Files:**
- Modify: `src/scenario/runtime/contracts.py:75-140`
- Test: `tests/scene/ktsl/test_runtime_event_types.py`

```python
# 在 RuntimeEvent.type Literal 列表追加
"ktsl_t扽_issued",        # KTSL 发出 BLOCK/REDACT/WAIT
"ktsl_override_applied",  # KP 裁量覆盖
"ktsl_audit_updated",     # 回合结算后 audit metrics 累加
```

- Step 1: 测试确认 Literal 接受新值
- Step 2: 红
- Step 3: 修改 Literal
- Step 4: 绿
- Step 5: commit

---

### Task 9: agent 模型扩展 — AgentPlanPrompt.ktsl_context + CommitResult.ktsl_filter_decisions

**Files:**
- Modify: `src/scenario/agent/models.py:185` (AgentPlanPrompt)
- Modify: `src/scenario/agent/models.py:305` (CommitResult)
- Test: `tests/scene/ktsl/test_agent_prompt_ktsl_fields.py

对 AgentPlanPrompt 追加：

```python
ktsl_context: Optional[Any] = Field(
    default=None,
    description="运行时注入的 KTSL 协议上下文（coupling/barrier/wait）；None 表示无 KTSL。",
)
```

对 CommitResult 追加：

```python
ktsl_filter_decisions: list[Any] = Field(
    default_factory=list,
    description="FilterLayer 对每个 character→info 访问的 REDACT/ALLOW 决策表。",
)
```

- Step 1–5 循环
- commit: `"feat(ktsl): AgentPlanPrompt/CommitResult carry ktsl_context fields"`

---

### Task 10: PromptBuilder.build() 末尾追加 KTSL 段落

**Files:**
- Modify: `src/scenario/agent/prompt_builder.py:130-150`
- Test: `tests/scene/ktsl/test_prompt_builder_ktsl.py`

Step 3 核心代码：

```python
# 在 PromptBuilder.build() 返回前追加
if session.ktsl_ledger is not None:
    from scenario.ktsl.prompt_adapter import KTSLPromptAdapter
    adapter = KTSLPromptAdapter()
    extras = adapter.build_plan_context(
        ledger=session.ktsl_ledger,
        scene=scene,
        intents=intent_map,
    )
    return AgentPlanPrompt(
        ...  # 现有字段,
        ktsl_context=extras,
    )
```

- commit: `"feat(ktsl): PromptBuilder injects ktsl_context section"`

---

### Task 11: KTSLPromptAdapter 完整实现

**Files:**
- Create: `src/scenario/ktsl/prompt_adapter.py`
- Test: `tests/scene/ktsl/test_prompt_adapter.py

```python
class KTSLPromptAdapter:
    def build_plan_context(self, ledger, scene, intents) -> dict[str, Any]:
        ...

    def build_render_context(self, ledger, decisions) -> dict[str, Any]:
        ...

    def build_redaction_notice(self, decision) -> str:
        ...
```

完整 spec 在 subagent dispatch 时展开。

- commit: `"feat(ktsl): KTSLPromptAdapter with plan/render/redaction contexts"`

---

### Task 12: resolve_turn_locked 重构为 stage pipeline

**Files:**
- Modify: `src/scenario/runtime/engine.py:392-1266`
- Test: `tests/scene/ktsl/test_resolve_stage_pipeline.py

**关键 Step 3 改动**：

```python
# SceneRuntime 追加注册器
def __init__(self, ...) -> None:
    ...
    self._ktsl_stages: list[Any] = []  # 默认空 pipeline

def register_ktsl_stages(self, stages: list[Any]) -> None:
    self._ktsl_stages = stages
```

```python
# 在 _resolve_turn_locked 的 scene loop 内追加
for stage in self._ktsl_stages:
    result = stage.run(ctx)
    event_log.extend(result.to_events())
    if result.status == "blocked":
        ctx.mark_blocked(result.interventions)
        break
ctx.commit_scratch_to_ledger()
```

- commit: `"feat(ktsl): resolve_turn_locked uses registered KTSL stage pipeline"`

---

### Task 13: ScheduleGate / Filter / CouplingDrift / Audit 四阶段实现

**Files:**
- Modify: `src/scenario/ktsl/stages.py`
- Test: `tests/scene/ktsl/test_all_stages.py

每个 stage 独立 Step 1–5 cycle。

- commit: `"feat(ktsl): complete KTSL stage suite (Schedule/Filter/Coupling/Audit)"`

---

### Task 14: 每回合决策日志落盘

**Files:**
- Create: `src/scenario/ktsl/log_writer.py`
- Modify: `src/scenario/runtime/engine.py` (resolve_turn_locked 末尾追加 log 调用)
- Test: `tests/scene/ktsl/test_log_writer.py

Step 3 核心：

```python
# resolve_turn_locked 末尾
if session.ktsl_ledger is not None:
    from scenario.ktsl.log_writer import KTSLLogWriter
    KTSLLogWriter.write_turn(
        session_id=session_id,
        turn_no=snapshot.current_turn,
        stage_trace=ctx.scratch.get("stage_trace", []),
        interventions=ctx.scratch.get("blocked_interventions", []),
        ...
    )
```

```python
# log/session/{session_id}/ktsl/{turn_no}/ 落盘规则
```

- commit: `"feat(ktsl): per-turn decision bundle writer"`

---

### Task 15: Analyst CLI 子命令

**Files:**
- Create: `src/scenario/report/analyst_renderer.py`
- Modify: `src/scenario/cli/ktsl_cli.py` (新增 `cmd_analyst`)
- Test: `tests/scene/ktsl/test_analyst_cli.py

```python
def cmd_analyst(args: argparse.Namespace) -> int:
    """终端输出 KTSL 决策审计表。"""
    session_id = args.session_id
    log_root = KTSLLogWriter.log_dir(session_id)
    ...
```

```bash
ktsl analyst S002 --turn 3
ktsl analyst S002 --focus causal
ktsl analyst S002 --export /tmp/report.zip
```

- commit: `"feat(ktsl): analyst CLI subcommand with focus + export"`

---

### Task 16: M3 闸门集成测试

**Files:**
- Create: `tests/scene/ktsl/test_m3_gate.py

- 端到端 M3 gate 验证 paper fixture 5 回合完整结算
- 故意两类违规因果 / 泄露审计正确
- `ktsl analyst <session>` 终端输出包含所有焦点

- commit: `"test(ktsl): M3 gate — full 5-turn runtime integration"`

---

## Self-Review Notes

**Spec coverage checklist:**
- [x] §1 Architecture (Stage protocol + Ledger) → Task 1-3, 8-12
- [x] §2 Data flow (M1/M2/M3 链路) → Task 4-5 / 6-7 / 13-15
- [x] §3 Error handling (干预 + Override 链) → Task 6 + 13 中 AuditStage
- [x] §4 Agent 集成 + 论文四组件 → Task 10-11 + 4(wizard) + 13-14(annotation/log)
- [x] §5 日志 + Analyst → Task 14-15
- [x] §6 测试 + Milestone 闸门 → Task 5, 7, 16

**Placeholder scan**：Task 4 / Task 10–13 标有"完整由 subagent dispatch 展开"——这些在 subagent-driven 执行时按接口实现。本 plan 已锁定接口签名和 Step 1/2/4 的契约（测试代码 + 期望输出），subagent 只需填入符合接口的实现。
