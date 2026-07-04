# KTSL 协议运行时集成设计

> 状态: 已批准 · 创建: 2026-07-05

## 0. 目标与非目标

本设计把论文中已经**以确定性 fixture oracle 实现**的 KTSL 协议（`src/scenario/ktsl/`）进一步**集成到实际跑团运行时的回合结算管线中**，使 KTSL 从"跑在旁边的审计员"变为"嵌在运行时里的防线"。

同步补齐论文中缺失的四类运行时组件（KP 语言细则、一页式清单、最小数据模板、评估标注手册），其统一原则是 **Agent 掌握全场信息**——所有 SceneCard/EventRecord/InfoLabel/EventRecord 集中在一处 Ledger 中，KTSL 的论文组件就是 Agent 的界面、检查清单和视图。

### 非目标

- 本设计**不**改变规则引擎的骰子/检定/效果判定——那是 `RuleEngine` 的职责，KTSL 只做"能不能做"和"能不能说"。
- 本设计**不**替代 Plan/Render Agent 做叙事判断——Agent 仍然决定"怎么写"，KTSL 只决定"能写什么"。
- 本设计不落地 Web Analyst 面板；分析可视化走 CLI 脚本输出终端 + 离线 JSON bundle。

## 1. 架构：Stage 协议 + Ledger + 管线

### 1.1 数据放置

```
SessionMapState
  └─ ktsl_ledger: KTSLLedger              ← 新增一等公民
        • scenes: dict[scene_id, SceneCard]
        • events: list[EventRecord]        ← append-only log
        • info_labels: dict[info_id, InfoLabel]
        • couplings: list[SceneCoupling]
        • knowledge: dict[char_id, ActorKnowledgeState]
        • mode: Mapping[scene_id, CouplingMode]
        • overrides: list[KTSLOverrideRecord]
        • narration_rules: KTSLPromptTemplateSet
```

`KTSLLedger` 归入 `SessionMapState` 而不是独立存在。理由：

- 单源持久化——`JsonScenarioStateStore` 零改动。
- `resolve_turn_locked` 现有的 `.model_copy(deep=True)` 机制自动把 ledger 一起快照。
- Prompt Adapter 从 `StageContext.snapshot` 读，不引入第二条数据通路。

### 1.2 Stage 协议

```python
class TurnStage(Protocol):
    name: str
    def run(self, ctx: StageContext) -> StageResult: ...

class StageContext:
    snapshot: SessionMapState           # 深拷贝快照，只读
    ledger: KTSLLedger                 # 同上，快捷访问
    scene: ModuleScene                 # 当前场景
    intents: list[(player_id, dict)]   # 本场次待结算意图
    event_log: list[RuntimeEvent]      # 累积事件
    scratch: dict[str, Any]            # stage 间通信

class StageResult:
    status: Literal["continue", "blocked", "wait"]
    interventions: list[KTSLIntervention]
    audit_deltas: list[KTSLAuditDelta]
```

Stage 不直接修改 snapshot——它们通过 `scratch` 通信，由管线最终把 `scratch` 中以 `commit_` 为前缀的项写入 ledger。这保证了 stage 顺序的重排不会改变副作用语义。

### 1.3 resolve_turn_locked 重构

**重构前**（现有）：`resolve_turn_locked` 是一个 ~900 行的平铺方法，stage 间通过局部变量和注释块分界。

**重构后**：

```python
async def _resolve_turn_locked(self, session_id, *, expected_turn=None):
    # ... 前置校验（现有） ...
    snapshot = session.model_copy(deep=True)
    ledger = snapshot.ktsl_ledger or KTSLLedger.empty(session.module_id)
    ctx = StageContext(snapshot=snapshot, ledger=ledger, event_log=event_log, ...)
    
    for scene in module.scenes:
        ctx.scene = scene
        ctx.intents = grouped_intents.get(scene.id, [])
        if not ctx.intents:
            continue
        
        for stage in self._ktsl_pipeline:          # ← 注入点
            result = stage.run(ctx)
            event_log.extend(result.to_events())
            if result.status == "blocked":
                ctx.mark_blocked(result.interventions)
                break
        
        # 把 scratch 中的 commit_* 写入 ledger
        ctx.commit_scratch_to_ledger()
    
    # ... 收尾（story / clock / render）（现有）...
    return TurnResolution(..., ktsl_audit=ctx.audit_summary())
```

