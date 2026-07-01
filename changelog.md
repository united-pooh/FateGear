# Changelog

## 2026-06-03

### Added
- 新增单玩家 `off_map_move` 风险状态：运行时按玩家持久化 `IllegalMoveRiskState`，记录 `illegal_value`、连续次数、累计次数、近期窗口、最近违规回合和惩罚等级。
- 新增越界移动风险事件与惩罚事件：`movement_risk_updated` 记录分数变化，`movement_penalty_triggered` 记录重度惩罚阈值、实际分数和应用效果。
- 新增 Keeper Prompt 只读风险事实，将当前越界风险、阈值、下一档惩罚和当前 pending move 的风险预览注入空间层，供模型解释但不允许覆盖运行时裁定。

### Safety
- `no_link` 移动会被运行时分类为 `violation_kind=off_map_move` 并按阈值升级；`missing_flags`、`missing_stage`、`locked_link` 等受规则阻塞的移动不会被误判为越界移动。
- 非越界回合只进行缓慢衰减，连续 2-3 次或多次间隔越界移动都会在确定性阈值下触发重度惩罚。

### Tests
- 新增连续越界、间隔越界、非越界阻塞不误伤、风险 prompt 注入等回归测试。

## 2026-06-01

### Added
- 新增 `scenario.narration` 渲染阶段守密人叙事管线：在 `SceneRuntime.resolve_turn()` 提交权威回合结果后，构造 `NarrationInputPacket`、检索辅助向量记忆、生成分层 prompt，并通过 `KeeperAgent(Render)` 产出公开叙事。
- 新增 `NarrativeState`、`NarrationPatchProposal`、`KeeperNarrationDraft` 与 `KeeperNarrationRecord` 等叙事契约，明确叙事状态只能保存氛围、NPC 语气和连续性信息，不能写入剧情、场景、flags、clocks、结局、已完成动作或检定结果。
- 新增内存版叙事记录仓库、向量上下文存储、确定性事件引用、记录生成与回放辅助，用于审计渲染输出、引用事件和重建叙事记录。

### Safety
- 叙事验证器会在持久化前检查事件引用、记忆引用、禁用事实泄露、已提交检定/移动/clock/剧情/动作事实冲突，以及非法叙事补丁；不安全或结构错误的模型输出会降级为基于已提交事件的安全模板叙事。
- 叙事补丁只允许更新公开 `NarrativeState` 路径，并会拒绝旧值不匹配、非公开 scope、未解析事件引用、类型/范围错误和权威游戏状态目标。

### Tests
- 新增叙事契约、输入构造、记忆、prompt、渲染代理、验证器、记录、管线、安全场景和回放测试，覆盖补丁边界、安全降级、辅助记忆冲突过滤、确定性回放和权威运行时状态不被叙事渲染修改。

## 2026-03-30

### Breaking Changes
- 移除旧 `scene.*` 命名空间（`src/scene` 整包删除），不再提供兼容层。
- 统一收敛到 `scenario.*` 新框架，运行时唯一入口为 `scenario.runtime.SceneRuntime`。

### Changed
- `scenario.module` 包导出改为惰性加载，避免 `story.models -> module.__init__ -> module.models` 的循环导入。
- 运行时相关测试收集路径已打通，可直接执行 `tests/scene/test_runtime.py --collect-only`。

## 2026-03-27

### Added
- 新增 YAML 模组静态定义模型，支持 scene、link、action、clock、ending 的最小表达。
- 新增模组 loader，可从 `module/<module_id>/module.yaml` 加载并执行结构与语义校验。
- 新增内存内 `SceneRuntime`，支持创建会话、提交结构化意图、按全局回合结算、多 scene 同步与 clock 阈值触发。
- 新增两个样例模组：
  - `module/generic_mvp/module.yaml`
  - `module/tokoyami_subset/module.yaml`
- 新增 `PyYAML` 依赖。

### Tests
- 新增 loader 测试，覆盖样例模组加载、重复 scene、坏 link、坏 action.scene_id、坏 clock 引用。
- 新增 runtime 测试，覆盖会话初始化、结构化动作、受限连线、全局回合推进、多 scene 同步、clock 阈值与 happy path。
- 为 `SceneMovementRules` 新增实际可达性测试，同时保留无配置时的显式未实现行为断言。

### Known Limitations
- 运行时状态仅保存在内存中，不接数据库或 API 层。
- 只支持结构化 `action_id` / `move` 意图，不处理自然语言输入。
- `Condition` / `Effect` 仅实现 MVP 所需的最小类型集合。
- `SceneRouter` 仍保留占位职责，当前可跑通链路由 `SceneRuntime` 提供。
