# FateGear 未完成能力需求细化

日期：2026-07-05

## 目标

本文把当前 README 中列出的 6 个未完成方向拆成可进入后续 Plan / Architecture / Execution 阶段的需求规格。范围包括 KTSL 真实模组启用、真实 transcript 证据层、CoC 规则扩展、ClueGraph、认证授权、产品化持久化与观测。

本规格不是实现计划，也不是代码变更清单。它先回答“要做到什么程度才算完成”，避免后续实现时把原型状态误判为产品状态。

## 总体约束

- 权威事实边界：模组静态事实来自 YAML，运行事实来自 `SessionMapState`，规则事实来自 `RuleEngine`，剧情迁移来自 `TransitionValidator`，KTSL 事实来自 `KTSLLedger`。
- LLM 权限边界：LLM 可以理解、建议和叙述，但不能直接写入 HP、SAN、Luck、线索拥有权、KTSL 授权、剧情阶段或持久化状态。
- KTSL 启用边界：`SessionMapState.ktsl_ledger is None` 的普通会话必须保持现有行为，不承担 KTSL stage、日志或 prompt 注入开销。
- 证据分层边界：deterministic oracle、live provider audit、真实 transcript replay、盲审标注是不同证据层，不应混成一个“模型得分”。
- 渐进产品化边界：JSON store 必须继续保留本地开发与回放价值；认证和数据库可以先做抽象与测试契约，再绑定具体供应商。

## 需求索引

| ID | 方向 | MVP 完成信号 | 产品化完成信号 |
|---|---|---|---|
| REQ-001 | KTSL 真实模组启用 | 会话可自动附加 ledger 并注册 stages | 模组/环境可配置 KTSL 模式与 Web/API 启动入口 |
| REQ-002 | Transcript 证据层 | 至少一个匿名 transcript fixture 可 replay 并输出 H1-H3 | 多标注者、差异报告、一致性统计和隐私流程 |
| REQ-003 | CoC 规则扩展 | 奖励/惩罚骰、Luck、对抗检定进入 `RuleEngine` 审计 | 战斗、追逐、疯狂症状形成结构化状态机 |
| REQ-004 | ClueGraph | session 中持久化线索图并支持 fail-forward | 关键线索断链检测、误解修正和 KTSL knowledge 合流 |
| REQ-005 | 正式认证授权 | HTTP principal 替代裸 `requester_id` | token 生命周期、撤销、审计、service token |
| REQ-006 | 产品化持久化 | StateStore 一致性契约和 JSON store 硬化 | 数据库事务、跨进程锁、迁移和线上观测 |

## REQ-001：KTSL 真实模组一键启用

### 背景

当前已经具备 `KTSLLedger`、`ModuleDefinition.ktsl_spec`、`SceneRuntime.register_ktsl_stages()`、`SubmitCheckStage`、M3 stage 测试和 KTSL log writer。但真实模组默认不会启用 KTSL；需要手工附加 ledger 并注册 stages。

### MVP 需求

- 会话创建路径支持 `enable_ktsl` 选项。
- 启用时优先从 `module.ktsl_spec` 构造 `KTSLLedger`；没有 `ktsl_spec` 时允许显式传入 ledger 或使用 wizard 生成的 ledger 文件。
- `ScenarioService.create_party()` 或独立 bootstrap 能把 ledger 放入 `SessionMapState.ktsl_ledger` 并持久化。
- `SceneRuntime` 在启用会话中注册标准 stage 链：`ScheduleGateStage`、`FilterStage`、`CouplingDriftStage`、`AuditStage`。
- `SubmitCheckStage` 保持提交前拦截职责，阻止空行动、明显未授权信息引用和未满足前置依赖。
- `PromptBuilder` 只在 ledger 存在时注入 KTSL 上下文。
- 每回合写出 KTSL 决策 bundle：`stage_trace.jsonl`、`interventions.jsonl`、`ledger_diffs.jsonl`、`audit_snapshot.json`。

### 产品化需求

