# KTSL KP 工具链设计

> **创建日期**：2026-07-04
> **状态**：设计草稿，待用户审阅
> **对应模块**：`src/scenario/ktsl/`、`src/scenario/cli/`、`src/scenario/web/`
> **目标受众**：KP（主持人），在真实跑团场景中使用
> **对应的论文 QC 项**：标注手册 calibration、预注册、失败条件阈值

---

## 1. 总览

### 1.1 要解决的问题

当前 `src/scenario/ktsl/` 有完整的三层协议逻辑（Schedule / Filter / Coupling）和六指标评估能力，但没有**可操作的 KP 端到端工作流**。本文档设计：

1. **CLI**：KP 在命令行中执行预检、实时审计、开团、复盘
2. **Web 骨架**：预留 REST API 接口，为后续前端面板做准备
3. **报告引擎**：生成可分享的 Markdown / HTML 复盘报告
4. **Session 状态机**：流式事件输入 + 实时违反检测
5. **发布门槛**：发布前全模拟 + 阈值判定

### 1.2 四个使用场景

| 场景 | CLI 命令 | 阶段 |
|------|---------|------|
| 跑团前：模组准备与自检 | `ktsl validate` | fixture 加载时 |
| 跑团中：实时审计 | `ktsl audit` / `ktsl session` | 每个裁决时 |
| 跑团后：复盘报告 | `ktsl session quit` / `ktsl replay` | session 结束时 |
| 模组发布前：发布门槛 | `ktsl publish` | 发布到分发渠道前 |

### 1.3 与论文 QC 项的映射

| 论文 QC 项 | 本工具中的对应物 |
|---|---|
| Cohen's κ 标注者间信度 | 不实现（单 KP 无第二标注者；v2 可扩展） |
| 盲审去标识化 | 不实现（KP 本身就是全知者） |
| 双标注者独立标注 | 不实现（无此需求） |
| 标注手册 calibration | `ktsl session` 开团时的 session config（参数声明） |
| 预注册 (preregistration) | `publish-criteria.yaml`（版本锁定、可审计） |
| 失败条件阈值 | `PublishGate`（三种对照条件下的量化判定） |

---

## 2. 总体架构

### 2.1 五层结构

```
┌──────────────────────────────────────────────────────────────────┐
│  Layer 5: Entry Points                                           │
│  CLI (typer)                    Web Skeleton (FastAPI router)    │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────┴───────────────────────────────────┐
│  Layer 4: Orchestration (新)                                     │
│  SessionAuditTracker            PublishGate                      │
│  (状态机: events in → violations out)  (阈值判定 + 判定报告)     │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────┴───────────────────────────────────┐
│  Layer 3: Report Engine (新)                                     │
│  SessionReport → MarkdownRenderer + HTMLRenderer                 │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────┴───────────────────────────────────┐
│  Layer 2: Simulation Core (现有，轻微扩展)                        │
│  schedule / filter / coupling / audit / evaluate                 │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────┴───────────────────────────────────┐
│  Layer 1: Domain Models + Fixtures (现有)                        │
│  models.py (KTSLFixture, EventRecord, InfoLabel, ...)            │
│  fixtures.py (图书馆/下水道, 警察/医院, 可扩展)                  │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 新增文件清单

| 文件 | Layer | 职责 |
|------|-------|------|
| `src/scenario/session_audit_tracker.py` | 4 | 跑团状态机：submit_action → AuditResult |
| `src/scenario/publish_gate.py` | 4 | 发布阈值判定：fixture + criteria → pass/fail |
| `src/scenario/runtime_event.py` | 2.5 | KP 自由输入 → EventRecord 适配翻译 |
| `src/scenario/report/__init__.py` | 3 | 报告引擎入口 |
| `src/scenario/report/session_reports.py` | 3 | Session 报告数据模型 |
| `src/scenario/report/markdown_renderer.py` | 3 | Markdown 渲染（f-string，零依赖） |
| `src/scenario/report/html_renderer.py` | 3 | HTML 渲染（Jinja2 模板 + inline CSS/SVG） |
| `src/scenario/report/templates/session.html.j2` | 3 | Session 报告 HTML 模板 |
| `src/scenario/report/templates/publish.html.j2` | 3 | Publish 报告 HTML 模板 |
| `src/scenario/cli/ktsl_cli.py` | 5 | CLI 入口（typer），四个子命令 |
| `src/scenario/web/ktsl_router.py` | 5 | FastAPI router 骨架 |
| `tests/scene/test_ktsl_*.py` (新增 2-3 个) | - | tracker / gate / adapter 的测试 |

### 2.3 对现有代码的改动（最小化）

| 文件 | 改动 |
|------|------|
| `src/scenario/ktsl/__init__.py` | 导出新的公共类型（SessionAuditTracker, PublishCriteria 等） |
| `src/scenario/ktsl/models.py` | 可能新增 1-2 个轻量模型（如 AuditResult, SessionConfig） |
| `src/scenario/ktsl/fixtures.py` | 不动 |
| `src/scenario/ktsl/{schedule,filter,coupling,audit,evaluate}.py` | 不动 |
| `src/scenario/api.py` | 注册 ktsl_router |
| `main.py` | 注册 ktsl CLI 子命令 |

---

## 3. Layer 4 — 编排层

### 3A. SessionAuditTracker

**职责**：接收流式事件输入，实时维护世界状态快照，检测六类违反，累积指标。

#### 状态

```python
@dataclass
class SessionState:
    fixture: KTSLFixture              # 模组数据（加载后只读）
    schedule_state: dict              # barrier 状态、事件排序、时间线
    knowledge_state: dict[str, ActorKnowledgeState]  # char_id → 知识状态
    event_log: list[EventRecord]      # 已提交事件历史
    violations: list[AuditEntry]      # 累积违反日志
    metrics: MetricSummary            # 实时更新的计数器
    config: SessionConfig             # session 参数配置
