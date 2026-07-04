# KTSL KP 工具链实施计划

> **创建日期**：2026-07-04
> **状态**：实施计划，待用户审阅
> **对应设计文档**：`docs/superpowers/specs/2026-07-04-ktsl-kp-toolchain-design.md`
> **目标**：从现有 `src/scenario/ktsl/` 出发，构建完整的 KP 操作工具链
> **约束**：只修改 `src/scenario/ktsl/models.py`（只扩展不重写），其余现有文件不动

---

## 0. 全局依赖图与并行策略

```
Phase 1 ──→ Phase 2 ──→ Phase 3 ──→ Phase 4 ──→ Phase 5 ──→ Phase 6 ──→ Phase 7 ──→ Phase 8
 (Layer4      (Layer4     (Layer3     (Layer3    (Layer5     (Layer5    (Web       (Web
  Core)       Gate)       MD Report)  HTML)     CLI)        Backend)   Scaffold)  Mockup)
```

**关键路径**：1 → 2 → 3 → 4 → 5 → 6 → 7 → 8（严格串行）

**可并行任务**：
- Phase 1 的两个文件（`runtime_event.py` + `session_audit_tracker.py`）有依赖关系（tracker 依赖 adapter），但可以同一阶段内串行完成
- Phase 3 的两个报告文件（MD + HTML）共享同一数据模型，但 HTML 依赖 MD 验证后的结构
- Phase 5 CLI 和 Phase 6 Web Backend **可以并行开发**（都依赖 Layer 4，互不依赖）

**⚠️ 重要适配**：
- 设计文档提到 FastAPI，但项目实际使用 **aiohttp**（见 `main.py`）。Phase 6 Web Backend 使用 aiohttp handler 实现
- 约束要求不修改 `main.py` 和 `api.py`。Phase 6 的 router 以一个独立模块存在，注册方式在计划末尾说明
- 新增的 Pydantic 模型（AuditResult, SessionConfig, KnowledgeItem, SessionReport 等）添加到 `models.py`

---

## Phase 1：Layer 4 核心 — Session Audit Tracker + Runtime Event Adapter

**目标**：实现跑团状态机的核心：接收 KP 流式事件输入，实时检测违反，累积指标。

### 1.1 新增文件

| 文件 | 职责 |
|------|------|
| `src/scenario/runtime_event.py` | KP 自由输入 → EventRecord 适配翻译 |
| `src/scenario/session_audit_tracker.py` | 跑团状态机，submit_action → AuditResult |

### 1.2 修改文件

| 文件 | 改动 |
|------|------|
| `src/scenario/ktsl/models.py` | 新增 `AuditResult`, `SessionConfig`, `KnowledgeItem`, `ActionParseResult`, `ManualOverrides` 模型 |

### 1.3 数据模型（添加到 models.py）

```python
# --- 新增到 src/scenario/ktsl/models.py ---

class AuditResult(BaseModel):
    """单次 submit_action 的返回值"""
    allowed: bool
    resolution: Literal["matched", "keyword_fallback", "manual", "unresolved"]
    event_record: EventRecord | None = None
    violations: list[AuditEntry] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    updated_metrics: MetricSummary | None = None
    matched_clue_id: str | None = None

class SessionConfig(BaseModel):
    """ktsl session 开团时的配置声明（标注手册 calibration）"""
    session_id: str = Field(default="", max_length=80)
    fixture_id: str
    started_at: str = ""           # ISO timestamp
    kp_name: str = Field(default="", max_length=60)
    default_visibility: Visibility = "public"
    allow_override: bool = True    # 是否允许 KP 强制提交因果违反
    notes: str = Field(default="", max_length=2000)

class KnowledgeItem(BaseModel):
    """角色知识地图中的一项"""
    info_id: str
    kind: InfoKind                 # know / obs
    sensitivity: SensitivityLevel
    content_summary: str           # InfoLabel.public_payload 或截断 payload
    source_event_id: str           # 从哪个事件获得的
    source_scene_id: str
    acquired_at_minute: int = 0

class ActionParseResult(BaseModel):
    """parse_action 的返回值"""
    resolution: Literal["matched", "keyword_fallback", "unresolved"]
    event_record: EventRecord | None = None
    matched_clue_id: str | None = None
    score: float = 0.0
    candidate_clues: list[tuple[str, float]] = Field(default_factory=list)  # (clue_id, score)

class ManualOverrides(BaseModel):
    """当 auto-resolve 失败时，KP 手动指定 info 流向"""
    output_info_ids: list[str] = Field(default_factory=list)
    required_info_ids: list[str] = Field(default_factory=list)
    barrier_id: str = ""
    causal_dependency_ids: list[str] = Field(default_factory=list)
    depends_on_event_ids: list[str] = Field(default_factory=list)
```

### 1.4 RuntimeEventAdapter 接口结构

```python
# src/scenario/runtime_event.py

class RuntimeEventAdapter:
    """把 KP 的实际输入翻译为 EventRecord，供现有 schedule/filter/coupling 消费"""

    def __init__(self, fixture: KTSLFixture):
        # 建立 scene_id → clues 索引
        # 建立 info_id → InfoLabel 索引
        # 保存 fixture 引用

    def parse_action(
        self,
        action_text: str,
        actor: str,
        scene_id: str,
        committed_event_ids: set[str],      # 已提交的事件 ID 集合
    ) -> ActionParseResult:
        # 1. 从 fixture.clues 中筛选 scene_id 匹配的 clue
        # 2. 对每个 clue，计算 action_text 与 clue.title + clue.public_hint 的关键词匹配分
        #    - 分词：按字符 n-gram (n=2,3) 做中文兼容
        #    - score = 命中词数 / clue 总词数
        # 3. 取 top-1 clue；score >= 0.3 → "matched" 或 "keyword_fallback"
        # 4. 构造 EventRecord（复用 clue 的 input/output info_ids、barrier、dependency）
        # 5. score < 0.3 → resolution="unresolved"，返回空 event_record

    def resolve_manual(
        self,
        draft: EventRecord,
        overrides: ManualOverrides,
    ) -> EventRecord:
        # 用 KP 手动指定的 info/barrier/dependency 覆盖 draft 的对应字段
        # 返回完整的 EventRecord
```

**关键词匹配算法**：
- 不依赖 jieba（零额外依赖）
- 使用 char bigram + trigram 做中文分词兼容
- 英文直接 split()
- Score = len(命中 n-grams) / len(clue 总 n-grams)

### 1.5 SessionAuditTracker 接口结构