- 为 `main.py` 或独立 `ktsl_server.py` 增加明确启动入口，避免只能从测试里创建 app。
- 支持按模组配置 KTSL 模式：`off`、`audit_only`、`warn_only`、`block`。
- 支持 KP override 链：每次 `force_allow`、`force_block`、`declassify` 都要写入 ledger 和审计日志。
- Web 面板能显示当前会话的 KTSL 启用状态、stage 模式、barrier debt、redaction 决策和 override 历史。

### 验收标准

- 未启用 KTSL 的 `generic_mvp` 会话与现有回归行为一致。
- 启用 KTSL 的 `generic_mvp` 或 `tokoyami_subset` 会话在保存/恢复后仍保留 `ktsl_ledger`。
- 一次 3 到 5 回合测试能证明 stage pipeline 在 `resolve_turn()` 中运行，且输出 KTSL 日志。
- Prompt 构建测试证明非 KTSL 会话没有 `ktsl_context`，KTSL 会话存在 `ktsl_context`。
- deterministic oracle 结果不退化：`H1/H2/H3` 仍为 `2/2`。

### 建议测试

- `tests/scene/test_ktsl_runtime_enablement.py`
- `tests/scene/test_ktsl_prompt_builder.py`
- `tests/scene/ktsl/test_m3_gate.py`
- `PYTHONPATH=src python -m scenario.ktsl.evaluate --format json`

### 非目标

- 不要求所有模组默认开启 KTSL。
- 不把 KTSL 只写进 LLM prompt 作为软约束。
- 不要求一次性完成 Web 面板。

### 依赖关系

- 依赖 `ModuleDefinition.ktsl_spec`、`KTSLLedger.from_module_spec()`、`SceneRuntime`、`JsonScenarioStateStore`、`PromptBuilder`。
- 后续与 REQ-005 认证、REQ-006 持久化有耦合。

## REQ-002：真实 transcript 与盲审证据层

### 背景

当前 KTSL 证据来自 deterministic fixture 和 live provider audit。它们能证明协议机制和模型复现能力，但不能证明真实桌面跑团中玩家、KP、私聊、误解、等待成本的外部效度。

### MVP 需求

- 定义匿名 transcript fixture schema，至少包含：
  - turn/session id
  - speaker id 与角色 id
  - channel：public/private/keeper
  - scene id 与叙事时间窗
  - raw utterance 或匿名摘要
  - normalized action
  - known info ids / observed info ids
  - manual labels
- 提供 transcript replay，把 transcript 转换成 KTSL 可消费的 `EventRecord`、`InfoLabel`、knowledge update 和 audit entry。
- 输出 H1/H2/H3 对应指标：
  - causal violation / retcon
  - unauthorized action / public payload leak
  - declassification completeness
  - high-coupling drift / spotlight max gap
- 报告中必须标注证据类型：`deterministic_fixture`、`live_provider_audit`、`transcript_replay`、`blind_annotation`。
- 至少提供一个匿名 toy transcript fixture，覆盖公开旁听、私聊降密、跨场景时间漂移和一次合法低置信推理。

### 产品化需求

- 支持 transcript 导入前匿名化，移除真实玩家昵称、联系方式和敏感桌面内容。
- 支持两名以上标注者的盲审结果合并。
- 输出标注一致性统计、冲突样例和人工裁决记录。
- 报告可同时展示 oracle 结果、模型审计结果和 transcript 外部效度结果。

### 验收标准

- 一个 transcript fixture 可以端到端 replay，并产出 markdown/json 报告。
- replay 报告能列出每条未授权行动或泄露的原始证据位置。
- 人工标注与系统判定不一致时，报告能显示差异原因，而不是只给总分。
- deterministic oracle 仍是回归权威，transcript 结果不得覆盖 oracle 的 H1-H3 判定。

### 建议测试

- transcript schema model tests
- transcript parser tests
- replay-to-ktsl-ledger tests
- annotation diff golden tests
- report renderer snapshot tests

### 非目标

- 不把少量 transcript 写成“大规模真实实证”。
- 不把 live provider 输出当作真实桌面效果。
- 不把未匿名原始聊天记录提交进仓库。

### 依赖关系

- 依赖 `scenario.ktsl.evaluate`、`KTSLLedger.events`、KTSL report、analyst CLI。
- 与 REQ-001 的真实模组 KTSL 启用互相增强。