**stage 链（完整启用时的 M3 子集）**：

```
ScheduleGate → Plan[注入KTSL] → Rule → Filter[render] → CouplingDrift → Audit
```

`self._ktsl_pipeline` 是可替换的 stage 列表——M1/M2/M3 阶段通过"启用不同 Stage 子集"推进，而不是 if/flag 开关。三个阶段的 stage 子集：

| 阶段 | 启用的 Stage | 入口位置 |
|---|---|---|
| M1 | `WizardStage`, `SchemaValidatorStage` | session 创建 wizard（在 engine 之外） |
| M2 | `SubmitCheckStage` | `submit_intent()` 末尾拦截 |
| M3 | `ScheduleGate`, `Filter`, `CouplingDrift`, `Audit` | `resolve_turn_locked()` stage pipeline |

### 1.4 里程碑边界

里程碑是**进度判断的硬闸门**，不是功能切分——每启用下一个 Stage 子集必须所有闸门同时亮灯：

- **M1**：Wizard 流程 + Schema 校验 + 持久化产出初始 ledger。验证命令：`ktsl wizard`。
- **M2**：提交时刻三层浅校验。验证命令：`ktsl validate-session` + 游戏 submit_intent 实测。
- **M3**：全管线 stage 链接入引擎。验证：完整 paper fixture 端到端运行。

## 2. 数据流：三条链路在 Ledger 处汇合

### 2.1 M1 链路 — 开团前准备

```
CLI `ktsl wizard <module_id>`
   ↓ (1) 加载 module schema → 列出 scene_map / lorebook / clues
   ↓ (2) 交互式引导：
   ↓     ① 为每个关键场景建 SceneCard（参与者/初始模式/时间窗）
   ↓     ② 为每条核心线索建 InfoLabel（敏感度/owner/授权受众/降密条件/public 摘要）
   ↓     ③ 计算 SceneCoupling（共享线索/倒计时/资源 → 评分 → 模式选择）
   ↓     ④ 写入 ActorKnowledgeState（初始 know/obs 集）
   ↓ (3) SchemaValidatorStage 校验：
   ↓     - settleable action 都有因果边；
   ↓     - 高敏 payload 都有 redaction；
   ↓     - 时间窗不自相矛盾
   ↓ (4) 生成 KTSLLedger → 注入 SessionMapState → 落盘
```

**论文四组件在 M1 变现**：

- **一页式 KP 清单** → wizard 强制性步骤，五步走不完拒绝启动。
- **最小数据模板** → `ModuleDefinition.ktsl_spec` 的 JSON Schema 校验规则（是 wizard 的输入约束）。
- **评估标注手册** → wizard 终态告知"本场游戏将自动采集的指标和标注方式"。
- **KP 语言细则** → wizard 每步的话术示例（"这条线索如果玩家旁听，你应说……"）。

### 2.2 M2 链路 — 行动提交拦截

```
PlayerTable → submit_intent(player_id, intent)
   ↓ SubmitCheckStage：
   ↓   a. RuntimeEventAdapter.parse_action(text, scene, committed_ids)
   ↓   b. 命中 fixture clue → 得到 EventRecord 草稿；未命中 → 解析为 Freeform
   ↓   c. Schedule 检查：depends_on 事件是否已 committed → blocked / shifted time
   ↓   d. Filter 检查：output_info 是否需要 redaction → 决策写入 ctx.scratch
   ↓   e. Coupling 检查：本 scene 是否已 drifting → 输出 wait_cost 警告
   ↓ 通过后写入 pending_intents；未通过则拒绝
```