```

#### 输入方法

```python
def submit_action(
    self,
    action_text: str,       # "玩家搜查医生办公室"
    actor: str,             # "佐藤"
    scene_id: str,          # "hospital_wing"
    visibility: Visibility | None = None,  # 默认从 scene_card 取
    manual_overrides: dict | None = None,  # 当 auto-resolve 失败时使用
) -> AuditResult:
```

`submit_action` 的执行步骤：

1. 通过 `RuntimeEventAdapter.parse_action()` 将 KP 输入翻译为 `EventRecord`
2. 返回 `resolution: "unresolved"` 时，提示 KP 用 `manual_overrides` 补充
3. 三层检测（复用现有逻辑）：
   - **Schedule 层**：检查前置事件/信息是否满足 → 更新 barrier 状态
   - **Filter 层**：检查 actor 是否有权获得 output_info_ids 的信息
   - **Coupling 层**：检查场景间 barrier 是否被触发、drift 是否超限
4. 更新 `knowledge_state`（该 actor 现在知道了什么）
5. 更新 `metrics` 中受影响的计数器
6. 返回 `AuditResult{allowed, violations, warnings, updated_metrics, event_record}`

#### 查询方法

```python
def get_current_metrics(self) -> MetricSummary
def get_knowledge_summary(self, character_id: str) -> list[KnowledgeItem]
def get_scene_timeline(self, scene_id: str) -> list[EventRecord]
def get_session_summary(self) -> SessionSummary  # 用于报告生成
def save_state(self, path: Path) -> None           # 序列化到 JSON
def load_state(self, path: Path) -> None           # 从 JSON 恢复
```

#### 关键设计决策

- **不依赖 LLM**。纯确定性 —— KP 输入"行动文本 + 角色 + 场景"，tracker 在现有 schedule/filter/coupling 逻辑上跑检测
- **默认 warn-only**。提交的事件触发 causal violation 时不阻塞（现实跑团中 KP 可能故意破规），但记录在案并累积 metrics
- **状态可序列化**。session state 可以 save/load JSON（支持跑团中断续接）

### 3B. PublishGate

**职责**：加载阈值配置 → 跑三次模拟（三条件对照）→ 判定 pass/fail → 生成判定报告。

```python
@dataclass
class PublishCriteria:
    thresholds: dict[RunMode, ModeThresholds]
    # 每种对照条件下每个指标的上限/下限

@dataclass
class ModeThresholds:
    max_causal_violations: int | None = None
    max_unauthorized_actions: int | None = None
    max_public_payload_leaks: int | None = None
    max_spotlight_gap_minutes: int | None = None
    min_declassification_completeness: float | None = None
    max_retcons: int | None = None
    max_high_coupling_drift_minutes: int | None = None

@dataclass
class ModeResult:
    mode: RunMode
    passed: bool
    metrics: MetricSummary
    failures: list[str]        # e.g. "ktsl_full.causal_violation: 2 > 0"
    warnings: list[str]

@dataclass
class PublishGateResult:
    overall_pass: bool
    per_mode: list[ModeResult]
    evaluated_at: str           # ISO timestamp
    fixture_id: str
    criteria_version: str
```

#### 阈值配置 YAML 示例

```yaml
# publish-criteria.yaml
version: "1.0.0"
fixture_id: "police_hospital_old_house"
description: "三级场景模组发布标准"

thresholds:
  baseline:
    max_causal_violations: 5
    max_retcons: 3

  schedule_only:
    max_causal_violations: 2
    max_unauthorized_actions: 4
    max_retcons: 1

  ktsl_full:
    max_causal_violations: 0
    max_unauthorized_actions: 0
    max_public_payload_leaks: 0
    max_spotlight_gap_minutes: 30
    min_declassification_completeness: 0.95
    max_retcons: 0
    max_high_coupling_drift_minutes: 15
```

---

## 4. Layer 5 — CLI 设计

### 4.1 依赖

- CLI 框架：**typer**（与项目现有 pydantic + typer 使用模式一致）
- REPL 交互：Python 内置 `cmd` 模块（轻量、无额外依赖）
- 报告模板：Jinja2（Markdown 走 f-string，HTML 走 Jinja2 template）

### 4.2 四个子命令

#### `ktsl validate` — 跑团前自检

```
$ ktsl validate fixture.yaml

执行流程:
1. fixture schema 校验（KTSLFixture 模型校验）
2. 结构完整性检查:
   -SceneCard 引用的 location_id 是否存在
   -EventRecord 引用的 info_id / clue_id 是否存在
   -Barrier 引用的 scene_id / event_id 是否存在
   -Coupling 引用的 source/target scene_id 是否存在
3. 检测循环依赖（CausalDependency / Barrier 的 event 依赖图）
4. 检测死锁 barrier（前置事件链永远无法满足的 barrier）
5. 检测孤立信息（info_label 不被任何 clue/event 引用）
6. 输出 validate-report.md

退出码:
  0 = 全部通过
  1 = 有 warning（孤立信息等软问题）
  2 = 有 error（循环依赖、死锁等硬问题）
```

#### `ktsl audit` — 单次实时审计

```
$ ktsl audit --fixture module.yaml \
             --action "玩家搜查医生办公室" \
             --actor 佐藤 \
             --scene hospital_wing

即时输出 (stdout, 纯文本):
  ┌─ Audit Result ─────────────────────────────┐
  │ Status:    ALLOWED                          │
  │ Resolution: matched clue "search_office"   │
  │                                             │
  │ Info flow:                                  │
  │   └─ output: [info_07] 档案记录 (low)       │
  │       └─ 佐藤 now knows: 档案内容 (low)    │
  │                                             │
  │ Violations: none                            │
  │ Warnings:   none                            │
  └─────────────────────────────────────────────┘

  (如有违反)
  ┌─ Audit Result ─────────────────────────────┐
  │ Status:    BLOCKED (barrier not met)       │
  │                                             │
  │ Violations:                                 │
  │   [ERROR] causal_violation: barrier B3      │
  │           requires event E5 (not committed) │
  │   [WARN]  info_leak: 佐藤 will learn        │
  │           [info_12] 尸体位置 (high)         │
  │           but scene is public               │
  │                                             │
  │ Override (--force): commit anyway           │
  └─────────────────────────────────────────────┘
