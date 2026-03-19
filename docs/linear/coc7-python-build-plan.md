# FateGear 的 COC7 Python 构建计划

## 基于工作簿推导的范围

源工作簿：`data/COC七版人物卡v1.6.3.xlsx`

重要导入说明：
- 该工作簿包含不合法的数据验证 XML，直接调用 `openpyxl.load_workbook()` 会失败。
- 如果 FateGear 后续需要自动提取数据，优先使用 `zipfile + XML` 解析，或者一次性导出规范化的 CSV/JSON 并提交到仓库中。

已观察到的工作表：
- `人物卡`：主角色卡、当前值、技能表、武器、备注
- `分支技能`：分支技能名称和基础值
- `职业列表`：114 个职业模板
- `属性和掷骰`：属性辅助说明、随机骰点、风味文本
- `武器列表`：104 个武器模板
- `信誉参照表`：信用评级到生活水平 / 现金 / 资产的查表
- `附表`：伤害加值、Build、MOV 的查表规则
- `更新说明`：更新日志

从工作簿中提取出的核心领域事实：
- 8 项核心属性：`STR`、`DEX`、`POW`、`CON`、`APP`、`EDU`、`SIZ`、`INT`
- 角色卡上的当前值 / 上限资源：`HP`、`SAN`、`Luck`、`MP`
- 派生的战斗 / 移动值：`DB`、`Build`、`MOV`
- 技能表有 64 个可见槽位，每个槽位包含基础值、成长、职业点、兴趣点、总值、半值、五分之一值
- `技艺`、`科学`、`格斗`、`射击`、`罕见` 都存在分支技能查表
- 职业模板数量：114
- 武器模板数量：104

需要保留或规范化的工作簿行为：
- `HPMAX = INT((CON + SIZ) / 10)`
- `MPMAX = INT(POW / 5)`
- `SAN current` 初始值来自 `POW`
- `SAN max = 99 - 克苏鲁神话`
- `DB` 和 `Build` 通过 `STR + SIZ` 对应的查表得到
- 技能总值为 `base + growth + occupation + interest + other modifiers`
- 半值 / 五分之一值都向下取整

需要在代码中显式处理的工作簿不一致点：
- `MOV` 在可见工作表中是可编辑的，但隐藏的 `附表` 里又定义了真实规则。Python 实现应默认按规则计算 `MOV`，并可选支持手动覆盖。
- `Luck` 在 `属性和掷骰` 中带有一定随机性，但可见角色卡中存储的是一个明确数值。MVP 阶段应把 `Luck` 当作显式输入，随机生成放到后续再做。
- 工作表里的时代选项有 `1920s`、`1980s`、`现代`、`其他`，但信誉参照表只包含 `1920s` 和 `现代`。MVP 先支持 `1920s` 和 `现代`，`1980s` / `其他` 作为延后处理的策略问题。
- 复选框单元格、头像单元格、说明性风味文本和长篇背景故事都属于表现层关注点，不属于数值核心。

## 推荐的 Python 包结构

```text
src/fategear/coc7/
  domain/
    enums.py
    value_objects.py
    attributes.py
    derived.py
    skills.py
    occupations.py
    weapons.py
    credit.py
    character.py
  rules/
    formulas.py
    movement.py
    allocators.py
    validators.py
  seed/
    base_skills.json
    branch_skills.json
    occupations.json
    weapons.json
    credit_bands.json
  app/
    services.py
    serializers.py
    cli.py
  tooling/
    extract_coc7_workbook.py
tests/
  coc7/
```

实现原则：
- 先做领域模型，再做 CLI，最后才做 Excel 导入。
- Seed 数据应以规范化 JSON 的形式提交到仓库，而不是在运行时直接读取 `.xlsx`。
- 所有数值规则都应实现为纯函数，并配备可重复、确定性的测试。
- `current_hp` 这类当前状态值要和 `max_hp` 这类派生上限明确分开。

## 交付顺序

1. 先实现纯数值核心。
2. 加入技能模板和技能点分配。
3. 加入职业、信用评级和武器查表数据。
4. 组装 `Character` 聚合并提供序列化。
5. 暴露一个简洁 CLI，并通过工作簿样例做一致性测试。

