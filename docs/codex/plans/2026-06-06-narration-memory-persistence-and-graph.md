# 叙事记忆持久化与图数据库正式 Redo 计划

> 本文是 FateGear narration memory/graph 的正式 MCP redo 执行计划。它替代早期只指向快速 run 的草案，后续 worker 需以本计划、MCP 账本和 ADR 边界共同作为审计依据。

## 执行证据

- 正式 MCP run：`RUN-20260606085022-7f9bb239`
- 目标：将叙事记忆扩展为可持久化、可搜索、可审计、可失效的非权威上下文层，并在验证后的 accepted narration record 上构建本地图数据库索引。
- 非目标：不让 narration memory 或 graph database 改写 `runtime`、`StoryState`、`SessionMapState`、地图位置、规则校验结果或其他权威游戏状态。
- 证据来源：正式 MCP redo 的 dispatch、subagent 审计记录、tree rubric 评分、validation/QA/final-assessment checklist。
- RAG 调研吸收：采用 OpenClaw / LivingMemory 风格的召回调试与审计日志，优先补足“为什么召回/为什么排除”的证据；本轮不引入 BM25/Faiss/RRF 等重检索依赖。

## 架构边界

- 权威状态只来自 runtime 层：`SceneRuntime`、`StoryState`、`SessionMapState`、`TurnResolution`、`RuntimeEvent`。
- `NarrationMemoryStore` 和 graph memory 只服务于叙事连续性、prompt context、审计检索和历史解释。
- memory scope 必须按 `session_id` 与 `module_id` 隔离；跨 session/module 复用只能通过显式 global seed 输入。
- graph ingest 只能发生在 narration validation 通过之后，输入必须是 accepted narration record 或已确认的 runtime event 引用。
- `forgotten`、`stale`、`superseded` 只影响叙事上下文召回和审计视图，不反向修改权威 runtime 状态。

## Dispatch 与 Worker 分工

- `memory` worker：实现 JSONL/本地持久化、scope 隔离、搜索、遗忘、导出审计记录。
- `graph` worker：实现 SQLite graph memory、实体/事实/边关系、supersede 与 temporal query。
- `pipeline` worker：维护 MCP dispatch、run stage、tree rubric、validation/QA/final-assessment 账本。
- `GROUP-5 docs` worker：更新本计划与 ADR，明确非权威边界和正式 redo 证据，不修改代码或 MCP artifacts。

## Tree Rubric

- 边界正确性：memory/graph 不成为权威状态来源；runtime/StoryState/SessionMapState 仍是唯一游戏真相。
- 可追溯性：每条 memory/fact 能追溯到 source record、event ids、session/module scope 与状态变化。
- 隔离性：默认检索不得跨 session/module 泄漏；global seed 必须显式声明。
- 失效语义：active、stale、forgotten、superseded 的含义清晰，并可在 audit/export 中复核。
- 召回可解释性：每次持久记忆召回应能给出 privacy-safe trace，说明 selected、scope mismatch、status、expiry、rank limit 等原因。
- 验证顺序：graph ingest 在 validation 后执行，不能摄入未接受的 LLM 草稿。
- 审计完整性：search、forget、expiry、export audit 的边界有测试或文档证据。

## Validation / QA / Final Assessment Checklist

- [x] `RUN-20260606085022-7f9bb239` 记录 implementation、validation、QA、final-assessment 阶段；两小时门槛已满足。
- [x] subagent 审计确认代码 worker 未让 memory/graph 写入权威 runtime 状态。
- [x] dispatch 记录能解释 memory、graph、pipeline、docs worker 的责任边界。
- [x] focused tests 覆盖 memory persistence、search、forget、audit export、graph ingest、temporal supersede。
- [x] RAG 吸收项覆盖 privacy-safe retrieval trace，并经真实 `NarrationPipeline` 路径验证。
- [x] QA 复核 session/module scope，确认默认召回不会跨作用域污染。
- [x] final assessment 对照 tree rubric 给出通过/失败原因。
- [x] 文档复核本计划与 ADR 一致，且不引用旧快速 run 作为唯一证据。

验证备注：离线 `tests/scene -k 'not online'` 已通过；完整 `tests/scene` 当前只在在线 agent smoke 上因 OpenAI API `429 insufficient_quota` 触发 fallback 断言失败。

## 后续维护规则

- 新增长期记忆字段时，先说明它是否影响权威状态；默认答案应为“不影响”。
- 新增 graph relation 时，必须记录 source、scope、validity window 与 status。
- 调整 retrieval/search/expiry 行为时，同步更新 ADR 或新增 ADR，以免 prompt context 被误读为游戏真相。