```

#### `ktsl session` — 交互式开团

```
$ ktsl session --fixture module.yaml --output-dir ./logs/

[Loading fixture: police_hospital_old_house]
[OK] 4 scenes loaded, 23 events in fixture, 12 barriers.

KTSL session started. Type 'help' for commands.
Metrics: causal=0 unauth=0 leak=0 spot_gap=0 decl=0.0 retcon=0

KTSL> action 佐藤 "翻找档案柜" @hospital_records
[OK] committed as event #S001. (timeline: 1 events, 0 violations)
     output: 佐藤 now knows [info_07] 档案记录 (low)

KTSL> action 李 "偷偷跟踪佐藤" @street
[WARN] potential info leak:
     李 will learn [info_07-summary] 佐藤发现了某物 (low,partial)
     but 李 doesn't know 档案内容 explicitly
     → (o)verride / (r)ollback / (a)llow+)flag > a
[OK] committed with flag. leak_count++.

KTSL> status
┌─ Session Status ──────────────────────────┐
│ Events committed:   2                      │
│ Current metrics:                           │
│   causal_violations:    0                  │
│   unauthorized_actions: 0                  │
│   public_payload_leaks: 0                  │
│   flagged_leaks:        1                  │
│   spotlight_max_gap:    0 min              │
│   retcons:              0                  │
│ Active barriers: 1 (B3 waiting)           │
│ Active couplings:  0                       │
└────────────────────────────────────────────┘

KTSL> timeline hospital_records
  [1] 佐藤 "翻找档案柜" @0min → output: info_07
  [2] ...

KTSL> knowledge 佐藤
  知道 (know):
    [info_07] 档案记录 (low) — from event #S001
  看到 (observed):
    (none)

KTSL> save
[OK] saved to ./logs/session-state.json

KTSL> quit
[OK] session closed.
     Report: ./logs/session-report.md
             ./logs/session-report.html
```

#### `ktsl publish` — 发布门槛验证

```
$ ktsl publish module.yaml --criteria publish-criteria.yaml --format html

[Simulation running...]
[OK] Simulation complete.

─ Publish Gate Result ─────────────────────────────
  Module:    police_hospital_old_house
  Criteria:  publish-criteria.yaml v1.0.0
  Verdict:   PASS / FAIL

  Mode Comparison:
  │ Mode           │ Caus │ Unauth │ Leak │ Decl │ Retcon │ Verdict │
  │ baseline       │  3   │   8    │  2   │ 0.40 │   1    │  PASS   │
  │ schedule_only  │  1   │   3    │  2   │ 0.65 │   0    │  PASS   │
  │ ktsl_full      │  0   │   0    │  0   │ 0.97 │   0    │  PASS   │

  Report: ./publish-report.html

  (失败时)
  Mode Comparison:
  │ ktsl_full      │  2   │   0    │  1   │ 0.97 │   0    │  FAIL   │
  Failures:
    - ktsl_full.causal_violation: 2 > 0 (expected)
    - ktsl_full.public_payload_leak: 1 > 0 (expected)
  Report: ./publish-report.html
```

#### `ktsl replay` — 从保存的 session 状态回放

```
$ ktsl replay ./logs/session-state.json --format html
[OK] loaded session with 2 events, 1 flagged leak.
[OK] Report: ./logs/replay-report.html
```

### 4.3 REPL 子命令详细

| REPL 命令 | 语法 | 功能 |
|-----------|------|------|
| `action` | `action <actor> "<text>" @<scene_id> [--visibility public\|private\|keeper]` | 提交事件 |
| `status` | `status [--verbose]` | 当前 metrics snapshot |
| `timeline` | `timeline <scene_id>` | 场景时间线 |
| `knowledge` | `knowledge <character_id>` | 角色知识状态 |
| `barriers` | `barriers` | 当前 barrier 状态一览 |
| `couplings` | `couplings` | 当前 coupling 状态一览 |
| `override` | `override <event_id> --commit` | 强制提交已违反的事件 |
| `rollback` | `rollback --last N` | 回滚最近 N 个事件 |
| `save` | `save [path]` | 保存 session 状态 |
| `help` | `help [command]` | 帮助信息 |
| `quit` / `exit` | `quit [--no-report]` | 退出并生成报告 |

---

## 5. Layer 3 — 报告引擎

### 5.1 报告类型

| 报告 | 触发命令 | 格式 | 内容 |
|------|---------|------|------|
| Session Report | `session quit` / `replay` | MD + HTML | 六指标摘要、违反事件时间线、角色知识地图、场景时间线 |
| Publish Report | `publish` | MD + HTML | 三条件对比表、阈值判定结果、失败项清单、指标雷达图（HTML inline SVG） |
| Validate Report | `validate` | MD（stdout可选） | 结构校验结果、循环依赖、死锁、孤立信息 |
| Audit Snapshot | `audit` | 纯文本（stdout） | 单次裁决结果 + 当前累计 metrics |

### 5.2 报告内部结构（Session Report）

```python
@dataclass
class SessionReport:
    fixture_id: str
    fixture_title: str
    started_at: str           # ISO timestamp
    ended_at: str
    session_config: SessionConfig
    total_events: int
    total_committed: int
    total_blocked: int
    total_overridden: int     # KP 强制提交的次数
    metrics: MetricSummary
    violation_timeline: list[ViolationEvent]  # 每个违反事件的详细记录
    final_knowledge_map: dict[str, list[KnowledgeItem]]  # char_id → 知道什么
    scene_timelines: dict[str, list[EventSummary]]  # scene_id → 事件摘要
    barrier_final_states: list[BarrierState]
    coupling_final_states: list[CouplingState]

@dataclass
class KnowledgeItem:
    info_id: str
    kind: InfoKind           # know / obs
    sensitivity: SensitivityLevel
    content_summary: str     # InfoLabel.public_payload 或截断 payload
    source_event_id: str     # 从哪个事件获得的
    source_scene_id: str
    acquired_at_minute: int