## Linear 任务包

使用一个 Epic 加若干小型子任务。下面的标题已经整理为可直接用于 Linear 的形式。

---

### Epic: FateGear 的 COC7 Python 角色领域 MVP

类型：`Epic`  
优先级：`P1`  
标签：`fategear`, `python`, `coc7`, `domain`

目标：
- 为 FateGear 构建一个 Python 优先的 COC7 角色领域模型，以 `COC七版人物卡v1.6.3.xlsx` 中的数值模型为起点，配套规范化 seed 数据和最小 CLI。

完成标准：
- FateGear 可以在运行时不依赖 Excel 的前提下，创建、校验、序列化并查看一名 COC7 调查员。

---

### Issue 01: 初始化 `fategear.coc7` 包骨架

类型：`Feature`  
优先级：`P1`  
预估：`1`  
标签：`fategear`, `python`, `scaffolding`
依赖：`Epic`

说明：
- 创建 COC7 领域包和测试目录的初始结构。

范围：
- 添加 `src/fategear/coc7/`
- 添加 `tests/coc7/`
- 添加占位用的 `__init__.py`
- 仅在仓库已经存在相关工具的前提下，补充基础测试命令和 lint/type-check 钩子

验收标准：
- 该包可以被成功导入
- 一个最简单的测试可以在新模块树上运行

---

### Issue 02: 编写一次性 workbook 提取脚本

类型：`Feature`  
优先级：`P1`  
预估：`2`  
标签：`fategear`, `python`, `tooling`, `data`
依赖：`Issue 01`

说明：
- 由于这个文件不能可靠地通过 `openpyxl` 直接加载，需要创建一个一次性提取脚本。

范围：
- 添加 `tooling/extract_coc7_workbook.py`
- 使用 `zipfile + ElementTree` 解析工作簿 XML
- 导出分支技能、职业、武器和信用段位的规范化 JSON 草稿
- 记录提取过程中的限制

验收标准：
- 运行脚本后可以产出机器可读的 JSON 制品
- 脚本不依赖 Excel 桌面程序，也不依赖人工 GUI 操作

---

### Issue 03: 定义 COC7 基础枚举和值对象

类型：`Feature`  
优先级：`P1`  
预估：`1`  
标签：`fategear`, `python`, `domain`
依赖：`Issue 01`

说明：
- 在编写公式前，先引入强类型的基础原语。

范围：
- 为 `AttributeName`、`Era`、`SkillCategory`、`WeaponCategory` 添加枚举
- 为有界百分比和正整数添加值对象
- 添加共享的校验错误类型

验收标准：
- 非法百分比和无效枚举输入会快速失败
- 规则模块可以引入这些类型且不会形成循环依赖

---

### Issue 04: 实现主属性模型

类型：`Feature`  
优先级：`P1`  
预估：`1`  
标签：`fategear`, `python`, `domain`, `attributes`
依赖：`Issue 03`

说明：
- 将 COC7 的 8 项核心属性建模为一等数据结构。

范围：
- 添加 `PrimaryAttributes`
- 按工作表推导出的限制进行校验：普通属性 `<= 99`，`POW <= 150` 仅在规则明确允许时放开
- 添加总和与查值辅助方法

验收标准：
- 可以从普通数据构造出合法的属性集合
- 非法值会抛出清晰错误

---

### Issue 05: 实现体力 / 魔法 / 理智派生规则

类型：`Feature`  
优先级：`P1`  
预估：`1`  
标签：`fategear`, `python`, `rules`, `derived`
依赖：`Issue 04`

说明：
- 将工作簿中的资源上限和初始值公式编码实现。

范围：
- `max_hp = floor((CON + SIZ) / 10)`
- `max_mp = floor(POW / 5)`
- `initial_san = POW`
- `max_san = 99 - mythos`
- 将 `current_*` 和 `max_*` 分离

验收标准：
- 公式输出与工作簿规则在代表性输入下保持一致
- 模型中明确区分当前状态值和上限值

---

### Issue 06: 实现伤害加值和 Build 查表规则

类型：`Feature`  
优先级：`P1`  
预估：`1`  
标签：`fategear`, `python`, `rules`, `combat`
依赖：`Issue 04`