## REQ-003：CoC 规则覆盖扩展

### 背景

当前 `RuleEngine` 已支持基础百分骰检定、普通/困难/极难成功等级、fumble/critical、简单 `NdM` 后果骰、SAN/HP 状态后果。但 README 点名的奖励/惩罚骰、Luck、对抗检定、战斗、追逐和疯狂症状还没有完整 runtime 规则。

### MVP 需求

- 统一检定请求模型，例如 `CheckRequest`：
  - skill/attribute/luck/sanity/opposed
  - difficulty
  - bonus_dice / penalty_dice
  - pushed_roll_allowed
  - stakes
  - failure_consequence
- 统一检定结果模型，例如 `CheckResult`：
  - roll values
  - selected ones digit / tens digit
  - threshold
  - success level
  - resource deltas
  - audit text
- 支持奖励/惩罚骰，并在审计中记录所有骰值和最终采用值。
- 支持 Luck roll 和 Luck spend，Luck 修改必须写回调查员会话状态。
- 支持 opposed check，比较双方成功等级和必要的平局规则，输出双方审计。
- 将所有新增规则纳入 `DiceRollAudit` 或等价结构，玩家可见/keeper-only 可由视图层过滤。
- Plan Agent 只能提出需要什么检定和理由，最终骰点、成功等级、资源消耗、伤害和状态变化必须由 `RuleEngine` 和 `SessionMapState` 提交。

### 产品化需求

- 战斗轮：
  - initiative / DEX order
  - attack / dodge / fight back
  - damage roll
  - armor or reduction hooks
  - major wound / dying / dead state
- 追逐：
  - chase participants
  - range/location segment
  - hazard
  - move advantage
  - escape/catch condition
- 疯狂症状：
  - temporary insanity
  - indefinite insanity
  - bout of madness entry
  - investigator state and recovery hooks
- NPC 也可参与技能、对抗、战斗、追逐和精神状态变化。

### 验收标准

- 每类新增规则都有 deterministic `roll_provider` 测试。
- 每个规则结果都可在 `KeeperTurnView` 中追溯，玩家视图只显示应该公开的结果。
- HP/SAN/Luck/physical/mental state 变化进入权威状态，不只出现在叙事文本。
- 失败、推动检定和疯狂后果可以被 Render Agent 描述，但 Render Agent 不能自行改写后果。

### 建议测试

- `tests/cards/domain/test_luck.py`
- `tests/scene/test_coc_bonus_penalty_dice.py`
- `tests/scene/test_coc_opposed_checks.py`
- `tests/scene/test_coc_combat_minimal.py`
- `tests/scene/test_coc_chase_minimal.py`
- `tests/scene/test_coc_insanity_state.py`

### 非目标

- 不一次性覆盖规则书所有可选规则。
- 不让 LLM 直接裁定 HP、SAN、Luck 或战斗命中。
- 不在 MVP 阶段实现完整战术地图。

### 依赖关系

- 依赖 `RuleEngine`、`ModuleActionCheck`、`DiceRollAudit`、`SessionPlayerState.investigator`。
- 战斗和对抗会依赖 NPC session state；与后续 NPC 完整状态层有关。

## REQ-004：ClueGraph 与 fail-forward 线索系统

### 背景

当前模组 action 可以携带 `fail_forward_hint`，KTSL fixture 有 `ClueRecord`，但主运行时还没有完整 `ClueGraph`。因此系统不能稳定表达线索发现、遗漏、误解、冗余路径和失败后替代投递。

### MVP 需求

- 新增模组线索定义，例如 `ModuleClue`：
  - id / title / payload
  - source_scene_ids
  - related_action_ids
  - points_to
  - visibility
  - sensitivity
  - is_core
  - fail_forward_routes
  - redaction/public_summary
- 新增会话线索状态，例如 `SessionClueState`：
  - clue_id
  - discovery_state：unknown/discovered/missed/misinterpreted/redundant/delivered_by_fail_forward
  - owner_character_ids / observed_player_ids
  - delivery_attempts
  - first_seen_turn
  - source_event_id
- 新增 `ClueGraph`：
  - clue nodes
  - prerequisite edges
  - redundancy edges
  - points-to edges
  - core-route coverage