```

### 5.3 HTML 报告视觉结构

```
┌─────────────────────────────────────────────────────────────┐
│  KTSL Session Report                                        │
│  Module: 警察·医院·老宅  |  Date: 2026-07-04                │
├─────────────────────────────────────────────────────────────┤
│  Metrics Dashboard (6 色卡)                                  │
│  ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐                 │
│  │Caus│ │Unau│ │Leak│ │Spot│ │Decl│ │Retc│                 │
│  │ 0  │ │ 1  │ │ 0  │ │ 25 │ │0.97│ │ 0  │                 │
│  └────┘ └────┘ └────┘ └────┘ └────┘ └────┘                 │
├─────────────────────────────────────────────────────────────┤
│  Violation Timeline (可折叠 / collapsible)                    │
│  ▶ Event #S003: 李跟踪佐藤 → 潜在泄露 flagged (WARN)        │
│  ▶ Event #S007: 跳过 barrier B3 → 因果违反 (ERROR, overriden)│
├─────────────────────────────────────────────────────────────┤
│  Character Knowledge Map                                     │
│                                                              │
│  佐藤 (玩家)                                                  │
│  ├─ 📖 知道 [high] 老宅地下室有尸体                           │
│  │   └─ 来源: 事件#S005 (hospital_wing → old_house)          │
│  ├─ 👁️ 看到 [medium] 医生深夜进入档案室                        │
│  │   └─ 来源: 事件#S002 (hospital_wing)                      │
│  └─ 📖 知道 [low] 警察有搜查令                                 │
│      └─ 来源: 初始知识 (模组设定)                              │
│                                                              │
│  李 (玩家)                                                    │
│  ├─ 📖 知道 [low] 警察有搜查令                                 │
│  │   └─ 来源: 初始知识                                         │
│  └─ 👁️ 看到 [medium] 佐藤翻找档案柜                            │
│      └─ 来源: 事件#S003 (street)                              │
│                                                              │
│  ⚠️ 李 不知道 [high] 老宅地下室有尸体 — 但事件#S007 中佐藤     │
│     的对话可能暗示了这一点（潜在泄露 #1）                        │
├─────────────────────────────────────────────────────────────┤
│  Scene Timelines                                             │
│  hospital_wing: ████████░░░░ (2/3 events, 1 barrier waiting) │
│  street:        ███░░░░░░░░░ (1/4 events)                    │
│  old_house:     █░░░░░░░░░░░ (0/2 events, locked)            │
├─────────────────────────────────────────────────────────────┤
│  Appendix: Raw Events Table                                  │
└─────────────────────────────────────────────────────────────┘
```

### 5.4 模板策略

- **Markdown**：纯 Python f-string 拼接（零依赖，可被 Pandoc / Obsidian / Notion 二次消费）
- **HTML**：Jinja2 模板 + 内联 CSS（不依赖外部 CDN，报告文件可离线查看/打印/分享）
- **雷达图**：HTML publish 报告中用 inline SVG 绘制 6 轴雷达图（不引入 matplotlib/plotly）

---

## 6. Runtime Event Adapter

### 6.1 职责

当前代码的 `EventRecord` 是 fixture 中预定义的静态数据。但 KP 跑团时需要运行时动态生成事件。需要一个适配层把 KP 自由输入翻译为 `EventRecord`。

### 6.2 接口

```python
class RuntimeEventAdapter:
    """把 KP 的实际输入翻译为 EventRecord，供现有 schedule/filter/coupling 消费"""

    def __init__(self, fixture: KTSLFixture): ...

    def parse_action(
        self,
        action_text: str,        # "玩家搜查医生办公室"
        actor: str,              # "佐藤"
        scene_id: str,           # "hospital_wing"
        current_state: SessionState,
    ) -> ActionParseResult:
        """
        匹配策略:
        1. fixture 中的 ClueRecord 做模糊匹配
           （"搜查" → clue "search_office"）
           → 找到对应的 input_info_ids / output_info_ids
        2. 找不到精确匹配 → 用关键词回退
           （"医生" → 医院场景的任意 clue）
        3. 仍找不到 → 返回 resolution="unresolved"
           （KP 需要手动指定 info 流向）
        4. 构造 EventRecord（所有 ID 已填入，可直接送进三层检测）
        """

    def resolve_manual(
        self,
        draft: EventRecord,
        overrides: ManualOverrides,  # KP 手动指定 info/barrier/dependency
    ) -> EventRecord:
        """当自动匹配失败时，KP 手动指定 info 流向"""
```

### 6.3 模糊匹配算法（初步方案）

```python
# 优先级：精确包含 > 关键词命中 > 语义相似（可选）

1. 将 action_text 分词（中文 jieba / 英文 split）
2. 对每个 scene_id 下的 ClueRecord:
   - check clue.title 中是否有任何词命中 action_text
   - check clue.public_hint 中是否有任何词命中 action_text
   - 命中数 / clue 总词数 = score