说明：
- 根据 `附表` 添加基于查表的战斗派生值。

范围：
- 规范化 `STR + SIZ -> DB` 表
- 规范化 `STR + SIZ -> Build` 表
- 实现纯查表函数

验收标准：
- 查表输出与隐藏工作表一致
- 边界值有测试覆盖

---

### Issue 07: 实现 MOV 规则和手动覆盖策略

类型：`Feature`  
优先级：`P1`  
预估：`2`  
标签：`fategear`, `python`, `rules`, `movement`
依赖：`Issue 04`

说明：
- 解决工作簿里可见 `MOV` 输入与隐藏规则表之间的冲突。

范围：
- 基于 `STR`、`DEX`、`SIZ`、`age` 实现规则化的 MOV 计算
- 支持 `附表` 中基于年龄的 MOV 减值规则
- 在领域模型中定义可选的手动覆盖行为

验收标准：
- 默认调查员无需手动输入即可算出 MOV
- 手动覆盖必须是显式且可审计的
- 测试覆盖 40 岁以下和年龄减值两类情况

---

### Issue 08: 实现职业点和兴趣点预算规则

类型：`Feature`  
优先级：`P1`  
预估：`2`  
标签：`fategear`, `python`, `rules`, `skills`
依赖：`Issue 04`

说明：
- 将后续技能分配必须满足的点数预算规则编码实现。

范围：
- 实现职业点公式，如 `EDU*4`、`EDU*2 + DEX*2`、`EDU*2 + max(STR, DEX)*2`
- 实现兴趣点公式 `INT * 2`
- 提供带有已花费 / 剩余计数的预算报告对象

验收标准：
- 仅根据属性即可计算出点数公式结果
- 剩余点数的计算独立于 UI

---

### Issue 09: 设计技能模板 schema

类型：`Feature`  
优先级：`P1`  
预估：`1`  
标签：`fategear`, `python`, `schema`, `skills`
依赖：`Issue 03`

说明：
- 定义所有技能模板的标准表示方式。

范围：
- 添加 `name`、`category`、`base_value`、`branch_required`、`branch_group` 等字段
- 区分固定技能与 `格斗:`、`科学:` 这类分支技能
- 决定是否将神话技能当作一种特殊技能类型处理

验收标准：
- 该 schema 能表示工作簿中所有可见技能行
- 分支技能槽位可以被实例化，而无需额外的临时逻辑

---

### Issue 10: 导出基础技能和分支技能 seed 数据

类型：`Feature`  
优先级：`P1`  
预估：`2`  
标签：`fategear`, `python`, `data`, `skills`
依赖：`Issue 02`, `Issue 09`

说明：
- 将规范化后的技能 seed 文件提交到仓库，而不是在运行时读取 Excel。

范围：
- 从主表导出基础技能
- 从 `分支技能` 导出分支技能选项
- 保留工作簿中 `格斗`、`射击`、`科学`、`技艺`、`特殊技能` 的基础值

验收标准：
- Seed 文件可以复现工作簿里的技能目录
- 技能元数据在运行时不再依赖 `.xlsx`

---

### Issue 11: 实现技能实例模型和成功率计算

类型：`Feature`  
优先级：`P1`  
预估：`2`  
标签：`fategear`, `python`, `domain`, `skills`
依赖：`Issue 08`, `Issue 10`

说明：
- 构建角色在运行时使用的技能对象。

范围：
- 跟踪 `base`、`growth`、`occupation`、`interest`、`other`
- 计算 `total`、`half`、`fifth`
- 支持分支标签绑定，例如 `格斗:斗殴`

验收标准：
- 技能总值和派生阈值是确定性的
- 分支技能序列化时同时保留槽位类型和分支名称

---

### Issue 12: 设计职业模板 schema

类型：`Feature`  
优先级：`P2`  
预估：`1`  
标签：`fategear`, `python`, `schema`, `occupations`
依赖：`Issue 03`

说明：
- 为工作簿中的职业定义结构化表示。

范围：
- 增加 `id`、`name`、`credit_range`、`point_formula`、`recommended_skills`、`notes` 等字段
- 先支持人类可读的技能推荐文本，不强求第一天就做到完全精确解析

