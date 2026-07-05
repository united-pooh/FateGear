# FateGear

FateGear 是一个面向《克苏鲁的呼唤》（Call of Cthulhu, CoC）跑团的 KP 运行时原型。它不是一个只靠 prompt 即兴讲故事的聊天机器人，而是把模组事实、玩家意图、规则检定、剧情状态、私密信息、叙事生成、KTSL 时间同步和审计日志放进同一条可复现的回合链路里。

当前项目的主线已经从“最小 KP 后端”推进到三块同时存在：

- `SceneRuntime`：以 YAML 模组和 `SessionMapState` 为权威状态，处理玩家行动、规则结算、剧情迁移、视图过滤和审计日志。
- `Keeper Agent`：LLM 只参与意图理解、Plan 建议和 Render 叙事，不能绕过 `RuleEngine` / `TransitionValidator` 直接改写事实。
- `KTSL`：把论文中的 Schedule / Filter / Coupling 三层协议落到 fixture oracle、runtime ledger、submit-time block、resolve-time stage pipeline、报告和评测 runner 上。

一句话概括当前边界：

```text
玩家输入
  -> IntentNormalizer / KeeperIntentAgent
  -> SceneRuntime
  -> KTSL submit check / stage pipeline（启用时）
  -> KeeperPlanAgent 提议
  -> RuleEngine + TransitionValidator 提交权威事实
  -> KTSL Filter / Audit / LogWriter（启用时）
  -> KeeperRenderAgent 只读叙事
  -> PlayerView / KeeperView / reports / JSONL audit
```

## 当前状态

### 已经能跑

- YAML 模组加载与校验，当前样例模组为 `generic_mvp` 和 `tokoyami_subset`。
- 多玩家会话、建团、加入、提交意图、自然语言意图、结算回合、回合重放。
- CoC 7e 基础调查员卡、技能检定、成功等级、SAN/HP 后果骰、暗骰和危险边界自由行动。
- `PlayerTurnView` / `KeeperTurnView` 信息隔离：玩家只看到本人可见信息，守密人保留全量事实、暗骰和 keeper-only 内容。
- `JsonScenarioStateStore` 会话快照和回合历史持久化。
- KP 视角 JSONL 审计日志。
- `scenario.narration` 叙事管线实验层：叙事输入、记忆、prompt、验证、补丁、记录和回放。
- NPC session state 与 NPC patch 校验的基础能力。
- HTTP API：`main.py` 基于 `aiohttp` 暴露核心跑团接口。
- CLI 入口：`src/scenario/cli/play.py` 和 KTSL 工具链 CLI。

### KTSL 已经落地的部分

- `src/scenario/ktsl/`：KTSL 模型、Schedule、Filter、Coupling、Audit、fixture、评测 runner、live provider runner。
- 两个确定性 fixture：
  - `library_sewer_church`
  - `police_station_hospital_old_house`
- 三种评测模式：
  - `baseline`
  - `schedule_only`
  - `ktsl_full`
- 当前确定性 oracle 结果：H1 / H2 / H3 均为 `2/2`。
- 当前 live provider 结果：LongCat `LongCat-2.0` 和 DeepSeek `deepseek-v4-pro` 均完成 `6/6` case，`metric_match_rate=1.00`。
- `KTSLLedger` 已接入 `SessionMapState`，没有 ledger 的普通会话不会承担 KTSL 开销。
- `SubmitCheckStage` 已接入 `SceneRuntime.submit_intent()`：启用 ledger 后可在提交时阻止明显无效或越权行动。
- `SceneRuntime.register_ktsl_stages()` 已支持注册 `ScheduleGateStage`、`FilterStage`、`CouplingDriftStage`、`AuditStage`。
- `PromptBuilder` 在存在 ledger 时会注入 KTSL 上下文给 Plan Agent。
- `KTSLLogWriter` 可以按回合输出 `stage_trace`、`interventions`、`ledger_diffs` 和 `audit_snapshot`。
- KTSL Markdown / HTML 报告、publish gate、analyst CLI 和独立 `aiohttp` router 均已有测试覆盖。

### 仍是原型或研究状态

