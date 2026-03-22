# 数值模型第一步

当前仓库还是骨架，所以第一步不要直接做“完整规则引擎”，而是先把调查员的核心数值域模型定下来。

这一步的目标只有四件事：

1. 固定属性输入结构：`STR/CON/SIZ/DEX/APP/INT/POW/EDU/Luck`
2. 固定衍生公式：`HP`、`MP`、`SAN`、`MOV`、`Build`、`Damage Bonus`
3. 固定角色卡初始化状态：当前 `HP/MP/SAN` 从最大值或初始值生成
4. 固定导入入口：先支持“像 Excel 导出出来的字典”这种最小输入

这样做的原因很直接：

- 技能点分配依赖属性
- 战斗依赖 `Build` 和 `Damage Bonus`
- 地图移动和追逐依赖 `MOV`
- SAN 系统依赖 `POW` 和克苏鲁神话值上限

如果这些基础值没有先变成稳定代码，后面每个模块都会重复写一遍公式。

## 目前代码落点

- `src/cards/domain/attributes.py`
  调查员属性对象和基础校验
- `src/cards/rules/derived.py`
  所有衍生值公式
- `src/cards/domain/card.py`
  调查员卡片聚合根
- `src/cards/domain/state.py`
  当前数值状态
- `src/cards/domain/build.py`
  从最小输入构建角色卡

## 最小使用方式

```python
from cards.domain.build import build_investigator_from_mapping

card = build_investigator_from_mapping(
    {
        "姓名": "前原树一",
        "职业": "大学生",
        "年龄": 20,
        "STR": 80,
        "CON": 50,
        "SIZ": 60,
        "DEX": 80,
        "APP": 50,
        "INT": 50,
        "POW": 50,
        "EDU": 80,
        "Luck": 50,
    }
)

assert card.derived.hit_points_max == 11
assert card.derived.damage_bonus.notation == "+1D4"
```

## 下一步建议顺序

1. 接职业模板和技能基础值种子
2. 建技能点分配模型
3. 再做骰子检定与对抗检定
4. 最后才接 Excel 解析和序列化

这条顺序的核心原则是：先做“纯数值域”，再做“规则动作”，最后做“I/O 和 Agent 接口”。