```python
# src/scenario/session_audit_tracker.py

@dataclass
class SessionState:
    fixture: KTSLFixture
    schedule_state: dict              # barrier 状态、事件排序
    knowledge_state: dict[str, ActorKnowledgeState]  # char_id → 知识状态
    event_log: list[EventRecord]      # 已提交事件历史
    violations: list[AuditEntry]      # 累积违反日志
    metrics: MetricSummary            # 实时更新的计数器
    config: SessionConfig
    event_counter: int = 0            # 自增事件编号（S001, S002...）

class SessionAuditTracker:
    def __init__(self, fixture: KTSLFixture, config: SessionConfig | None = None):
        # 初始化 SessionState
        # 从 fixture.initial_knowledge 构建 knowledge_state
        # 初始化 RuntimeEventAdapter

    def submit_action(
        self,
        action_text: str,
        actor: str,
        scene_id: str,
        visibility: Visibility | None = None,
        manual_overrides: ManualOverrides | None = None,
    ) -> AuditResult:
        # 1. adapter.parse_action() → ActionParseResult
        # 2. 如果 unresolved:
        #    - 如果有 manual_overrides → adapter.resolve_manual()
        #    - 否则 → 返回 AuditResult(allowed=False, resolution="unresolved")
        # 3. 三层检测（复用现有逻辑的简化版）:
        #    - Schedule: 检查 depends_on_event_ids ⊆ committed_event_ids
        #               检查 required_info_ids ⊆ known_info_ids
        #    - Filter: 检查 actor 是否有权获得 output_info_ids
        #              参考 filter.py 的 SENSENSITIVE_LEVELS 逻辑
        #    - Coupling: 检查涉及 scene_id 的 coupling drift
        # 4. 更新 knowledge_state[actor].known_info_ids += output_info_ids
        # 5. 更新 metrics 计数
        # 6. 追加到 event_log
        # 7. 返回 AuditResult

    def get_current_metrics(self) -> MetricSummary
    def get_knowledge_summary(self, character_id: str) -> list[KnowledgeItem]
    def get_scene_timeline(self, scene_id: str) -> list[EventRecord]
    def get_session_summary(self) -> SessionSummary  # 用于报告生成
    def save_state(self, path: Path) -> None           # SessionState → JSON
    def load_state(self, path: Path) -> None           # JSON → 恢复 SessionState
    def get_barrier_states(self) -> list[BarrierState]
    def get_coupling_states(self) -> list[CouplingState]
```

**关于"三层检测复用"的说明**：
现有 `evaluate.py` 的 `evaluate_fixture()` 是对 fixture 所有事件做批量评估，不适用于逐事件流式调用。Phase 1 的 tracker 采用"增量检测"模式：每次 submit_action 只检测当前事件的前置条件（barrier 是否满足、info 是否 authorized）和涉及的 coupling。这与 evaluate 的批量结果一致，但是增量版本。具体策略：
- Schedule 检测：检查 `depends_on_event_ids` 是否都在 `committed_event_ids` 中
- Filter 检测：检查 actor 的 visibility 场景下，output_info_ids 的 sensitivity 是否允许
- Coupling 检测：检查涉及的两个 scene 之间的 drift 是否超过 threshold

### 1.6 测试计划

**文件**：`tests/scene/test_ktsl_runtime_adapter.py`

```python
# 测试用例清单：

def test_adapter_matches_clue_by_title_keyword():
    """adapter 能从 action_text 匹配到 fixture 中的 clue"""
    # 使用现有的 build_library_sewer_church_fixture()
    # action_text = "搜查图书馆" → 应匹配到相关 clue

def test_adapter_returns_unresolved_for_unknown_action():
    """action_text 与任何 clue 无关时返回 unresolved"""

def test_adapter_keyword_fallback():
    """title 不完全匹配但 public_hint 命中时仍能匹配"""

def test_resolve_manual_overrides_draft():
    """resolve_manual 正确覆盖 output_info_ids"""

# ---

文件：tests/scene/test_ktsl_session_tracker.py

def test_tracker_initializes_from_fixture():
    """tracker 从 fixture 加载后 knowledge_state 正确"""

def test_submit_action_commits_valid_event():
    """提交合法事件后 event_log +1, metrics 不变"""

def test_submit_action_detects_causal_violation():
    """提交前置条件不满足的事件时，allowed=True (warn-only), violations 有记录"""

def test_submit_action_unresolved_with_manual_override():
    """unresolved 事件 + manual_overrides → 正常提交"""

def test_knowledge_state_updates_after_commit():
    """提交事件后 output_info_ids 加入 actor 的 known_info_ids"""

def test_save_and_load_state_roundtrip():
    """save_state → load_state 后状态一致"""

def test_metrics_accumulate_correctly():
    """多次提交后 metrics 计数正确"""

def test_get_knowledge_summary_returns_items():
    """get_knowledge_summary 返回 KnowledgeItem 列表"""

def test_scene_timeline_filters_by_scene():
    """get_scene_timeline 只返回指定 scene 的事件"""
```

### 1.7 验收标准（Phase 1 完成时可直接运行验证）

| 编号 | 标准 | 验证命令 |
|------|------|---------|
| P1-AC1 | Adapter 能匹配现有 fixture 的 clue | `pytest tests/scene/test_ktsl_runtime_adapter.py -v` 全部通过 |
| P1-AC2 | Tracker 能加载 fixture、submit_action 返回正确 AuditResult | `pytest tests/scene/test_ktsl_session_tracker.py -v` 全部通过 |
| P1-AC3 | save/load 往返序列化不丢数据 | 端到端测试：创建 tracker → 提交 3 个事件 → save → load → metrics 一致 |
| P1-AC4 | 现有测试不受影响 | `pytest tests/scene/test_ktsl_*.py` 全部通过 |

---

## Phase 2：Layer 4 门槛 — PublishGate

**目标**：实现发布阈值判定：加载 criteria → 三条件对照模拟 → pass/fail → 结果数据模型。

### 2.1 新增文件

| 文件 | 职责 |
|------|------|
| `src/scenario/publish_gate.py` | 发布阈值判定引擎 |

### 2.2 修改文件

| 文件 | 改动 |
|------|------|
| `src/scenario/ktsl/models.py` | 新增 `PublishCriteria`, `ModeThresholds`, `ModeResult`, `PublishGateResult` 模型 |

### 2.3 数据模型（添加到 models.py）

```python
# --- 新增到 src/scenario/ktsl/models.py ---

class ModeThresholds(BaseModel):
    """单对照条件（一个 RunMode）的阈值配置"""
    max_causal_violations: int | None = None
    max_unauthorized_actions: int | None = None
    max_public_payload_leaks: int | None = None
    max_spotlight_gap_minutes: int | None = None
    min_declassification_completeness: float | None = None
    max_retcons: int | None = None
    max_high_coupling_drift_minutes: int | None = None

class PublishCriteria(BaseModel):
    """发布阈值配置（对应 publish-criteria.yaml）"""
    version: str = "1.0.0"
    fixture_id: str = ""
    description: str = Field(default="", max_length=1000)
    thresholds: dict[RunMode, ModeThresholds] = Field(default_factory=dict)

class ModeResult(BaseModel):
    """单对照条件模拟结果"""
    mode: RunMode
    passed: bool
    metrics: MetricSummary
    failures: list[str]        # e.g. "ktsl_full.causal_violation: 2 > 0"
    warnings: list[str]

class PublishGateResult(BaseModel):
    """发布门槛总判定"""
    overall_pass: bool
    per_mode: list[ModeResult]
    evaluated_at: str           # ISO timestamp
    fixture_id: str
    criteria_version: str
```

