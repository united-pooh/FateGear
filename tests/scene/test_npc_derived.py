"""CoC 7e 派生属性测试。

验证 ``NPCSessionState`` 的 HP/MP/SAN/DB/Move 派生属性计算公式。
"""

from __future__ import annotations


from scenario.session.state import NPCSessionState


def _npc(**characteristics: int) -> NPCSessionState:
    """辅助函数：构造带指定 characteristics 的 NPCSessionState。"""
    return NPCSessionState(
        npc_id="test_npc",
        module_id="test_module",
        characteristics=characteristics,
    )


def test_hp_simple() -> None:
    """CON=50, SIZ=50 → HP = ceil(100/10) = 10。"""
    npc = _npc(CON=50, SIZ=50)
    assert npc.derived_hp == 10


def test_mp() -> None:
    """POW=65 → MP = floor(65/5) = 13。"""
    npc = _npc(POW=65)
    assert npc.derived_mp == 13


def test_san_eq_pow() -> None:
    """POW=55 → SAN = 55。"""
    npc = _npc(POW=55)
    assert npc.derived_san == 55


def test_db_symmetric() -> None:
    """STR+SIZ=2(小值)时查表 = -2。"""
    npc = _npc(STR=1, SIZ=1)
    assert npc.derived_db == -2


def test_move_human_default() -> None:
    """DEX=SIZ=50 → move = 8 (人类默认)。"""
    npc = _npc(DEX=50, SIZ=50)
    assert npc.derived_move == 8


def test_move_dex_less_than_siz() -> None:
    """DEX<SIZ → move = 7。"""
    npc = _npc(DEX=30, SIZ=70)
    assert npc.derived_move == 7


def test_move_dex_greater_than_siz() -> None:
    """DEX>SIZ → move = 9。"""
    npc = _npc(DEX=70, SIZ=30)
    assert npc.derived_move == 9


def test_same_request_cached() -> None:
    """同一请求内调用两次 derived_hp 返回同一 int 对象(值一致性)。"""
    npc = _npc(CON=50, SIZ=50)
    hp1 = npc.derived_hp
    hp2 = npc.derived_hp
    assert hp1 == hp2
    assert "hp" in npc._derived_cache


def test_missing_characteristics_returns_safe_default() -> None:
    """CON/SIZ 缺失时使用安全默认值 50 → HP = ceil(100/10) = 10。"""
    npc = _npc()  # 无任何 characteristics
    assert npc.derived_hp == 10  # ceil((50+50)/10) = 10


def test_reset_derived_cache() -> None:
    """reset_derived_cache() 应在回合开始时清空缓存。"""
    npc = _npc(CON=50, SIZ=50)
    _ = npc.derived_hp
    assert "hp" in npc._derived_cache
    npc.reset_derived_cache()
    assert "hp" not in npc._derived_cache