- `RuleEngine` 在检定失败时可根据 `fail_forward_hint` 和 `ClueGraph` 投递低精度替代线索。
- `TransitionValidator` 不能只依赖单一线索；核心剧情迁移应能检查 clue coverage 或多个等价证据路径。
- `PlayerView` 只显示授权线索；`KeeperView` 显示完整 clue graph、误解状态和未投递核心线索。
- KTSL Filter 使用同一线索可见性与敏感度来源，避免 ClueGraph 和 KTSL knowledge map 各说各话。

### 产品化需求

- Keeper 面板显示线索断链预警：核心结论是否仍有至少一条可达路径。
- 支持误解修正建议：当玩家误读线索时，系统提供低敏提醒或 NPC/环境补线索建议。
- 支持冗余线索统计：每个核心结论至少有多条线索路径。
- 支持后续 transcript 标注：每个玩家行动可以引用哪些 clue ids。

### 验收标准

- 玩家失败一次核心调查检定，不会让主线永久死锁。
- 玩家视图无法看到未授权私密线索 payload。
- Keeper 视图能解释“某个结论为什么仍可推到”或“为什么已经断链”。
- KTSL report 能引用 ClueGraph 中的 clue/info id 判断授权行动。

### 建议测试

- ClueGraph model tests
- module loader clue schema tests
- fail-forward runtime tests
- PlayerView/KeeperView clue filtering tests
- KTSL + ClueGraph integration tests
- transcript replay clue-reference tests

### 非目标

- 不做完整图形化编辑器。
- 不用 ClueGraph 替代剧情迁移权威；它只提供证据路径。
- 不要求所有低敏氛围描述都进入 ClueGraph。

### 依赖关系

- 依赖 `ModuleAction.fail_forward_hint`、`SessionMapState`、`RuleEngine`、`TransitionValidator`、`PromptBuilder`。
- 与 REQ-001 KTSL、REQ-002 transcript、REQ-005 认证强相关。

## REQ-005：正式认证与令牌权限

### 背景

当前 `ScenarioService` 通过 `requester_id` 校验玩家视图和守密人视图。这适合本地测试，但请求方可以伪造 query/body 中的 id，不适合作为产品级安全边界。KTSL router 也需要同一套权限模型，否则 report/knowledge API 可能泄露 keeper-only 或 private payload。

### MVP 需求

- 新增 principal 抽象：
  - principal_id
  - role：keeper/player/observer/service
  - session_id scope
  - player_id binding
  - permissions
- HTTP middleware 从 Authorization header 或开发模式 token 解析 principal。
- `ScenarioService` 方法从 `requester_id` 迁移到 principal，但保留测试辅助兼容层。
- player view、keeper view、KTSL report、KTSL knowledge、session state、timeline 都通过集中授权函数校验。
- 无 token 返回 401；权限不足返回 403；错误响应不得包含私密 payload。
- KP audit log 记录 principal，而不是只记录声称的 requester id。

### 产品化需求

- token 签发、刷新、过期、撤销。
- service token 用于内部任务和离线评测。
- observer role 支持旁观公开信息但不能看私聊、keeper-only、暗骰细节。
- 访问日志可查询：谁在什么时候查看了哪个 session/report/view。
- KTSL override 必须记录 keeper principal 和理由。

### 验收标准

- 玩家 token 不能读取其他玩家私密视图。
- 玩家 token 不能读取 keeper view。
- observer token 只能读取 public view。
- keeper token 可以读取全量 keeper view 和 KTSL report。
- 老的离线 runtime 单元测试不需要真实 token server。

### 建议测试

- HTTP auth middleware tests
- `ScenarioService` principal scope tests
- KTSL router auth tests
- private clue leakage regression tests
- audit log principal tests

### 非目标

- MVP 不绑定 OAuth/OIDC 供应商。
- 不把认证逻辑散落在每个 handler 中。
- 不把认证当作 KTSL Filter 的替代品；认证管用户身份，KTSL 管角色知识和信息流。

### 依赖关系