**关键边界**：M2 只做"前置过滤"——仅能看到已 committed 事件和当前 intent 自身。跨玩家因果依赖留给 M3。

### 2.3 M3 链路 — 回合结算（Stage 链注入 Agent）

```
resolve_turn_locked stage pipeline:
   snapshot = session.model_copy(deep=True)
   ctx = StageContext(snapshot, ledger, event_log)
   
   for scene in module.scenes:
       ctx.scene = scene
       ctx.intents = grouped_intents[scene.id]
       
       for stage in pipeline:
           result = stage.run(ctx)
           ...
```

各 stage 具体行为：

| Stage | 读 | 写（scratch） | 失败行为 |
|---|---|---|---|
| **ScheduleGate** | ledger 已 committed 事件 + context deps | `commit_schedule_order[]` | BLOCK 含 wait_cost |
| **Plan** | 现有 PromptBuilder + KTSLPromptAdapter.build_plan 追加 KTSL section | `plan_agent_call(inputs)` | Plan Agent 调用失败走现有 noop |
| **Filter** | InfoLabel 过滤 + 授权受众 | `filter_decisions[char_info]` | info 缺失时默认 REDACT（较重者） |
| **CouplingDrift** | SceneCoupling.mode + committed 时间窗 | `drift_adjustments[]`（仅标记） | drift 不阻塞，进 audit |
| **Audit** | 全 scratch 集合 | `audit_entries[]` + `audit_metrics_summary` | 不可能失败（纯计算） |

**每回合结算后**：`EventRecord` 中 settleable 的 events 被 append 到 `ledger.events` 并标记 committed——下一回合的因果边在此基础上生长。

## 3. 错误处理：三种干预 + Override 链

### 3.1 三种干预

```python
class KTSLIntervention(Enum):
    ALLOW = "allow"
    REDACT = "redact"
    BLOCK = "block"
```

力量排序：**BLOCK 永远来自前置事件因果和授权链；REDACT 永远来自输出过滤。** 两者不重叠。

| 层级 | 力度 | 触发条件 |
|---|---|---|
| **M2 submit** | BLOCK | 引用未 committed 前置事件 / 引用角色 know 集中不存在的高敏 info |
| **M3 schedule** | BLOCK / WAIT | 同步屏障未满足 / 同场景行动顺序错乱 |
| **M3 filter** | REDACT | 高敏 info 授权受众不含当前角色 |

### 3.2 回退路径

```
① SUBMIT→BLOCK:
   engine 抛 KTSLBlockError(reason, blocked_by_info_ids)
   → 前端 PlayersTable 显示具体拒绝原因
   → 玩家可以重写；或 override 走 KP 人工裁定

② SCHEDULE→WAIT:
   barrier 含 "等 P1 查完电话后" → Plan Agent 看到 wait_cost 消息
   → Plan Agent 决定先做其他行动 / 宣布 montage 跳过 / 接受等待

③ FILTER→REDACT:
   ctx.filter_decisions 中 event→info→character 标记为 redacted
   → Render Agent 收到带 redaction 文本的叙述草稿（由 KTSLPromptTemplates.render_redacted 生成）
   → 或 KP Agent 选择主动降密
```

### 3.3 Override 链

```
默认 → KTSL 自动判定
         ↓ 拒绝
KP 判定有合法推理桥
         ↓
Override: ktsl override <intervention_id> --reason "..." --type {force_allow, force_block, declassify}
         ↓
写入 ledger.overrides[] + 关联干预的 override_chain_id
         ↓
下一回合 audit 对应项 nullified（override 不算违反，但进审计留痕）
```

### 3.4 灰区处理（论文 §12.4）

