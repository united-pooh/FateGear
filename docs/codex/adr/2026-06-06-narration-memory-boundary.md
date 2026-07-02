# ADR: 叙事记忆与图数据库边界

- 日期：2026-06-06
- 状态：Accepted
- MCP run：`RUN-20260606085022-7f9bb239`

## 背景

FateGear 需要持久化叙事记忆，并用本地图数据库索引角色、事件、事实和时间关系。该能力用于提升 Keeper 叙事连续性、检索历史上下文和生成审计证据，但不能改变游戏规则、地图状态或 runtime 已提交的事实。

## 决策

`Narration memory` 与 `graph memory` 是非权威层。它们只能作为 prompt context、搜索索引、审计记录和叙事解释来源。

权威状态仍由 runtime 维护，包括但不限于：

- `StoryState`
- `SessionMapState`
- runtime/session state
- `TurnResolution`
- `RuntimeEvent`
- 规则校验与地图移动结果

## 边界规则

- memory scope 必须使用 `session_id` 与 `module_id` 隔离；默认检索只返回当前 scope 的内容。
- global seed 必须显式输入、显式标记，不能由普通 session 记忆隐式提升。
- graph ingest 必须发生在 narration validation 通过之后，只能摄入 accepted narration record、validated patch 或权威 runtime event 引用。
- memory/graph 可以记录“叙事曾这样描述”，但不能据此改写 `StoryState`、`SessionMapState`、位置、flag、时钟或校验结果。
- search、audit、expiry 只管理上下文可见性和审计可见性，不具备游戏状态提交能力。

## 状态语义

- `active`：可被当前 scope 的 prompt context 召回。
- `stale`：仍保留审计价值，但默认不作为当前叙事事实召回。
- `forgotten`：被用户或系统明确遗忘；默认不召回，但可在审计导出中保留状态记录。
- `superseded`：graph fact 被同一 scope、entity/relation/path 的更新事实替代；旧记录保留 provenance，并设置有效期结束。

## 审计与查询

- 每条 memory/fact 必须尽量保留 source record id、source event ids、session/module scope、created/updated 时间和 status。
- audit export 应能包含 stale、forgotten、superseded 记录，用于解释“为什么不再召回”。
- 持久记忆召回应保留不含正文的 trace，用于解释 selected、scope mismatch、status、expiry、rank limit 等召回/排除原因。
- search 默认排除 stale、forgotten、superseded 内容；include inactive 必须显式。
- `valid_from_turn` / `valid_to_turn` 使用半开区间语义：`valid_from_turn <= turn < valid_to_turn`。
- expiry 只能降低召回优先级或改变 status，不能删除权威 runtime 事件。

## 后果

该边界让叙事层可以更聪明、更可查，同时避免 LLM 记忆、graph 推断或过期上下文污染游戏真相。后续实现和测试必须优先证明：runtime 仍是 authoritative，memory/graph 只是可审计的辅助层。