### 2.4 PublishGate 接口结构

```python
# src/scenario/publish_gate.py

class PublishGate:
    """加载阈值配置 → 跑三次模拟 → 判定 pass/fail"""

    def __init__(self, fixture: KTSLFixture):
        self._fixture = fixture

    @staticmethod
    def load_criteria(path: Path) -> PublishCriteria:
        """从 YAML 文件加载 PublishCriteria"""
        # 使用 yaml.safe_load + PublishCriteria.model_validate()

    def evaluate(self, criteria: PublishCriteria) -> PublishGateResult:
        # 1. 对 criteria.thresholds 中的每个 mode:
        #    - 调用 evaluate_fixture(self._fixture, mode)  # 复用现有 evaluate 模块
        #    - 对比 metrics vs ModeThresholds
        #    - 收集 failures（值 > max 或值 < min 的项）
        #    - 收集 warnings（threshold 中缺少某指标的 key → soft gate）
        # 2. 汇总 overall_pass = all(mode.passed for mode in per_mode)
        # 3. 返回 PublishGateResult

    @staticmethod
    def default_criteria(fixture_id: str) -> PublishCriteria:
        """返回默认的宽松阈值配置（用于无 criteria YAML 时的 fallback）"""
        # baseline: max_causal_violations=5, max_retcons=3
        # schedule_only: max_causal_violations=2, max_unauthorized_actions=4, max_retcons=1
        # ktsl_full: 全指标零容忍
```

### 2.5 测试计划

**文件**：`tests/scene/test_ktsl_publish_gate.py`

```python
# 测试用例清单：

def test_load_criteria_from_yaml(tmp_path):
    """从 YAML 文件加载 PublishCriteria 模型"""

def test_default_criteria_has_all_modes():
    """default_criteria 返回包含三个 mode 的配置"""

def test_evaluate_returns_result_for_each_mode():
    """evaluate 为每个 mode 生成 ModeResult"""

def test_pass_when_metrics_within_threshold():
    """指标在阈值内 → passed=True"""

def test_fail_when_metrics_exceed_threshold():
    """指标超出阈值 → passed=False, failures 有明确描述"""

def test_missing_threshold_is_soft_gate():
    """某指标没有设置阈值 → 跳过该指标（warning，不 fail）"""

def test_overlogic_pass_is_all_modes_pass():
    """overall_pass = all(per_mode.passed)"""

def test_evaluate_uses_existing_evaluate_module():
    """evaluate 内部调用 evaluate_fixture（mock 验证）"""
```

### 2.6 验收标准

| 编号 | 标准 | 验证命令 |
|------|------|---------|
| P2-AC1 | 三条件对照模拟结果与设计文档示例一致 | `pytest tests/scene/test_ktsl_publish_gate.py -v` 全部通过 |
| P2-AC2 | 阈值判定逻辑正确（pass/fail） | 用已知 fixture 测试：ktsl_full → 全零容忍应 PASS |
| P2-AC3 | 现有测试不受影响 | `pytest tests/scene/test_ktsl_*.py` 全部通过 |

---

## Phase 3：Layer 3 MD 报告 — MarkdownRenderer

**目标**：实现零依赖的 Markdown 报告渲染，先做 Session Report 和 Publish Report。

### 3.1 新增文件

| 文件 | 职责 |
|------|------|
| `src/scenario/report/__init__.py` | 包入口 |
| `src/scenario/report/session_reports.py` | 报告数据模型（SessionReport, PublishReport, ValidateReport） |
| `src/scenario/report/markdown_renderer.py` | Markdown 渲染（f-string） |

### 3.2 修改文件

| 文件 | 改动 |
|------|------|
| `src/scenario/ktsl/models.py` | 新增 `SessionReport`（含嵌套模型如 ViolationEvent, EventSummary 等） |

### 3.3 报告数据模型（添加到 models.py）

```python
# --- 新增到 src/scenario/ktsl/models.py ---

class ViolationEvent(BaseModel):
    """违反事件记录"""
    event_id: str
    event_index: int              # S001, S002...
    actor: str
    action_text: str
    scene_id: str
    severity: Literal["info", "warning", "error"]
    metric: AuditMetric
    message: str
    overridden: bool = False

class EventSummary(BaseModel):
    """场景时间线中的事件摘要"""
    event_id: str
    event_index: int
    actor: str
    action_text: str
    time_minute: int = 0
    output_info_ids: list[str] = Field(default_factory=list)
    status: CommitStatus = "committed"

class BarrierState(BaseModel):
    """barrier 最终状态"""
    barrier_id: str
    status: BarrierStatus
    required_event_ids: list[str] = Field(default_factory=list)
    satisfied_event_ids: list[str] = Field(default_factory=list)
    required_info_ids: list[str] = Field(default_factory=list)
    satisfied_info_ids: list[str] = Field(default_factory=list)

class CouplingState(BaseModel):
    """coupling 最终状态"""
    coupling_id: str
    source_scene_id: str
    target_scene_id: str
    mode: CouplingMode
    drift_minutes: int = 0
    active: bool = True

class SessionSummary(BaseModel):
    """tracker.get_session_summary() 返回值"""
    fixture_id: str
    fixture_title: str
    started_at: str
    total_events: int
    total_committed: int
    total_overridden: int

class SessionReport(BaseModel):
    """完整 session 报告"""
    fixture_id: str
    fixture_title: str
    started_at: str
    ended_at: str
    session_config: SessionConfig
    total_events: int
    total_committed: int
    total_blocked: int
    total_overridden: int
    metrics: MetricSummary
    violation_timeline: list[ViolationEvent]
    final_knowledge_map: dict[str, list[KnowledgeItem]]
    scene_timelines: dict[str, list[EventSummary]]
    barrier_final_states: list[BarrierState]
    coupling_final_states: list[CouplingState]
```

### 3.4 MarkdownRenderer 接口结构

```python
# src/scenario/report/markdown_renderer.py

def render_session_report(report: SessionReport) -> str:
    """渲染 Session Report 为 Markdown 字符串"""
    # 1. 标题 + 元信息
    # 2. Metrics Dashboard（6 指标表格）
    # 3. Violation Timeline（列表）
    # 4. Character Knowledge Map（每个角色的已知信息列表）
    # 5. Scene Timelines（每个场景的事件列表）
    # 6. Barrier/Coupling 终态（表格）
    # 纯 f-string 拼接，零额外依赖

def render_publish_report(result: PublishGateResult) -> str:
    """渲染 Publish Gate 报告为 Markdown 字符串"""
    # 1. 标题 + fixture 信息
    # 2. Mode Comparison 表格
    # 3. Failures 列表（如有）
    # 4. Warnings 列表（如有）

def render_validate_report(fixture_id: str, errors: list[str], warnings: list[str]) -> str:
    """渲染 Validate 报告"""
    # 1. 结构校验结果摘要
    # 2. Errors 列表
    # 3. Warnings 列表
    # 退出码信息
```