KTSL 不确定性时选择 BLOCK/REDACT 中的较重者，但留下 `expected_declassified_for_character_ids`。若后续回合信息真的通过合法路径进入角色知识集，audit_leak 自动从 error 降级为 info。

### 3.5 持久化一致性

```
resolve_turn_locked 锁内:
  1) KTSL stage 链跑完 → decisions + audit entries + next-committed 集合
  2) committed events append 到 ledger.events
  3) ktsl_audit 写入 TurnResolution
  4) 原子写入 JSON store（现有 _persist_session）
  
  任何一步异常 → 整轮回退（现有 engine 行为），ledger 不被污染
```

## 4. Agent 集成 + 论文四组件形态

### 4.1 KTSLPromptAdapter

```python
class KTSLPromptAdapter:
    """读 ledger，写 prompt 片段——不持有状态，纯增量。"""
    
    def build_plan_context(self, ledger, scene, intents, ctx) -> PlanPromptExtras:
        return PlanPromptExtras(
            coupling_summary=coupling_ledger.snapshot(scene.id),
            barrier_debt=barrier_ledger.open_barriers(scene.id),
            wait_warnings=[w for w in ledger.wait_warnings if w.scene_id == scene.id],
            pending_causal_edges=[
                (e.action_text, e.depends_on_event_ids)
                for e in ledger.events
                if e.scene_id == scene.id and e.status == "proposed"
            ],
        )
    
    def build_render_context(self, ledger, filter_decisions) -> RenderPromptExtras:
        return RenderPromptExtras(
            per_character_filter=group_by_character(filter_decisions),
            narration_directives=ledger.narration_rules,
        )
```

注入方式：扩展 `PromptBuilder.build()`，在最后追加一个 "KTSL 上下文" section。**不改变** `KeeperPlanAgent` / `KeeperRenderAgent` 现有接口——prompt adapter 是纯增量。

### 4.2 论文四组件落地点

| 论文组件 | 代码位置 | 运行时形态 |
|---|---|---|
| **一页式 KP 清单** | `src/scenario/cli/ktsl_cli.py` + `WizardStage` | `ktsl wizard` 强制走完 5 步；create_session 时若发现 ledger 缺失则拒绝并提示运行 wizard |
| **最小数据模板** | `src/scenario/module/models.py` + `ModuleDefinition.ktsl_spec` | module.yaml 新可选字段 `ktsl_spec`：{scenes, info_labels, couplings, initial_knowledge}；SchemaValidatorStage 校验 |
| **评估标注手册** | `src/scenario/ktsl/audit.py` + `TurnResolution.ktsl_audit` | 自动写入四类违规；CLI `ktsl analyst` 输出"手册格式"标注表；每回合落盘 |
| **KP 语言细则** | `src/scenario/ktsl/prompt_templates/`（新增目录） | 灰区/broadcast/private/redaction 四类叙事模板，供 KP Agent 在 override 或 ambiguous 时填充；模板参数化 |

### 4.3 持久化扩展

```
SessionMapState 新增字段:
  ktsl_ledger: Optional[KTSLLedger]        # 运行时装载
  ktsl_spec: Optional[ModuleKTSLSpec]       # module 静态定义引入

ModuleDefinition 新增字段:
  ktsl_spec: Optional[ModuleKTSLSpec]       # YAML 可选模块

KTSLFixture 保留现状（离线评估用）:
  `ktsl migrate <fixture_id>` → 生成 wizard 预填文件 (M3 快照)
```

## 5. 日志 + Analyst 终端落地

### 5.1 决策日志（每回合落盘）