验收标准：
- 该 schema 能容纳工作簿中的全部职业行
- 点数公式的存储格式可供机器读取

---

### Issue 13: 导出 114 个职业模板 seed 数据

类型：`Feature`  
优先级：`P2`  
预估：`3`  
标签：`fategear`, `python`, `data`, `occupations`
依赖：`Issue 02`, `Issue 12`

说明：
- 将工作簿中的职业表规范化为可版本化的 seed 数据。

范围：
- 从 `职业列表` 导出全部职业
- 保留工作簿中的职业 id
- 规范化信用范围文本和点数公式

验收标准：
- Seed 数据包含全部 114 个职业
- 至少有一个 snapshot 测试保护导出的目录

---

### Issue 14: 实现信用评级和生活水平查表

类型：`Feature`  
优先级：`P2`  
预估：`1`  
标签：`fategear`, `python`, `credit`, `lookup`
依赖：`Issue 03`, `Issue 02`

说明：
- 建模 `信誉参照表` 中的数值部分。

范围：
- 规范化 `1920s` 和 `现代` 的信用段位
- 将信用评级映射到生活水平标签、现金、花销水平和资产范围
- 将 `1980s` 和 `其他` 标记为不支持或可配置

验收标准：
- `1920s` 和 `现代` 都可以返回有效的查表结果
- 不支持的时代会显式报错

---

### Issue 15: 实现职业合法性校验器

类型：`Feature`  
优先级：`P2`  
预估：`2`  
标签：`fategear`, `python`, `validation`, `occupations`
依赖：`Issue 08`, `Issue 11`, `Issue 13`, `Issue 14`

说明：
- 校验一个角色构筑是否符合所选职业要求。

范围：
- 校验职业点预算
- 校验信用评级范围
- 以规则引擎层级校验必需或推荐的职业技能
- 返回结构化校验报告，而不只是布尔值

验收标准：
- 角色可以被拿来对照某个职业模板进行检查
- 校验输出足够详细，能够用于 CLI 展示和未来 UI

---

### Issue 16: 设计武器模板 schema

类型：`Feature`  
优先级：`P2`  
预估：`1`  
标签：`fategear`, `python`, `schema`, `weapons`
依赖：`Issue 03`

说明：
- 定义工作簿中武器的标准表示方式。

范围：
- 增加 `name`、`skill_name`、`damage`、`range`、`impale`、`attacks`、`ammo`、`malfunction`、`era`、`price` 等字段
- 保留像 `1D8+DB` 这样的伤害字符串

验收标准：
- 工作簿中的全部武器行都能落入该 schema
- 在这个阶段伤害字符串不会丢失信息

---

### Issue 17: 导出 104 个武器模板 seed 数据

类型：`Feature`  
优先级：`P2`  
预估：`2`  
标签：`fategear`, `python`, `data`, `weapons`
依赖：`Issue 02`, `Issue 16`

说明：
- 将工作簿中的武器列表规范化为提交到仓库的 seed 文件。

范围：
- 从 `武器列表` 导出武器行
- 保留工作簿中的命名和时代字符串
- 规范化 `ammo`、`malfunction` 等可空字段

验收标准：
- Seed 数据包含全部 104 个武器
- 通过一个小型 fixture 测试验证行数和若干样例行

---

### Issue 18: 实现武器实例和命中率绑定

类型：`Feature`  
优先级：`P2`  
预估：`2`  
标签：`fategear`, `python`, `domain`, `combat`
依赖：`Issue 11`, `Issue 17`

说明：
- 将武器模板和角色技能模型连接起来。

范围：
- 创建运行时武器实例
- 从对应技能解析命中率
- 支持默认的徒手攻击和闪避条目

验收标准：
- 武器实例可以报告当前命中率、半值和五分之一值
- 无需选择武器模板也能正确处理徒手和闪避条目

---

### Issue 19: 组装 `Character` 聚合根

类型：`Feature`  
优先级：`P1`  
预估：`2`  
标签：`fategear`, `python`, `domain`, `aggregate`
依赖：`Issue 05`, `Issue 06`, `Issue 07`, `Issue 11`, `Issue 15`, `Issue 18`