3. 取 score 最高的 clue
4. 如果 top score < threshold (0.3) → unresolved
```

**实现约束**：不修改现有 `EventRecord` 模型。Adapter 只做 KP 输入到 EventRecord 的单向翻译。三层检测逻辑完全复用。

---

## 7. Web 前端设计

### 7.1 设计概述

Web 前端面向 KP 浏览器使用，提供比 CLI 更直观的可视化操作面板。前端通过 §7.2 的 REST API 与后端通信。

前端技术栈：
- **框架**：React + TypeScript + Vite
- **样式**：Tailwind CSS（utility-first，无需手写 CSS）
- **状态管理**：Zustand（轻量，无需 Redux 复杂度）
- **HTTP 客户端**：原生 fetch + React Query（缓存 + 自动重试）
- **图表**：Recharts（雷达图、时间线柱状图）

> **Mockup 工具**：使用 `/canvas-design` skill 在 implementation 阶段生成高保真 mockup 和交互原型。
> Wireframe 阶段的 ASCII 线框图先在本节给出，作为后续视觉设计的结构约束。

### 7.2 页面结构

```
┌──────────────────────────────────────────────────────────────────┐
│  KTSL KP Panel                                      [User] [⚙️]  │
├────────────┬─────────────────────────────────────────────────────┤
│            │                                                     │
│  Sidebar   │                  Main Content                       │
│            │                                                     │
│  Dashboard │  ┌─────────────────────────────────────────────┐   │
│  Session   │  │                                               │   │
│  Timeline  │  │  (Page Content 根据导航切换)                    │   │
│  Knowledge │  │                                               │   │
│  Barriers  │  │                                               │   │
│  Couplings │  │                                               │   │
│  Reports   │  │                                               │   │
│  Modules   │  │                                               │   │
│            │  │                                               │   │
│            │  └─────────────────────────────────────────────┘   │
└────────────┴─────────────────────────────────────────────────────┘
```

### 7.3 六个核心页面（Wireframe）

---

#### 页面 A: Dashboard（仪表盘）

**用途**：全局概览——当前 session 健康度、最新警报、快速操作入口。

```
┌──────────────────────────────────────────────────────────────────┐
│  Dashboard                                      Session: 警察·医院 │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─ Metrics Cards (6 卡片网格，每个一张小卡) ─────────────────┐   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐                    │   │
│  │  │ ⏱️ 因果   │ │ 🛡️ 未授权 │ │ 💧 泄露  │                    │   │
│  │  │   0      │ │   1      │ │   0      │                    │   │
│  │  │  ✓ 正常  │ │  ⚠ 警告  │ │  ✓ 正常  │                    │   │
│  │  └──────────┘ └──────────┘ └──────────┘                    │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐                    │   │
│  │  │ 🎯 Spot  │ │ 🔓 解密   │ │ 🔄 Retcon│                    │   │
│  │  │  25 min  │ │  0.97    │ │   0      │                    │   │
│  │  │  ✓ 正常  │ │  ✓ 正常  │ │  ✓ 正常  │                    │   │
│  │  └──────────┘ └──────────┘ └──────────┘                    │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─ 最新警报 (最近 3 个违反/警告) ────────────────────────────┐   │
│  │  ⚠ Event #S007: 因果违反（已 override）          [详情]    │   │
│  │  ⚠ Event #S003: 潜在信息泄露（已 flag）          [详情]    │   │
│  │  ✓ Event #S012: barrier B3 满足                   [详情]   │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─ 快速操作 ─────────────────────────────────────────────────┐   │
│  │  [+ 提交行动]  [📋 查看 Timeline]  [🧠 知识地图]          │   │
│  │  [💾 Save]     [📊 生成报告]     [🚪 Quit Session]        │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

#### 页面 B: Session（跑团交互）

**用途**：KP 在 Web 面板中提交行动、看到实时反馈——对应 CLI `ktsl session` REPL 的图形化版本。