- 依赖 `ScenarioService._owner_by_session_id`、view builders、`main.py` handlers、`scenario.web.ktsl_router`、KP audit logger。
- 与 REQ-004 线索可见性、REQ-006 持久化审计有关。

## REQ-006：产品化持久化、锁与观测

### 背景

`JsonScenarioStateStore` 当前提供本地 JSON 快照、turn history 和原子 replace 写入，适合开发和回放。但线上需要事务、跨进程锁、并发保护、健康检查、迁移和观测指标。

### MVP 需求

- 明确 `ScenarioStateStore` 一致性契约：
  - session snapshot 与 turn resolution 的写入顺序
  - 写失败时的回滚或可恢复状态
  - `expected_turn` 幂等语义
  - `delete_session` 对 turn history 的处理
- JSON store 硬化：
  - 写入中断不会留下半截 JSON 被当成有效状态
  - corrupted JSON 有明确错误或 quarantine 机制
  - 可选文件锁，跨进程冲突时给出明确错误
- `SceneRuntime.resolve_turn()` 的持久化路径输出可审计事件，至少能区分 save_session、save_turn、load_sessions、load_turns 的失败。
- KTSL log writer 和 KP JSONL audit 与状态写入顺序要有一致性说明。

### 产品化需求

- 新增数据库 store，例如 SQLite 或 PostgreSQL 实现，但保持 `ScenarioStateStore` protocol 不膨胀。
- 每次 `resolve_turn` 在一个事务中提交：
  - session state
  - turn resolution
  - KP audit summary
  - KTSL audit snapshot
- 跨进程锁或数据库行锁防止双重结算。
- 线上观测指标：
  - save latency
  - load latency
  - lock wait
  - transaction rollback
  - idempotent replay hit
  - corrupted state count
- 提供 JSON store 到数据库 store 的迁移脚本和校验报告。

### 验收标准

- 崩溃或写入失败不会产生静默不一致，例如 turn 已写但 session 未推进。
- 两个并发 `resolve_turn(expected_turn=N)` 不会双提交。
- 重复 resolve 能返回历史结果。
- 数据库 store 事务回滚测试能证明失败不污染 session。
- 健康检查能报告 store 类型、连接状态、最近错误和迁移版本。

### 建议测试

- `ScenarioStateStore` protocol contract tests
- JSON store corrupted file tests
- JSON store lock conflict tests
- concurrent resolve tests
- database store transaction rollback tests
- migration smoke tests
- observability event snapshot tests

### 非目标

- 不删除 JSON store。
- 不在 MVP 阶段强制引入数据库依赖。
- 不把业务状态拆成多源写入；`SessionMapState` 仍是权威快照。

### 依赖关系

- 依赖 `JsonScenarioStateStore`、`ScenarioStateStore` protocol、`SceneRuntime._persist_session`、turn history、KTSL logs、KP JSONL audit。
- 与 REQ-005 访问日志和 REQ-001 KTSL 审计持久化有关。

## 建议实施顺序

1. REQ-001 KTSL 真实模组启用：它把已有 KTSL 能力接到真实 session，是当前最短闭环。
2. REQ-002 transcript 证据层：它让论文和 runtime 的外部效度开始可复现。
3. REQ-004 ClueGraph：调查游戏的可玩性主要靠线索系统，且它会反过来服务 KTSL 和 transcript 标注。
4. REQ-003 CoC 规则扩展：先补奖励/惩罚、Luck、对抗，再扩到战斗/追逐/疯狂。
5. REQ-005 正式认证：在更多私密线索和 KTSL report 出现前，应完成权限抽象。
6. REQ-006 产品化持久化：最后把本地闭环升级为可并发、可观测、可迁移的线上边界。

## 后续 Plan 阶段输入

后续进入 Plan 阶段时，应把这 6 个需求拆成至少 6 个 worker group，初步建议如下：

- Group A：KTSL enablement 与 bootstrap。
- Group B：Transcript schema、replay、annotation report。
- Group C：ClueGraph model、runtime integration、view filtering。
- Group D：CoC rules extension。
- Group E：Authentication/principal/middleware。
- Group F：StateStore contract、JSON hardening、database store contract。

每组必须独立保留 focused tests 和 evidence logs，不得只在 README 或 chat 中宣称完成。