```
log/session/{session_id}/ktsl/{turn_no}/
  ├─ stage_trace.jsonl          每个 stage 输入指纹 + 输出决策 + 耗时ms
  ├─ agent_context_plan.json    KTSLPromptAdapter 输出快照（不含全文 prompt）
  ├─ agent_context_render.json
  ├─ interventions.jsonl        被 BLOCK/REDACT/WAIT 的每条:
  │     turn, layer(M2_submit/M3_schedule/M3_filter),
  │     player, scene, character, info_id,
  │     reason_code, reason_text, override_chain_id|null
  ├─ ledger_diffs.jsonl         该回合增量:
  │     new_committed_events[], updated_actor_knowledge[],
  │     barrier_satisfied[], drift_adjustments[]
  └─ audit_snapshot.json        MetricSummary 完整快照
```

**约束**：
- `stage_trace.jsonl` 完整 recording——事后可 trace "为什么被拦截"每一跳。
- `interventions.jsonl` 是 analyst 工作原材料——可直接加载进 CLI，不需再 query ledger。
- 每回合文件 self-contained——不依赖前一回合也能读。

### 5.2 Analyst CLI

```
CLI 入口:
  ktsl analyst <session_id>
    --format {table, json}
    --turn <turn_no>
    --focus {causal, knowledge, interventions, wait, modes, metrics}
    --export <path.zip>

终端输出示例:
  ┌─────┬─────────┬────────┬──────────┬──────────┬──────────┐
  │turn │ causal  │ leak   │ unauth   │ wait_min │ drift_m  │
  ├─────┼─────────┼────────┼──────────┼──────────┼──────────┤
  │  1  │    0    │   0    │   0      │    0     │    0     │
  │  2  │  1 ⚠   │   0    │   0      │  8 min   │    0     │
  │  3  │    0    │  1 ⚠   │   0      │  0       │ 12 ⚠    │
  └─────┴─────────┴────────┴──────────┴──────────┴──────────┘
  Focus: interventions @ T2
    └─ P2 │ info_I12 │ BLOCK │ schedule:precond
       └─ override_chain: none
       └─ related_committed: [evt_L_library_find]
```

| 焦点 | 数据来源 | 用途 |
|---|---|---|
| `causal` | ledger_diffs 内 new_committed_events | 验证"后果是否真的在原因之后" |
| `knowledge` | actor_knowledge diffs + obs/know 交叉 | 泄露可视化——何时 obs 领先 know |
| `interventions` | interventions.jsonl | 每回合逐决策审计 |
| `wait` | schedule stage wait_cost per action | spotlight 公平性：谁等了多久 |
| `modes` | coupling.mode per scene | 同步强度时变可视化 |
| `metrics` | audit_snapshot.json | 回合指标时间线 |

**Analyst 事后操作**：
- `--turn N` drilldown 进入单回合
- `--focus causal` 用文本 adjacency list 输出因果图
- `--export <path.zip>` 打包决策 bundle + audit snapshot + 标注反馈 JSON（供人工标注）

## 6. 测试与 Milestone 闸门

### 6.1 分层测试

| 层次 | 覆盖 | 方式 | belong to |
|---|---|---|---|
| **Stage 单元** | 单层 stage 决策正确性 | fixture 输入 → stage.run() → 决策快照对比 | M1/M2/M3 各自 |
| **管线集成** | resolve_turn_locked 全管线 | fixture → 管线 → ktsl_audit + event 数组计数 | M3 |
| **Agent 注入** | Prompt Adapter 输出确定性结构 | 固定 ledger → build_plan_context 结构字段校验 | M3 |
| **回退** | BLOCK/WAIT/REDACT + override | 构造违例 fixture → 对应干预 | M2+M3 |
| **持久化** | session save/load 后 ledger 不变 | 运行中止 → reload → 再结算 → 产出一致 | M3 |

### 6.2 Milestone 闸门

**M1 闸门（Wizard + Schema）**：

① `ktsl wizard` 不带 `--skip` 走完 5 步，产出 JSON ledger。
② 漏填 `info_label.sensitivity` → SchemaValidatorStage 输出字段路径报错。
③ 跳过 wizard 直接 create_session → engine 拒绝并提示"missing ktsl_ledger"。
④ 初始 ledger JSON 每字段有来源 trace。
⑤ log/ 存在初始 ledger 快照。