说明：
- 构建应用其余部分会使用到的主调查员聚合对象。

范围：
- 包含身份字段、属性、派生数值、技能、职业、武器和信用信息
- 区分不可变的构筑数据和可变的游戏状态字段
- 添加聚合级别的校验入口

验收标准：
- 一个对象就能表示一名可游玩的调查员构筑
- 聚合对象的序列化足够稳定，可用于测试

---

### Issue 20: 实现 JSON/YAML 序列化协议

类型：`Feature`  
优先级：`P2`  
预估：`1`  
标签：`fategear`, `python`, `serialization`
依赖：`Issue 19`

说明：
- 定义一种独立于 Excel 的可移植磁盘表示格式。

范围：
- 添加 JSON 的序列化 / 反序列化器
- 如果仓库已使用 YAML，可选增加 YAML 支持
- 对载荷 schema 进行版本化

验收标准：
- 角色可以无损地在磁盘上往返读写
- 载荷中存储了 schema 版本

---

### Issue 21: 实现最小 CLI：`create`、`show`、`validate`

类型：`Feature`  
优先级：`P2`  
预估：`2`  
标签：`fategear`, `python`, `cli`
依赖：`Issue 19`, `Issue 20`

说明：
- 提供一个轻量命令行接口，方便前期使用和测试。

范围：
- 从 JSON/YAML 输入执行 `create`
- `show` 派生数值、关键技能和职业报告
- `validate` 职业和点数预算检查

验收标准：
- 用户无需打开 Excel 就可以构建并查看角色
- 校验失败时 CLI 以非零状态退出

---

### Issue 22: 建立 workbook 对照样例测试

类型：`Feature`  
优先级：`P1`  
预估：`2`  
标签：`fategear`, `python`, `tests`, `parity`
依赖：`Issue 19`

说明：
- 用具体的工作簿样例锁定领域行为，同时记录不一致点。

范围：
- 为工作簿中可见的样例调查员值添加测试
- 断言 HP、MP、SAN max、DB、Build 和代表性技能总值
- 显式记录诸如 `MOV` 之类已知偏差点

验收标准：
- 测试可以保护来源于工作簿的公式行为
- 已知工作簿不一致点会以具名测试用例或注释的形式保留下来

---

### Issue 23: 补齐开发文档和后续 backlog

类型：`Task`  
优先级：`P3`  
预估：`1`  
标签：`fategear`, `docs`
依赖：`Issue 21`, `Issue 22`

说明：
- 记录已交付的 MVP，并列出后续延期项。

范围：
- 添加安装和 CLI 使用文档
- 记录 seed 文件来源及其重新生成流程
- 添加延期 backlog，包括叙事字段、骰点、Excel 导入适配器、1980s 时代支持、UI 层

验收标准：
- 新贡献者无需先阅读工作簿也能理解这个领域包
- 延期范围与 MVP 范围有清晰分隔

## 建议的 MVP 截止线

如果想先做出一个最小但真正可用的切片，可以先做到以下任务为止：
- `Issue 01`
- `Issue 03`
- `Issue 04`
- `Issue 05`
- `Issue 06`
- `Issue 07`
- `Issue 09`
- `Issue 10`
- `Issue 11`
- `Issue 12`
- `Issue 13`
- `Issue 15`
- `Issue 19`
- `Issue 20`
- `Issue 21`
- `Issue 22`

这一版能给 FateGear 带来：
- 原生 Python 的角色模型
- 确定性的派生数值
- 技能总值和成功阈值
- 职业点校验
- 已导入的职业 seed 数据
- JSON 持久化
- 一个可用的 CLI

## 明确延期到 MVP 之后的内容

- Excel UI 层面的还原，例如合并单元格、复选框、头像位置
- 与工作簿布局完全一致的全文本导出
- 随机属性和随机幸运值生成 UI
- 传记、伤势、恐惧、随身物品等叙事字段
- 从任意用户提供的 `.xlsx` 自动导入
- 完整的 `1980s` 和 `其他` 经济策略
- 对伤害表达式做进一步解析，而不只是保存原始字符串