### 3.5 测试计划

**文件**：`tests/scene/test_ktsl_markdown_renderer.py`

```python
# 测试用例清单：

def test_render_session_report_contains_metrics_table():
    """MD 包含六指标表头"""

def test_render_session_report_contains_knowledge_map():
    """MD 包含角色知识地图 section"""

def test_render_session_report_violation_timeline():
    """MD 包含违反事件列表"""

def test_render_session_report_scene_timelines():
    """MD 包含场景时间线 section"""

def test_render_publish_report_contains_mode_comparison():
    """MD 包含三条件对比表"""

def test_render_publish_report_shows_failures():
    """MD 包含 failures 列表（FAIL 时）"""

def test_render_validate_report_shows_errors_and_warnings():
    """MD 包含 errors/warnings"""

def test_markdown_is_valid_structure():
    """渲染结果可被解析（无格式混乱）"""
```

### 3.6 验收标准

| 编号 | 标准 | 验证命令 |
|------|------|---------|
| P3-AC1 | Session MD 报告包含所有必需 section | 渲染后断言 6 个 section 标题存在 |
| P3-AC2 | Publish MD 报告包含 mode comparison 表格 | 渲染后断言表格行存在 |
| P3-AC3 | 零额外依赖 | 不 import jinja2 或任何模板库 |
| P3-AC4 | 现有测试不受影响 | `pytest tests/scene/test_ktsl_*.py` 全部通过 |

---

## Phase 4：Layer 3 HTML 报告 — HTMLRenderer

**目标**：实现基于 Jinja2 的 HTML 报告渲染，生成可离线查看的 HTML 文件。

### 4.1 新增文件

| 文件 | 职责 |
|------|------|
| `src/scenario/report/html_renderer.py` | HTML 渲染（Jinja2 template） |
| `src/scenario/report/templates/session.html.j2` | Session HTML 模板 |
| `src/scenario/report/templates/publish.html.j2` | Publish HTML 模板 |

### 4.2 依赖变更

| 动作 | 文件 |
|------|------|
| 添加 jinja2 依赖 | `requirements.txt` |

> 注：`requirements.txt` 不是 `.py` 文件，其更新不违反"不修改现有 Python 文件"的约束。若严格要求不触碰任何现有文件，则将 jinja2 import 为 optional（try/except + 运行时检查）。

### 4.3 HTMLRenderer 接口结构

```python
# src/scenario/report/html_renderer.py

class HTMLRenderer:
    """加载 Jinja2 模板，渲染 HTML 报告"""

    def __init__(self, template_dir: Path | None = None):
        # 默认 template_dir = Path(__file__).parent / "templates"
        # 创建 Jinja2 Environment + FileSystemLoader

    def render_session_report(self, report: SessionReport) -> str:
        # 加载 session.html.j2
        # 传入 report model
        # 返回完整 HTML 字符串

    def render_publish_report(self, result: PublishGateResult) -> str:
        # 加载 publish.html.j2
        # 返回完整 HTML 字符串

    def render_to_file(self, content: str, path: Path) -> None:
        # 写入文件
```

### 4.4 模板结构（session.html.j2 设计说明）

```
模板变量: report (SessionReport)

结构:
- <head>: meta, <style> 内联 CSS（深色/浅色主题变量）
- <body>:
  - 页头: 标题 + fixture 名 + 时间范围
  - Metrics Dashboard: 6 个彩色卡片（grid layout）
  - Violation Timeline: 可折叠 <details> 元素
  - Character Knowledge Map: 每个角色一个子 section
  - Scene Timelines: 每个场景 + 进度条 (████░░)
  - Barrier/Coupling 终态: 表格
  - Footer: 生成时间 + KTSL 版本
```