**M2 闸门（Submit 拦截）**：

① submit 引用未 committed 前置 → BLOCK + 错误含前置 ID。
② submit 引用授权不足 info → BLOCK。
③ submit 引用已 committed 前置 + 授权 info → ALLOW + 入 pending。
④ override reject → interventions.jsonl 含完整 `override_chain_id`。
⑤ 每次 submit_intent KTSL 决策都落 interventions.jsonl（即使 ALLOW）。

**M3 闸门（Resolve 全管线）**：

① 完整跑 paper 图书馆/下水道/教堂 fixture → audit_metrics 与 paper 期望锚点一致。
② barrier → wait_cost 发生 + Plan Prompt 出现 barrier_debt。
③ 高敏 info 经过 render → public_payload 替换 payload。
④ save → reload → 再次结算一致。
⑤ 两回合因果链：P1 查资料 → P2 电话 → P1 第二回合去祭坛 → 第二回合 audit 零 causal_violation。
⑥ 跑完 5 回合游戏后 `ktsl analyst` 终端输出所有焦点有数据。
⑦ 故意设计的两类违规（因果前置未满足 + 跨玩家情报泄露）在 analyst 正确高亮。

### 6.3 Anti-illusion 四灯原则

每个 M 必须**同时达成**：

1. ✅ 所有新 fixture 三个 run mode（baseline / schedule_only / ktsl_full）跑通。
2. ✅ Stage 单元测试数量增加 ≥5 条。
3. ✅ 用户可触达命令每条端到端演示通过（不只是 test 通过）。
4. ✅ M3 engine 改造前/后 resolve_turn_locked 行为不变——以现有 `tests/scene/test_runtime*.py` 为回归基准。

四灯全亮才视为 M 完成；任一不亮不算。

## 7. 已确认的设计决策快照

| 问题 | 决策 |
|---|---|
| 论文四组件补齐深度 | 完全运行时集成，Agent 掌握全场信息 |
| 运行时接入模式 | Stage pipeline 切片（C），不直插 engine |
| Agent 集成方式 | 两阶段都注入（A），扩展 PromptBuilder 不改 agent 接口 |
| submit_intent vs resolve_turn | 分层——submit 做浅前置检查（单玩家可判），resolve 做深挖（跨玩家因果/屏障/漂移） |
| Analyst 落地形态 | CLI 终端 + JSON bundle，不落地 Web |
| 里程碑顺序 | M1（Wizard+Schema）→ M2（Submit 拦截）→ M3（Resolve 全管线） |

## 8. 文件清单（计划中涉及）

```
src/scenario/
  runtime/
    engine.py                          # 重构 resolve_turn_locked，加 _ktsl_pipeline 注册器
  session/
    state.py                          # 新增 ktsl_ledger / ktsl_spec 字段
  ktsl/
    models.py                         # 新增 KTSLLedger / OverrideRecord / NarrativeRules
    stages.py                         # 新增 WizardStage/SubmitCheckStage/ScheduleGate/Filter/CouplingDrift/Audit
    prompt_adapter.py                 # 新增 KTSLPromptAdapter
    prompt_templates/                 # 新增：灰区/broadcast/private/redaction 四类模板
    wizard.py                         # 新增：ktsl wizard 交互式流程
§  cli/
    ktsl_cli.py                       # 扩展：wizard / validate-session / analyst / override
  report/
    analyst_renderer.py               # 新增：终端表格 + focus 过滤
tests/scene/
  test_ktsl_stages.py                # Stage 单元测试
  test_ktsl_pipeline.py              # 管线集成测试
  test_ktsl_wizard.py                # Wizard + Schema 校验测试
  test_ktsl_analyst.py               # CLI analyst 输出测试
  test_ktsl_runtime_bridge.py        # engine + KTSL 联动测试
```