- `main.py` 默认只挂载核心跑团 API，不会自动挂载 `/ktsl/*` router。KTSL router 目前通过 `scenario.web.ktsl_router.create_ktsl_app()` 或测试入口独立使用。
- Web 前端位于 `web/`，是 KTSL KP 面板原型和 mockup，不是完整产品前端。
- KTSL runtime stage pipeline 已可注册和测试，但不是所有真实模组默认启用。需要给会话附加 `KTSLLedger` 并注册 stages。
- 当前 KTSL 证据来自 deterministic fixture 和 live provider audit，不等同于真实跑团 transcript 或盲审标注。
- CoC 规则仍是基础子集，尚未完整覆盖奖励/惩罚骰、Luck、对抗检定、战斗、追逐和疯狂症状。
- 线索系统还没有完整 `ClueGraph`、误解修正、冗余线索和 fail-forward 投递。
- 访问边界目前主要靠 `requester_id`，还不是正式认证/令牌系统。
- JSON store 可用于本地开发和回放，数据库事务、跨进程锁和线上观测仍未产品化。

## 快速开始

推荐 Python 3.12+。

```bash
cd /Users/united_pooh/PycharmProjects/FateGear
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

离线规则模式不需要 LLM API key：

```bash
python main.py --no-agents
```

默认服务地址：

```text
http://127.0.0.1:8000
```

带 Agent 模式读取 `.env` 或当前 shell 环境变量：

```bash
cp .env.example .env
python main.py
```

常用环境变量：

```text
AGENT_API_KEY=
AGENT_BASE_URL=
PLANNER_AGENT_MODEL=
NARRATOR_AGENT_MODEL=

DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_THINKING=disabled
```

`main.py` 常用参数：

```bash
python main.py --host 127.0.0.1 --port 8000 --module-root ./module
python main.py --no-agents --no-kp-log
python main.py --kp-log-path ./log/kp-flow.jsonl
```

## HTTP API

健康检查和模组列表：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/modules
```

创建会话：

```bash
curl -X POST http://127.0.0.1:8000/sessions \
  -H 'Content-Type: application/json' \
  -d '{"module_id":"tokoyami_subset","creator_id":"keeper"}'
```

加入玩家：

```bash
curl -X POST http://127.0.0.1:8000/sessions/<session_id>/players \
  -H 'Content-Type: application/json' \
  -d '{"player_id":"player_1"}'
```

提交结构化意图：

```bash
curl -X POST http://127.0.0.1:8000/sessions/<session_id>/intents \
  -H 'Content-Type: application/json' \
  -d '{"player_id":"player_1","intent":{"type":"observe","text":"我查看门上的便签"}}'
```

提交自然语言意图：

```bash
curl -X POST http://127.0.0.1:8000/sessions/<session_id>/text-intents \
  -H 'Content-Type: application/json' \
  -d '{"player_id":"player_1","text":"我查看门上的便签"}'
```

结算回合：

```bash
curl -X POST http://127.0.0.1:8000/sessions/<session_id>/resolve \
  -H 'Content-Type: application/json' \
  -d '{"requester_id":"keeper"}'
```

查看视图：

```bash
curl 'http://127.0.0.1:8000/sessions/<session_id>/players/player_1/view?requester_id=player_1'
curl 'http://127.0.0.1:8000/sessions/<session_id>/keeper-view?requester_id=keeper'
```

## KTSL 评测与工具链

确定性 oracle 是 KTSL 的主评测入口：

```bash
PYTHONPATH=src python -m scenario.ktsl.evaluate --format markdown
```

按 fixture 或 mode 过滤：

```bash
PYTHONPATH=src python -m scenario.ktsl.evaluate \
  --fixture library_sewer_church \
  --mode ktsl_full \
  --format json
```

真实 API provider audit：

```bash
PYTHONPATH=src python -m scenario.ktsl.live_evaluate \
  --provider longcat \
  --provider deepseek \
  --format markdown \
  --timeout 120
```

live runner 会从白名单环境变量和 `~/.zshrc` 读取 provider 配置，但不会把 API key 写入报告。它的作用是让模型尝试复现 deterministic oracle 指标；oracle 仍以 `scenario.ktsl.evaluate` 为准。

KTSL CLI：

```bash
PYTHONPATH=src python -m scenario.cli.ktsl_cli --help
PYTHONPATH=src python -m scenario.cli.ktsl_cli validate library_sewer_church
PYTHONPATH=src python -m scenario.cli.ktsl_cli publish library_sewer_church --output-dir ./ktsl-output
PYTHONPATH=src python -m scenario.cli.ktsl_cli replay ./ktsl-output/repro-20260705/session-demo/session-state.json
PYTHONPATH=src python -m scenario.cli.ktsl_cli analyst <session_id> --log-base ./log
```

当前可追溯报告：