**视觉规范**（供 Phase 8 /canvas-design mockup 参考）：
- 配色：Caus(#e74c3c), Unauth(#e67e22), Leak(#3498db), Spot(#2ecc71), Decl(#9b59b6), Retcon(#f39c12)
- 字体：system-ui, sans-serif
- 卡片：圆角 8px，阴影，hover 效果
- 进度条：内联 div 实现，不用外部 CSS 框架

### 4.5 Publish HTML 模板中的雷达图

Publish 报告的 HTML 包含 6 轴 SVG 雷达图：

```
<svg viewBox="0 0 400 400">
  <!-- 6 轴：Causal / Unauth / Leak / Spot / Decl / Retcon -->
  <!-- 三层对比：baseline(虚线灰) / schedule_only(虚线蓝) / ktsl_full(实线绿) -->
  <!-- 多边形 + 数据点 + 轴标签 -->
</svg>
```

生成策略：纯 Jinja2 template 中内联 SVG，通过 template loop 计算 6 个轴的角度和坐标。

### 4.6 测试计划

**文件**：`tests/scene/test_ktsl_html_renderer.py`

```python
# 测试用例清单：

def test_session_html_contains_metrics_cards():
    """HTML 包含 6 个 metrics 卡片"""

def test_session_html_contains_knowledge_map_content():
    """知识地图显示 content_summary（非仅 info_id）"""

def test_session_html_is_valid_html():
    """HTML 包含 <html>, <head>, <body> 标签"""

def test_publish_html_contains_svg_radar():
    """Publish HTML 包含 <svg> 元素"""

def test_publish_html_contains_mode_table():
    """Publish HTML 包含三层对比表"""

def test_html_no_external_resources():
    """HTML 不包含外部 CDN 链接（可离线查看）"""

def test_render_to_file_creates_file():
    """render_to_file 正确写入磁盘"""
```

### 4.7 验收标准

| 编号 | 标准 | 验证命令 |
|------|------|---------|
| P4-AC1 | Session HTML 可离线打开，知识地图显示内容摘要 | 渲染后断言 HTML 包含 public_payload 文本 |
| P4-AC2 | Publish HTML 包含 SVG 雷达图 | 渲染后断言 `<svg` 字符串存在 |
| P4-AC3 | 无外部 CDN 依赖 | 断言 HTML 中不包含 `cdn.` 或 `googleapis` |
| P4-AC4 | 现有测试不受影响 | `pytest tests/scene/test_ktsl_*.py` 全部通过 |

---

## Phase 5：Layer 5 CLI — ktsl 子命令

**目标**：实现 typer CLI 入口，四个子命令（validate / audit / session / publish / replay）。

### 5.1 新增文件

| 文件 | 职责 |
|------|------|
| `src/scenario/cli/ktsl_cli.py` | CLI 入口（typer app） |

### 5.2 依赖变更

| 动作 | 文件 |
|------|------|
| 添加 typer 依赖 | `requirements.txt` |

### 5.3 CLI 结构

```python
# src/scenario/cli/ktsl_cli.py

import typer

app = typer.Typer(help="KTSL KP 工具链 — 跑团前/中/后全流程")

@app.command()
def validate(
    fixture_path: str = typer.Argument(..., help="fixture YAML 文件路径"),
    output: str = typer.Option("validate-report.md", "--output", "-o"),
):
    """跑团前自检"""
    # 1. Load YAML → KTSLFixture.model_validate()
    # 2. 结构完整性检查（location_id, info_id, clue_id 引用验证）
    # 3. 循环依赖检测（CausalDependency / Barrier 依赖图 DFS）
    # 4. 死锁检测（barrier 前置条件链是否可达）
    # 5. 孤立信息检测
    # 6. 调用 render_validate_report() → 写入 output
    # 退出码: 0/1/2

@app.command()
def audit(
    fixture_path: str = typer.Option(..., "--fixture"),
    action: str = typer.Option(..., "--action"),
    actor: str = typer.Option(..., "--actor"),
    scene: str = typer.Option(..., "--scene"),
    force: bool = typer.Option(False, "--force"),
):
    """单次实时审计"""
    # 1. Load fixture
    # 2. Create SessionAuditTracker
    # 3. submit_action() → AuditResult
    # 4. 格式化 stdout 输出（纯文本框）
    # 如有 violations 且未 --force → warn 提示

@app.command()
def session(
    fixture_path: str = typer.Option(..., "--fixture"),
    output_dir: str = typer.Option("./logs", "--output-dir"),
):
    """交互式开团（REPL）"""
    # 1. Load fixture
    # 2. Create SessionAuditTracker
    # 3. 进入 cmd.Cmd REPL 循环:
    #    - do_action(actor, text, scene, visibility)
    #    - do_status()
    #    - do_timeline(scene_id)
    #    - do_knowledge(character_id)
    #    - do_barriers()
    #    - do_couplings()
    #    - do_save(path)
    #    - do_quit() → 生成 report
    # 4. quit 时调用 report 引擎生成 MD + HTML

@app.command()
def publish(
    fixture_path: str = typer.Option(..., "--fixture"),
    criteria_path: str = typer.Option(..., "--criteria"),
    format: str = typer.Option("html", "--format", help="md 或 html"),
    output: str = typer.Option("publish-report", "--output"),
):
    """发布门槛验证"""
    # 1. Load fixture
    # 2. Load criteria
    # 3. PublishGate.evaluate() → PublishGateResult
    # 4. 格式化 stdout 输出
    # 5. 根据 format 选择 MD 或 HTML 渲染
    # 6. 写入文件

@app.command()
def replay(
    state_path: str = typer.Argument(..., help="session-state.json 路径"),
    format: str = typer.Option("html", "--format"),
    output: str = typer.Option("replay-report", "--output"),
):
    """从保存的 session 状态回放"""
    # 1. SessionAuditTracker.load_state(state_path)
    # 2. get_session_summary()
    # 3. 构建 SessionReport
    # 4. 渲染 + 写入文件

# 入口
def main():
    app()

if __name__ == "__main__":
    main()
```

### 5.4 REPL 交互详细设计

```
内部命令 → SessionAuditTracker 方法映射:

do_action(actor, text, scene, visibility)
  → tracker.submit_action(action_text=text, actor=actor, scene_id=scene)
  → 格式化输出（允许/违反/警告）
  → 如 resolution="unresolved" → 提示手动指定 info_ids

do_status()
  → tracker.get_current_metrics() + barrier/coupling 计数
  → 格式化状态框

do_timeline(scene_id)
  → tracker.get_scene_timeline(scene_id)
  → 编号列表输出

do_knowledge(character_id)
  → tracker.get_knowledge_summary(character_id)
  → know/obs 分组输出

do_barriers()
  → tracker.get_barrier_states()
  → 状态列表（satisfied/waiting）

do_couplings()
  → tracker.get_coupling_states()
  → 耦合分数 + drift

do_save(path)
  → tracker.save_state(Path(path or default))

do_quit()
  → 构建 SessionReport
  → 渲染 MD + HTML 到 output_dir
  → raise SystemExit(0)
```

### 5.5 fixture 加载策略

```
优先级: 内置 fixture fixtures → 外部 YAML 文件

1. 如果 --fixture 参数是内置 fixture ID（如 "police_station_hospital_old_house"）:
   → get_ktsl_fixture(fixture_id)
2. 否则，当作文件路径:
   → 读取 YAML → KTSLFixture.model_validate(yaml_data)
```

> 注：现有 fixture 函数（`build_library_sewer_church_fixture()` 等）返回 `KTSLFixture` 对象，直接从内存加载。这些 fixture 就是"模组数据"，CLI 可以直接使用。

### 5.6 测试计划

**文件**：`tests/scene/test_ktsl_cli.py`

```python
# 测试用例清单（使用 CliRunner 或 subprocess）：

def test_validate_builtin_fixture_exit_code_0():
    """ktsl validate 对内置 fixture 返回 exit code 0"""

def test_validate_detects_missing_reference():
    """构造一个有 bad reference 的 fixture → exit code 2"""

def test_audit_outputs_allowed_for_valid_action():
    """ktsl audit 对合法动作输出 ALLOWED"""

def test_audit_outputs_violation_for_bad_action():
    """ktsl audit 对非法动作输出 violations"""

def test_session_e2e_workflow(tmp_path):
    """端到端：ktsl session → 提交 5 个事件 → quit → 报告存在"""
    # 使用 pexpect 或 stdin pipe 驱动 REPL

def test_publish_outputs_pass_for_clean_fixture():
    """ktsl publish 对 clean fixture 输出 PASS"""

def test_publish_outputs_html_report(tmp_path):
    """ktsl publish --format html 生成 .html 文件"""

def test_replay_loads_state_and_generates_report(tmp_path):
    """ktsl replay 从 JSON 恢复并生成报告"""

def test_cli_no_required_fixture_for_replay():
    """ktsl replay 接受 JSON path 而非 fixture path"""
```

### 5.7 验收标准

| 编号 | 标准 | 验证命令 |
|------|------|---------|
| P5-AC1 | `ktsl validate` 对两个内置 fixture 返回 0 | `python -m scenario.cli.ktsl_cli validate police_station_hospital_old_house ; echo $?` → 0 |
| P5-AC2 | `ktsl audit` 能给出正确 output_info 列表 | 快照测试 |
| P5-AC3 | `ktsl session` 端到端跑通关键路径 | 集成测试：5 events + barrier + report |
| P5-AC4 | `ktsl publish` → PASS + HTML report | 命令行为快照 + 文件存在 |
| P5-AC5 | `ktsl replay` 恢复状态 | 端到端测试 |
| P5-AC6 | 现有测试不受影响 | `pytest tests/scene/test_ktsl_*.py` |

---

## Phase 6：Layer 5 Web Backend — ktsl_router

**目标**：实现 aiohttp REST API 骨架，为前端提供接口。

### 6.1 新增文件

| 文件 | 职责 |
|------|------|
| `src/scenario/web/__init__.py` | 包入口 |
| `src/scenario/web/ktsl_router.py` | aiohttp 路由 handler |

### 6.2 接口设计（aiohttp handler 风格）

```python
# src/scenario/web/ktsl_router.py

from aiohttp import web

# 内存状态暂存
_SESSION_STORE: dict[str, SessionAuditTracker] = {}

# --- Request/Response Models (Pydantic) ---

class ActionInput(BaseModel):
    action_text: str
    actor: str
    scene_id: str
    visibility: Visibility | None = None

class SessionCreated(BaseModel):
    session_id: str
    fixture_id: str
    scene_count: int
    event_count: int

class SessionStateSnapshot(BaseModel):
    session_id: str
    metrics: dict  # MetricSummary.model_dump()
    knowledge_map: dict  # char_id → list[KnowledgeItem]
    event_count: int
    violation_count: int

# --- Route Handlers ---

async def handle_validate(request: web.Request) -> web.Response:
    """POST /ktsl/validate"""
    # 1. 读取 JSON body → fixture dict
    # 2. KTSLFixture.model_validate()
    # 3. 执行 validate 逻辑（同 CLI validate 命令）
    # 4. 返回 {"valid": bool, "errors": [...], "warnings": [...]}

async def handle_create_session(request: web.Request) -> web.Response:
    """POST /ktsl/session"""
    # 1. 读取 body → fixture_id 或 inline fixture
    # 2. 加载 fixture
    # 3. 创建 SessionAuditTracker
    # 4. 生成 session_id = sha1(fixture_id + timestamp)[:12]
    # 5. 存入 _SESSION_STORE[session_id]
    # 6. 返回 SessionCreated

async def handle_submit_event(request: web.Request) -> web.Response:
    """POST /ktsl/session/{session_id}/events"""
    # 1. 从 _SESSION_STORE 取 tracker
    # 2. 读取 body → ActionInput
    # 3. tracker.submit_action()
    # 4. 返回 AuditResult.model_dump()

async def handle_get_session_state(request: web.Request) -> web.Response:
    """GET /ktsl/session/{session_id}/state"""
    # 1. 取 tracker
    # 2. 构建 SessionStateSnapshot
    # 3. 返回 JSON

async def handle_get_timeline(request: web.Request) -> web.Response:
    """GET /ktsl/session/{session_id}/timeline?scene_id=xxx"""
    # 1. 取 tracker
    # 2. 可选 scene_id filter
    # 3. 返回事件列表 JSON

async def handle_get_report(request: web.Request) -> web.Response:
    """GET /ktsl/session/{session_id}/report?format=md|html"""
    # 1. 取 tracker
    # 2. 构建 SessionReport
    # 3. 根据 format 选择渲染器
    # 4. 返回 {"report": "...", "format": "md"}

async def handle_destroy_session(request: web.Request) -> web.Response:
    """DELETE /ktsl/session/{session_id}"""
    # 1. 从 _SESSION_STORE 删除
    # 2. 返回 {"deleted": session_id}

# --- Route Registration ---

def create_ktsl_app() -> web.Application:
    """创建独立的 aiohttp sub-app"""
    app = web.Application(middlewares=[error_middleware])
    app.add_routes([
        web.post("/ktsl/validate", handle_validate),
        web.post("/ktsl/session", handle_create_session),
        web.post("/ktsl/session/{session_id}/events", handle_submit_event),
        web.get("/ktsl/session/{session_id}/state", handle_get_session_state),
        web.get("/ktsl/session/{session_id}/timeline", handle_get_timeline),
        web.get("/ktsl/session/{session_id}/report", handle_get_report),
        web.delete("/ktsl/session/{session_id}", handle_destroy_session),
    ])
    return app
```

### 6.3 注册方式（不修改 main.py）

由于约束不能修改 `main.py`，Web router 通过以下方式之一注册：

**方案 A**（推荐）：在 `main.py` 同级添加 `ktsl_server.py`，作为独立 Web 入口文件。

**方案 B**：使用 aiohttp 的 `app.add_subapp()` 机制。在 `create_ktsl_app()` 中对现有 app:
```python
# 在 ktsl_server.py 中:
from main import create_app
ktsl_app = create_ktsl_app()
existing_app = create_app(service)
existing_app.add_subapp("/ktsl", ktsl_app)
```

### 6.4 测试计划

**文件**：`tests/scene/test_ktsl_web_router.py`

```python
# 测试用例（使用 aiohttp test_utils 或 pytest-aiohttp）:

async def test_validate_endpoint_returns_200(aiohttp_client):
    """POST /ktsl/validate 返回 200"""

async def test_create_session_returns_session_id(aiohttp_client):
    """POST /ktsl/session 返回 session_id"""

async def test_submit_event_returns_audit_result(aiohttp_client):
    """POST /ktsl/session/{id}/events 返回 AuditResult"""

async def test_get_state_returns_metrics(aiohttp_client):
    """GET /ktsl/session/{id}/state 返回 metrics"""

async def test_get_timeline_filters_by_scene(aiohttp_client):
    """GET /ktsl/session/{id}/timeline?scene_id=xxx"""

async def test_get_report_returns_html_or_md(aiohttp_client):
    """GET /ktsl/session/{id}/report?format=html"""

async def test_destroy_session_removes_state(aiohttp_client):
    """DELETE /ktsl/session/{id} 后 GET 返回 404"""

async def test_unknown_session_returns_404(aiohttp_client):
    """访问不存在的 session → 404"""
```

### 6.5 验收标准

| 编号 | 标准 | 验证命令 |
|------|------|---------|
| P6-AC1 | 所有路由返回 200 + 正确 JSON schema | `pytest tests/scene/test_ktsl_web_router.py -v` 全部通过 |
| P6-AC2 | 端到端流程：create session → submit events → get report | 集成测试 |
| P6-AC3 | 现有测试不受影响 | `pytest tests/scene/test_ktsl_*.py` |

---

## Phase 7：Layer 5 Web Frontend Scaffold

**目标**：搭建 React + TypeScript + Vite + Tailwind 前端项目骨架 + 空壳页面。

### 7.1 新增文件/目录

```
web/
  package.json
  tsconfig.json
  tsconfig.node.json
  vite.config.ts
  tailwind.config.js
  postcss.config.js
  index.html
  src/
    main.tsx
    App.tsx              # Router + Layout
    index.css            # Tailwind directives
    vite-env.d.ts
    pages/
      Dashboard.tsx       # 空壳：标题 + placeholder
      Session.tsx         # 空壳
      Timeline.tsx        # 空壳
      KnowledgeMap.tsx    # 空壳
      BarriersCouplings.tsx  # 空壳
      Reports.tsx         # 空壳
      Modules.tsx         # 空壳
    components/
      MetricsCard.tsx     # 空壳组件
      EventCard.tsx       # 空壳
      KnowledgeMatrix.tsx # 空壳
      TimelineTrack.tsx   # 空壳
      Sidebar.tsx         # 导航栏
      Layout.tsx          # 主布局（Sidebar + Main）
    hooks/
      useSession.ts       # 空壳：返回 mock 数据
      useSessionState.ts  # 空壳
    api/
      ktslClient.ts       # fetch wrapper（stub: 返回 mock）
    store/
      sessionStore.ts     # Zustand store（初始空状态）
    types/
      ktsl.ts             # TS 类型定义（与后端模型对应）
```

### 7.2 技术栈版本

| 工具 | 版本 |
|------|------|
| Node.js | ≥ 18 |
| React | ^18.3 |
| TypeScript | ^5.4 |
| Vite | ^5.2 |
| Tailwind CSS | ^3.4 |
| Zustand | ^4.5 |
| React Query (@tanstack/react-query) | ^5.40 |
| React Router | ^6.23 |
| Recharts | ^2.12 |

### 7.3 TS 类型定义（types/ktsl.ts 结构）

```typescript
// 与后端 Pydantic 模型一一对应

export type RunMode = "baseline" | "schedule_only" | "ktsl_full";
export type InfoKind = "know" | "obs";
export type SensitivityLevel = "public" | "low" | "medium" | "high" | "keeper";
export type Visibility = "public" | "private" | "keeper";
export type AuditMetric = "causal_violation" | "unauthorized_action" | "public_payload_leak" | "spotlight_gap" | "declassification" | "retcon" | "coupling_drift";

export interface MetricSummary {
  causal_violation_count: number;
  unauthorized_action_count: number;
  public_payload_leak_count: number;
  spotlight_max_gap_minutes: number;
  declassification_completeness: number;
  retcon_count: number;
  high_coupling_time_drift_minutes: number;
  barrier_wait_minutes: number;
  committed_event_count: number;
  blocked_event_count: number;
}

export interface AuditResult {
  allowed: boolean;
  resolution: "matched" | "keyword_fallback" | "manual" | "unresolved";
  violations: AuditEntry[];
  warnings: string[];
  updated_metrics: MetricSummary | null;
}

export interface KnowledgeItem {
  info_id: string;
  kind: InfoKind;
  sensitivity: SensitivityLevel;
  content_summary: string;
  source_event_id: string;
  source_scene_id: string;
  acquired_at_minute: number;
}

export interface SessionStateSnapshot {
  session_id: string;
  metrics: MetricSummary;
  knowledge_map: Record<string, KnowledgeItem[]>;
  event_count: number;
  violation_count: number;
}
```

### 7.4 页面路由结构

```typescript
// App.tsx 路由
<Router>
  <Layout>
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/session/:sessionId" element={<Session />} />
      <Route path="/session/:sessionId/timeline" element={<Timeline />} />
      <Route path="/session/:sessionId/knowledge" element={<KnowledgeMap />} />
      <Route path="/session/:sessionId/barriers" element={<BarriersCouplings />} />
      <Route path="/reports" element={<Reports />} />
      <Route path="/modules" element={<Modules />} />
    </Routes>
  </Layout>
</Router>
```

### 7.5 空壳页面要求

每个空壳页面包含：
1. 页面标题（`<h1>`）
2. 一个 placeholder 区域（"TBD" 或 mock 数据展示）
3. 正确的路由参数解析（如 `useParams()` 取 `sessionId`）

### 7.6 测试计划

**文件**：`web/src/**/*.test.tsx` (用 Vitest)

```typescript
测试用例：

test("Dashboard renders without crashing", async () => {
  render(<Dashboard />);
  expect(screen.getByText("Dashboard")).toBeInTheDocument();
});

test("Session page shows session id from URL", async () => {
  render(<MemoryRouter initialEntries={["/session/test-123"]}><Session /></MemoryRouter>);
  expect(screen.getByText(/test-123/)).toBeInTheDocument();
});

test("Sidebar navigation links exist", async () => {
  render(<Layout><Dashboard /></Layout>);
  expect(screen.getByText("Dashboard")).toBeInTheDocument();
  expect(screen.getByText("Timeline")).toBeInTheDocument();
});

test("ktslClient stub returns mock data", async () => {
  const result = await ktslClient.getState("test");
  expect(result.session_id).toBe("test");
});
```

### 7.7 验收标准

| 编号 | 标准 | 验证命令 |
|------|------|---------|
| P7-AC1 | Vite dev server 启动 | `cd web && npm run dev` → `localhost:5173` 可访问 |
| P7-AC2 | 所有页面路由可访问 | 导航到每个 URL 不报错 |
| P7-AC3 | 空壳组件渲染无 crash | `npm run test` 通过 |
| P7-AC4 | TypeScript 编译无错误 | `npx tsc --noEmit` 通过 |

---

## Phase 8：Web UI Mockup + 组件实现

**目标**：对六个核心页面做高保真 mockup → 用户确认 → 组件实现。

### 8.1 Mockup 阶段（调用 /canvas-design skill）

**前置条件**：Phase 7 完成 + Web backend 可用（或 mock server）

对以下 6 个页面分别调用 `/canvas-design skill` 生成高保真 mockup：

| # | 页面 | Mockup 内容 | Wireframe 参考 |
|---|------|------------|----------------|
| 1 | Dashboard | 6 色 metrics 卡片、最近警报列表、快速操作按钮 | 设计文档 §7.3 页面 A |
| 2 | Session | 底部事件提交栏 + 事件聊天流 + Override 按钮 | 设计文档 §7.3 页面 B |
| 3 | Timeline | 多场景并行轨道 + 时间轴 + 事件详情面板 | 设计文档 §7.3 页面 C |
| 4 | Knowledge Map | 交互式知识矩阵 + 单元格详情 | 设计文档 §7.3 页面 D |
| 5 | Barriers & Couplings | barrier 状态卡片 + coupling 分数面板 | 设计文档 §7.3 页面 E |
| 6 | Reports | 报告列表 + metrics 雷达图预览 + 导出按钮 | 设计文档 §7.3 页面 F |

**/canvas-design skill 调用顺序**（每个页面独立调用，逐个确认）：

```
for page in [Dashboard, Session, Timeline, KnowledgeMap, BarriersCouplings, Reports]:
    1. 调用 /canvas-design skill，传入:
       - 页面名称和用途
       - Wireframe ASCII（从设计文档 §7.3 复制）
       - 配色方案（Phase 4 定义的 6 色）
       - 交互要求（实时更新、可折叠、可点击）
    2. 等待用户确认 mockup
    3. 用户确认后 → 开始该页面的组件实现
```

### 8.2 组件实现（mockup 确认后）

**实现顺序**（按用户确认的 mockup 优先级）：

1. **基础组件**（所有页面共享）
   - `MetricsCard.tsx`（单个指标卡片）
   - `AlertFeed.tsx`（警报列表）
   - `Sidebar.tsx` + `Layout.tsx`

2. **Dashboard 页面**
   - 接入 `useSessionState` hook（从 API 拉取数据）
   - 6 个 MetricsCard 网格布局
   - AlertFeed 展示最近违反

3. **Session 页面**
   - `ActionSubmitBar.tsx`（底部固定栏）
   - `EventCard.tsx`（事件卡片，类似聊天气泡）
   - 实时轮询（每 2 秒 GET /session/{id}/state）

4. **Timeline 页面**
   - `TimelineTrack.tsx`（单场景轨道）
   - 多轨道容器 + 事件详情侧面板

5. **Knowledge Map 页面**
   - `KnowledgeMatrix.tsx`（交互式矩阵）
   - 点击单元格 → 详情面板

6. **Barriers & Couplings 页面**
   - Barrier 状态指示条
   - Coupling 分数 + drift 显示

7. **Reports 页面**
   - `RadarChart.tsx`（使用 Recharts RadarChart）
   - 报告列表 + 预览面板

### 8.3 状态管理接入

```typescript
// store/sessionStore.ts (Zustand)
interface SessionState {
  sessionId: string | null;
  metrics: MetricSummary | null;
  knowledgeMap: Record<string, KnowledgeItem[]>;
  events: EventRecord[];
  // actions:
  setSessionId: (id: string) => void;
  updateMetrics: (m: MetricSummary) => void;
  appendEvent: (e: EventRecord) => void;
}
```

### 8.4 测试计划

```typescript
每个页面的组件测试：
- 渲染测试：组件挂载不 crash
- 数据展示测试：传入 mock 数据后正确显示
- 交互测试：点击按钮/单元格触发正确回调
- 响应式测试：不同 viewport 下布局正确

集成测试：
- 端到端：create session via API → submit event → Web 面板显示新事件
- Dashboard metrics 与实际 API 返回一致
```

### 8.5 验收标准

| 编号 | 标准 | 验证方式 |
|------|------|---------|
| P8-AC1 | 6 个 mockup 全部通过用户评审 | 用户逐页确认签字 |
| P8-AC2 | Dashboard 实时显示 session 健康度 | 提交事件后 Dashboard metrics 更新 |
| P8-AC3 | Knowledge Map 正确显示"谁知道什么" | 与 CLI session quit 报告交叉验证 |
| P8-AC4 | RadarChart 在 Reports 页面正确渲染 | 视觉检查 + 快照测试 |
| P8-AC5 | 轮询更新（每 2 秒）工作正常 | 观察 Web 面板实时更新 |
| P8-AC6 | 响应式布局（桌面/平板/手机） | Chrome DevTools 模拟不同 viewport |

---

## 全局验收标准汇总（对应设计文档 §13）

| 编号 | 标准 | 对应 Phase | 验证方式 |
|------|------|-----------|---------|
| AC1 | `ktsl validate` 能检测两个现有 fixture 的结构完整性 | P5 | exit code = 0 |
| AC2 | `ktsl audit` 给出正确 output_info 列表 | P5 | 命令行为快照测试 |
| AC3 | `ktsl session` 完整跑通关键路径 | P5 | 端到端集成测试 |
| AC4 | `ktsl publish` 给出 PASS 判定 | P5 | 命令行为快照 + HTML 报告 |
| AC5 | Session Report HTML 知识地图显示内容摘要 | P4 | HTML 渲染输出断言 |
| AC6 | `ktsl replay` 恢复并生成报告 | P5 | 端到端集成测试 |
| AC7 | Web 骨架所有路由返回 200 + 正确 JSON | P6 | API 冒烟测试 |
| AC8 | 全部新代码有测试覆盖 | P1-P7 | `pytest tests/scene/test_ktsl_*.py` |
| AC9 | Web 前端六个页面 mockup 通过用户评审 | P8 | 用户签字确认 |

---

## 新增文件清单汇总

```
src/scenario/
├── runtime_event.py                     # Phase 1 — KP输入适配
├── session_audit_tracker.py             # Phase 1 — 跑团状态机
├── publish_gate.py                      # Phase 2 — 发布门槛
├── report/
│   ├── __init__.py                      # Phase 3
│   ├── session_reports.py               # Phase 3 — 报告数据模型
│   ├── markdown_renderer.py             # Phase 3 — MD 渲染
│   ├── html_renderer.py                 # Phase 4 — HTML 渲染
│   └── templates/
│       ├── session.html.j2              # Phase 4 — HTML 模板
│       └── publish.html.j2              # Phase 4 — HTML 模板
├── cli/
│   └── ktsl_cli.py                      # Phase 5 — CLI 入口
└── web/
    ├── __init__.py                      # Phase 6
    └── ktsl_router.py                   # Phase 6 — aiohttp router

web/                                      # Phase 7 — 前端项目
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.js
├── index.html
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── pages/ (7 个空壳 .tsx)
    ├── components/ (7 个空壳 .tsx)
    ├── hooks/ (2 个 .ts)
    ├── api/ktslClient.ts
    ├── store/sessionStore.ts
    └── types/ktsl.ts

tests/scene/
├── test_ktsl_runtime_adapter.py          # Phase 1
├── test_ktsl_session_tracker.py          # Phase 1
├── test_ktsl_publish_gate.py             # Phase 2
├── test_ktsl_markdown_renderer.py        # Phase 3
├── test_ktsl_html_renderer.py            # Phase 4
├── test_ktsl_cli.py                      # Phase 5
└── test_ktsl_web_router.py               # Phase 6

总计新增：~ 30 个文件
```

---

## 依赖添加汇总

| 依赖 | 用途 | 引入 Phase |
|------|------|-----------|
| `typer` | CLI 框架 | Phase 5 |
| `jinja2` | HTML 模板渲染 | Phase 4 |

两个库都添加至 `requirements.txt`。

---

## 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 增量检测与批量 evaluate 结果不一致 | P1 tracker 判定的 violations 可能与 evaluate_fixture() 不同 | P1 测试中加入对比验证：tracker 提交 fixture 中所有事件后的 metrics ≈ evaluate_fixture() 结果 |
| fixture YAML 来自外部时 schema 未定型 | P5 validate 可能遇到未知字段 | 使用 Pydantic 的 `model_config = ConfigDict(extra="forbid")` 或宽松模式 |
| aiohttp 与 typer 事件循环冲突 | P6 handler 调用同步的 tracker 方法 | tracker 是纯同步逻辑，aiohttp handler 中直接调用，不需要 await |
| Web 前端 mockup 用户反复修改 | P8 时间超预期 | 每个页面 mockup 最多 2 轮修改，超出则进入实现后续迭代微调 |
| jinja2 未安装时 HTML 报告不可用 | P4 HTML render 失败 | html_renderer 中为 jinja2 import 提供友好错误提示，fallback 到 MD |