```
┌──────────────────────────────────────────────────────────────────┐
│  Session: police_hospital                                        │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─ 行动提交区（底部固定栏） ─────────────────────────────────┐   │
│  │                                                            │   │
│  │  行动描述: [玩家佐藤翻找档案柜...........................] │   │
│  │                                                            │   │
│  │  角色: [佐藤 ▼]   场景: [hospital_records ▼]              │   │
│  │  可见性: [public ▼]                                       │   │
│  │                                                            │   │
│  │           [取消]  [提交行动 →]                              │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─ 事件滚动区（事件历史，类似聊天流） ───────────────────────┐   │
│  │                                                            │   │
│  │  ┌─ Event #S001 ──────────────────────────────────────┐   │   │
│  │  │ 👤 佐藤  @hospital_records   ✅ ALLOWED             │   │   │
│  │  │ "翻找档案柜"                                        │   │   │
│  │  │ → 获得信息: [info_07] 档案记录 (low)                │   │   │
│  │  └────────────────────────────────────────────────────┘   │   │
│  │                                                            │   │
│  │  ┌─ Event #S002 ──────────────────────────────────────┐   │   │
│  │  │ 👤 李    @street               ✅ ALLOWED            │   │   │
│  │  │ "跟踪佐藤"                                          │   │   │
│  │  │ → 看到: [info_07-summary] 佐藤在找某物 (medium)     │   │   │
│  │  └────────────────────────────────────────────────────┘   │   │
│  │                                                            │   │
│  │  ┌─ Event #S003 ──────────────────────────────────────┐   │   │
│  │  │ 👤 李    @street               ⚠️ WARN               │   │   │
│  │  │ "偷偷靠近听他们说话"                                 │   │   │
│  │  │ → ⚠ 潜在泄露: 李可能推断出 尸体位置 (high)          │   │   │
│  │  │   [Override] [Rollback] [Allow+Flag]                │   │   │
│  │  └────────────────────────────────────────────────────┘   │   │
│  │                                                            │   │
│  │  ...                                                       │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

#### 页面 C: Timeline（时间线）

**用途**：多场景并行时间线视图——类似视频编辑器的多轨时间轴。每个场景一条轨道，事件按时间排列。

```
┌──────────────────────────────────────────────────────────────────┐
│  Timeline                                      Session: 警察·医院 │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  场景筛选: [全部 ▼]  时间缩放: [===●====] 0min ──────── 120min   │
│                                                                  │
│  ┌─ hospital_wing ───────────────────────────────────────────┐   │
│  │  ●──────●────────●                                        │   │
│  │  0min   15min     30min                                   │   │
│  │  #S001  #S004    #S007                                    │   │
│  │  搜查   审问      ⚠ 跳过barrier                            │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─ street ───────────────────────────────────────────────────┐   │
│  │  ●────────●                                                 │   │
│  │  0min      20min                                           │   │
│  │  #S002     #S003                                           │   │
│  │  跟踪      ⚠ 偷听                                          │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─ old_house ────────────────────────────────────────────────┐   │
│  │  🔒 (locked: 需要 barrier B3 satisfied)                    │   │
│  │                                                            │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─ 事件详情面板（点击事件后展开） ────────────────────────────┐   │
│  │                                                            │   │
│  │  Event #S003                                               │   │
│  │  ├─ Actor: 李                                               │   │
│  │  ├─ Scene: street                                          │   │
│  │  ├─ Action: "偷偷靠近听他们说话"                             │   │
│  │  ├─ Status: ⚠️ WARN (potential leak)                       │   │
│  │  ├─ Output Info:                                           │   │
│  │  │   └─ [info_07-summary] 佐藤在找某物 (medium, partial)   │   │
│  │  ├─ Causal Dep: satisfied (event #S002 committed)          │   │
│  │  └─ Visibility: public                                     │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

#### 页面 D: Knowledge Map（知识地图）

**用途**：可视化"谁知道什么"——交互式矩阵，行是角色，列是信息条目。

```
┌──────────────────────────────────────────────────────────────────┐
│  Knowledge Map                                 Session: 警察·医院  │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  筛选: 信息敏感度 [全部 ▼]  信息类型 [全部 ▼]  搜索: [......]    │
│                                                                  │
│  ┌─ 知识矩阵 ─────────────────────────────────────────────────┐   │
│  │                                                            │   │
│  │  Info ╲ Role │  佐藤  │  李   │  王   │  NPC_医生         │   │
│  │  ────────────┼────────┼───────┼───────┼──────────────     │   │
│  │  info_01     │  📖初始 │ 📖初始 │   ·   │    ·             │   │
│  │  搜查令(low) │        │       │       │                  │   │
│  │  ────────────┼────────┼───────┼───────┼──────────────     │   │
│  │  info_07     │  📖#001│  👁#003│   ·   │    ·             │   │
│  │  档案(low)   │ 🟢know │ 🟡obs │       │                  │   │
│  │  ────────────┼────────┼───────┼───────┼──────────────     │   │
│  │  info_12     │  📖#005│  ⚠泄露│   ·   │  📖#init          │   │
│  │  尸体(high)  │  🔴know│ 🟠hint│       │  🔴know          │   │
│  │  ────────────┼────────┼───────┼───────┼──────────────     │   │
│  │  info_15     │   ·    │   ·   │   ·   │  🖤keeper         │   │
│  │  真凶(keeper)│        │       │       │                  │   │
│  │                                                            │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  图例: 📖 know (知道)  👁 obs (看到)  ⚠ leaked (泄露)            │
│        🟢 low  🟡 medium  🔴 high  🖤 keeper                    │
│                                                                  │
│  点击单元格查看详情:                                              │
│  ┌─ 选中: info_12 × 李 ───────────────────────────────────────┐   │
│  │  状态: ⚠️ 潜在泄露 (leaked)                                │   │
│  │  内容: 老宅地下室有一具尸体 (high)                          │   │
│  │  李拥有: 暗示 (partial) — 从事件 #S007 佐藤的对话推断      │   │
│  │  应拥有: 否 (李当前不应该知道这件事)                        │   │
│  │  建议: 让佐藤在接下来的对话中避免提及，或正式解密该信息    │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

#### 页面 E: Barriers & Couplings（屏障与耦合）

**用途**：运行时状态面板——展示当前哪些 barrier 处于 waiting、哪些 coupling 被触发。

```
┌──────────────────────────────────────────────────────────────────┐
│  Barriers & Couplings                          Session: 警察·医院 │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─ Barriers ─────────────────────────────────────────────────┐   │
│  │                                                            │   │
│  │  B1 (hospital_wing → street)                               │   │
│  │  ●─────────●  satisfied                                    │   │
│  │  条件: event #S001, #S004                                  │   │
│  │  当前: 2/2  satisfied ✅                                   │   │
│  │                                                            │   │
│  │  B2 (street → old_house)                                   │   │
│  │  ●─────────○  waiting                                     │   │
│  │  条件: event #S008 (李进入老宅)                             │   │
│  │  当前: 0/1  waiting (缺少事件) 🔒                           │   │
│  │                                                            │   │
│  │  B3 (hospital_wing → old_house)                            │   │
│  │  ●─────────○  waiting                                     │   │
│  │  条件: info_07 (档案记录)                                  │   │
│  │  当前: 0/1  waiting (缺少信息) 🔒                           │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─ Couplings ────────────────────────────────────────────────┐   │
│  │                                                            │   │
│  │  C1: hospital_wing ↔ street                                │   │
│  │  耦合分数: 0.85   模式: linked    drift: +5min             │   │
│  │  角色重叠: 佐藤, 李                                        │   │
│  │  状态: 🟢 active (drift < 15min threshold)                 │   │
│  │                                                            │   │
│  │  C2: street → old_house                                    │   │
│  │  耦合分数: 0.40   模式: loose     drift: 0min              │   │
│  │  条件: not yet triggered (需要 barrier B2)                 │   │
│  │  状态: 🔴 locked                                           │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

#### 页面 F: Reports（报告中心）

**用途**：浏览、导出、对比历史 session 报告和 publish 报告。

```
┌──────────────────────────────────────────────────────────────────┐
│  Reports                                                         │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Tab: [Session Reports] [Publish Reports]                        │
│                                                                  │
│  ┌─ Session Reports 列表 ─────────────────────────────────────┐   │
│  │                                                            │   │
│  │  2026-07-04  police_hospital  ⏱ 45min  ✅ no violations  │   │
│  │  2026-07-03  police_hospital  ⏱ 32min  ⚠ 1 leak (flagged)│   │
│  │  2026-06-28  simple_library    ⏱ 28min  ⚠ 2 causal (over) │   │
│  │                                                            │   │
│  │  [导出 MD]  [导出 HTML]  [对比选中]                         │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─ 报告详情（点击后右侧预览） ────────────────────────────────┐   │
│  │                                                            │   │
│  │  Session Report: police_hospital_2026-07-04                │   │
│  │                                                            │   │
│  │  ┌─ Metrics Radar ────────────────────────────────────┐   │   │
│  │  │           Causal                                    │   │   │
│  │  │            ●                                        │   │   │
│  │  │     Retcon ●     ● Unauth                          │   │   │
│  │  │            ●     ●                                  │   │   │
│  │  │        Decl ●     ● Leak                           │   │   │
│  │  │              Spot                                   │   │   │
│  │  └────────────────────────────────────────────────────┘   │   │
│  │                                                            │   │
│  │  Summary:                                                  │   │
│  │  - Total events: 12 (11 committed, 1 overridden)          │   │
│  │  - Knowledge leaks: 1 (flagged, not escalated)            │   │   │
│  │  - Barriers resolved: 2/3                                  │   │
│  │                                                            │   │
│  │  [打开完整 HTML 报告]  [分享到玩家群]                        │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

### 7.4 交互模式设计

#### 实时推送

- Phase 1（本期）：前端轮询 `GET /session/{id}/state`，每 2 秒一次
- Phase 2（后续）：升级为 WebSocket 推送（事件提交后即时广播）

#### 冲突处理

- KP 在 Web 面板和 CLI 同时操作同一 session 时，以后端状态为准
- Web 面板显示 optimistic update，后端返回冲突时回滚并提示

#### 响应式布局

- 桌面（≥1280px）：完整 sidebar + 主内容双栏布局
- 平板（768-1279px）：sidebar 折叠为图标栏
- 手机（<768px）：单栏堆叠，底部固定快速操作栏

### 7.5 前端项目结构（预留）

```
web/
  package.json          # React + TypeScript + Vite + Tailwind
  tsconfig.json
  vite.config.ts
  tailwind.config.js
  src/
    main.tsx
    App.tsx             # Router + Layout
    pages/
      Dashboard.tsx
      Session.tsx
      Timeline.tsx
      KnowledgeMap.tsx
      BarriersCouplings.tsx
      Reports.tsx
      Modules.tsx
    components/
      MetricsCard.tsx
      EventCard.tsx      # Session 页面中的事件卡片
      KnowledgeMatrix.tsx
      TimelineTrack.tsx
      RadarChart.tsx
      AlertFeed.tsx
      ActionSubmitBar.tsx
    hooks/
      useSession.ts      # React Query hook wrapper
      useSessionState.ts
    api/
      ktslClient.ts      # fetch wrapper
    store/
      sessionStore.ts    # Zustand store
    types/
      ktsl.ts            # 与后端对应的 TS 类型
```

### 7.6 设计与实现路径

```
Phase 1 (本期，spec 范围):
  ├─ Wireframe (本节 ASCII 线框) — 已完成
  ├─ REST API 实现 (§8 Web 骨架 Backend) — 与 Layer 4 同步开发
  └─ 前端项目 scaffold (上述目录骨架 + 空壳组件)

Phase 2 (后续 implementation plan):
  ├─ 使用 /canvas-design skill 对六个核心页面做高保真 mockup
  ├─ 组件实现 + 状态接入
  └─ 交互打磨 (动画、响应式、键盘快捷键)
```

> **TODO (Implementation Phase)**：在开始前端开发前，对 Dashboard、Session、Timeline、Knowledge Map、Barriers & Couplings、Reports 六个页面分别调用 `/canvas-design` skill 制作高保真 mockup，用户确认后再开始组件实现。

---

## 8. Web 骨架（Backend）

### 8.1 FastAPI Router

```python
# src/scenario/web/ktsl_router.py

router = APIRouter(prefix="/ktsl", tags=["ktsl"])

# 内存状态暂存（后续可换数据库）
_SESSION_STORE: dict[str, SessionAuditTracker] = {}

@router.post("/validate")
async def validate_fixture(...): ...

@router.post("/session")
async def create_session(...) -> SessionCreated:
    """创建 SessionAuditTracker 实例，返回 session_id"""

@router.post("/session/{session_id}/events")
async def submit_event(session_id: str, action: ActionInput) -> AuditResult:
    """流式输入事件"""

@router.get("/session/{session_id}/state")
async def get_session_state(session_id: str) -> SessionStateSnapshot:
    """当前 metrics + knowledge map"""

@router.get("/session/{session_id}/timeline")
async def get_scene_timeline(session_id: str, scene_id: str | None = None): ...
    """场景时间线 JSON"""

@router.get("/session/{session_id}/report")
async def get_report(session_id: str, format: Literal["md", "html"] = "md"): ...

@router.delete("/session/{session_id}")
async def destroy_session(session_id: str): ...
```

### 8.2 与现有 API 的集成

- 检查 `src/scenario/api.py` 中是否已有 FastAPI 实例
- 直接注册 `ktsl_router`
- Phase 1（本期）：只注册路由和 handler stub，handler 调用 Layer 4 Orchestration 层
- Phase 2（后续）：加入 WebSocket 推送 + 前端面板

---

## 9. 异常处理

| 场景 | 处理方式 |
|------|---------|
| KP 输入在 fixture 中无匹配 clue | 返回 `resolution: "unresolved"`，提示 KP 用 `manual_overrides` |
| 提交事件触发 causal violation | 默认 **warn only**（KP override），记录并累积 metrics |
| barrier 永远无法满足（死锁） | `validate` 静态检测 + `session` 提交时动态检测，报 BLOCKED |
| Actor 不存在于 SceneCard participants | 自动加入（临时出场）+ 黄色警告 |
| Session 中触发 keeper-only 信息 | 自动 `redacted`，知识地图中不显示角色知道该信息 |
| Session save/load 反序列化失败 | 降级为"新 session 开始"，不崩溃 |
| fixture YAML schema 校验失败 | 输出人类可读的错误定位（行号、字段名） |
| PublishGate 缺失某指标的 threshold | 默认跳过该指标（soft gate），输出 warning |

---

## 10. 数据流全景

### 10.1 Session 模式（实时跑团）

```
KP 输入 ──→ [RuntimeEventAdapter.parse_action()] ──→ EventRecord
                                                         │
    ┌────────────────────────────────────────────────────┘
    ▼
[SessionAuditTracker.submit_action()]
    │
    ├─→ [Schedule 层]──→ barrier update / causal check
    ├─→ [Filter 层]──→ authorized? / leak check
    ├─→ [Coupling 层]──→ drift check / trigger barrier
    │
    ├─→ 更新 knowledge_state
    ├─→ 更新 metrics
    ├─→ 追加 violations
    │
    └─→ 返回 AuditResult

session quit ──→ [SessionReport 数据收集]
                     ├─→ [MarkdownRenderer]  → .md
                     └─→ [HTMLRenderer]       → .html
```

### 10.2 Publish 模式（发布验证）

```
fixture.yaml + criteria.yaml
        │
        ▼
[PublishGate.evaluate()]
    │
    ├─→ Run simulate(baseline)      → ModeResult
    ├─→ Run simulate(schedule_only) → ModeResult
    ├─→ Run simulate(ktsl_full)     → ModeResult
    │
    ├─→ 逐指标对比 thresholds
    ├─→ 汇总 failures
    │
    └─→ PublishGateResult
        │
        ├─→ [MarkdownRenderer]  → publish-report.md
        └─→ [HTMLRenderer]       → publish-report.html (含雷达图)
```

---

## 11. 文件级实施顺序

建议按以下顺序实现，每个阶段可以独立测试：

1. **Layer 4 核心**：`SessionAuditTracker` + `RuntimeEventAdapter`
   - 依赖：仅现有 ktsl 模块
   - 测试：Tracker 能加载 fixture、submit_action 返回正确 AuditResult
2. **Layer 4 门槛**：`PublishGate`
   - 依赖：现有 evaluate 模块
   - 测试：三条件对照模拟 + 阈值判定
3. **Layer 3 报告**：`MarkdownRenderer` (先 MD，零额外依赖)
   - 依赖：SessionReport / PublishGateResult 数据模型
   - 测试：render 输出符合预期结构
4. **Layer 3 报告**：`HTMLRenderer`（引入 Jinja2）
   - 依赖：Jinja2、模板文件
   - 测试：渲染后 HTML 可离线打开
5. **Layer 5 CLI**：`ktsl_cli.py`
   - 依赖：Layer 3 + Layer 4 完成
   - 测试：四个子命令端到端冒烟
6. **Layer 5 Web Backend**：`ktsl_router.py`
   - 依赖：Layer 4 完成，现有 FastAPI 实例
   - 测试：curl 调用各端点返回 200 + 正确 JSON
7. **Layer 5 Web Frontend**：`web/` 项目 scaffold + 空壳页面
   - 依赖：Layer 5 Web Backend 可用
   - 测试：Vite dev server 启动、页面路由可访问
8. **Web UI Mockup + 实现**：对 6 个核心页面逐一调用 `/canvas-design` skill → 用户确认 → 组件实现
   - 依赖：Layer 7 完成 + /canvas-design mockup 确认
   - 测试：端到端页面功能 + 视觉还原度自检

---

## 12. 不在范围内（Out of Scope）

以下功能有意留给 v2：

- LLM 驱动的 clue 语义匹配（当前用关键词 + 编辑距离）
- 多 KP 协作标注 + Cohen's κ 计算
- Web 前端面板的高保真 mockup（预留具体视觉设计到 implementation phase，通过 /canvas-design skill 完成）
- Session 数据库持久化（当前内存 save/load JSON）
- 盲审 / 去标识化（不适用于 KP 全知场景）
- 实时 WebSocket 推送
- 模组市场 / 分发平台集成

---

## 13. 验收标准

| 编号 | 标准 | 验证方式 |
|------|------|---------|
| AC1 | `ktsl validate` 能检测出 simple_library / police_hospital 两个现有 fixture 的结构完整性 | 跑两个现有 fixture，exit code = 0 |
| AC2 | `ktsl audit` 对 police_hospital 模组的"搜查"动作给出正确的 output_info 列表 | 命令行为快照测试 |
| AC3 | `ktsl session` 能完整跑通 police_hospital 的关键路径（至少 5 个事件提交，1 个 barrier 触发，最终 report 有知识地图） | 端到端集成测试 |
| AC4 | `ktsl publish` 对 police_hospital + 默认阈值给出 PASS 判定 | 命令行为快照 + HTML 报告存在 |
| AC5 | Session Report HTML 中知识地图显示内容摘要（非仅 info_id） | HTML 渲染输出断言 |
| AC6 | `ktsl replay` 从保存的 JSON 状态恢复并生成报告 | 端到端集成测试 |
| AC7 | FastAPI 骨架所有路由返回 200 + 正确 JSON schema | API 冒烟测试 |
| AC8 | 全部新代码有测试覆盖，所有测试在 `pytest tests/scene/test_ktsl_*.py` 通过 | CI |
| AC9 | Web 前端六个核心页面 wireframe + mockup 通过用户评审 | 用户签字确认 mockup 后进入实现 |

## 14. 设计决策记录

### D1: 为什么不重写现有 schedule/filter/coupling 逻辑？

现有三层逻辑已经由 `evaluate` 模块在确定性 fixture 上验证过。SessionAuditTracker 只在"事件输入端"新增一个 Adapter，内部检测完全复用。这保证了评估逻辑的一致性。

### D2: 为什么默认 warn-only 而非 block？

现实跑团中 KP 可能需要故意破规（如剧情需要让角色提前知道某事）。Block 模式会导致 KP 频繁被工具打断体验。Warn-only 既保留了审计追踪，又不干扰叙事自由。KP 可以通过 `override --commit` 明确覆盖。

### D3: Jinja2 vs 纯字符串拼接？

Markdown 走 f-string 保证零依赖且易于 Obsidian/Notion 消费。HTML 走 Jinja2 因为模板复杂度高（嵌套循环、条件渲染、inline SVG），f-string 的可维护性差。Jinja2 是成熟库，不引入外部 CDN。

### D4: Web 骨架先做 REST 而非 WebSocket？

REST 足以覆盖 v1 需求（移动端/桌面端轮询即可）。WebSocket 用于实时推送，增加复杂度和测试难度，留给 v2。

### D5: RuntimeEventAdapter 为什么不做 LLM 语义匹配？

LLM 调用引入延迟和成本，不适合跑团中实时使用。关键词 + 编辑距离在 fixture clue 数量有限（< 50）的情况下足够。如果 clue 量大，v2 可以加入向量化检索。