- `docs/research/ktsl-evaluation.md`
- `docs/research/ktsl-live-provider-evaluation.md`
- `ktsl-output/repro-20260705/`

## KTSL Web API 与前端原型

KTSL router 在 `src/scenario/web/ktsl_router.py` 中，当前提供：

```text
POST   /ktsl/validate
POST   /ktsl/session
POST   /ktsl/{session_id}/events
GET    /ktsl/{session_id}/state
GET    /ktsl/{session_id}/timeline
GET    /ktsl/{session_id}/report
GET    /ktsl/{session_id}/knowledge
DELETE /ktsl/{session_id}
POST   /ktsl/publish
POST   /ktsl/replay
```

它没有挂到 `main.py` 的默认 app 上。开发时可以从 `scenario.web.ktsl_router.create_ktsl_app()` 创建独立 aiohttp app，或参考 `tests/scene/test_ktsl_web_api.py`。

前端原型：

```bash
cd web
npm install
npm run dev
```

当前页面包括 dashboard、session、timeline、knowledge map、barriers/couplings、reports 和 modules。它更接近 KTSL KP 面板原型，不是完整跑团产品壳。

## 项目结构

```text
FateGear/
  main.py                         # aiohttp 核心跑团 API 入口
  requirements.txt
  module/
    generic_mvp/
    tokoyami_subset/
  src/
    cards/                        # CoC 调查员卡、技能和规则基础
    scenario/
      agent/                      # Intent / Plan / Render Agent 契约
      api.py                      # ScenarioService 服务层
      audit/                      # KP JSONL 审计日志
      cli/                        # play CLI 与 ktsl CLI
      context/                    # NarrativeContext 选择器
      intent/                     # 自然语言意图归一化
      io/                         # YAML 模组加载
      ktsl/                       # KTSL 协议、评测、runtime stages
      module/                     # 模组 schema
      narration/                  # 叙事管线实验层
      report/                     # Markdown / HTML / analyst 报告
      runtime/                    # SceneRuntime、RuleEngine、回合契约
      session/                    # SessionMapState 与持久化状态
      story/                      # 剧情阶段与迁移
      store/                      # JSON StateStore
      view/                       # 玩家/守密人视图投影
      web/                        # KTSL aiohttp router
  tests/
    cards/
    scene/
      ktsl/
  docs/
    research/
    superpowers/
  web/                            # React + Vite KTSL KP 面板原型
  ktsl-output/                    # 本地 KTSL 复现实验输出
```

## 核心设计原则

FateGear 最重要的原则是：

> LLM 可以帮助理解、建议和叙述，但不能成为游戏事实的唯一来源。

因此：

- 模组静态事实来自 YAML。
- 会话事实来自 `SessionMapState`。
- 规则事实来自 `RuleEngine`。
- 剧情迁移来自 `TransitionValidator`。
- KTSL 事实来自 `KTSLLedger`，启用时参与提交检查、输出过滤、同步审计和报告。
- 叙事文本来自 Render Agent，但只能描述已经提交的结果。
- 事件日志、回合历史和 KTSL logs 负责回答“为什么会这样”。

这个边界会让系统比纯 prompt 跑团硬一些，但它换来的是可审计、可回放、可测试，也更适合以后扩展成多人在线跑团工具。

## 开发与验证

常用测试：

```bash
PYTHONPATH=src pytest -q
```

场景运行时：

```bash
PYTHONPATH=src pytest tests/scene -q
```

KTSL 重点回归：

```bash
PYTHONPATH=src pytest tests/scene/test_ktsl_*.py tests/scene/ktsl -q
```

卡牌/调查员规则：

```bash
PYTHONPATH=src pytest tests/cards -q
```

静态检查：

```bash
ruff check src tests
git diff --check
```

当前仓库的全量 `mypy` 可能受历史测试模块映射问题影响。做 KTSL 或运行时验证时，优先保留 focused pytest、确定性 oracle 和相关报告输出作为证据。

## 近期路线

- 把 KTSL stage pipeline 从可注册测试状态推进到真实模组的一键启用流程。
- 给 `main.py` 或独立 bootstrap 增加明确的 KTSL API 启动入口。
- 继续补 `ClueGraph`、线索迁移、误解修正和 fail-forward 投递。
- 补 NPC 离屏行动、关系记忆、知识边界和世界时钟。
- 把 `web/` 面板从 prototype 接到真实 KTSL API 和 session 数据。
- 继续收集真实或更接近真实的 transcript，验证 deterministic fixture 之外的外部效度。
