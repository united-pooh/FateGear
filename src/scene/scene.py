"""地图与场景静态数据模型占位模块。

这里将来承载 `Scene` 和 `SceneLink` 的领域定义，用于描述模组地图上的场景与连接关系。
"""

from pydantic import BaseModel, Field


class Scene(BaseModel):
    id: str = Field(
        ...,
        min_length=1,
        max_length=30,
        description="场景在模组内的唯一标识。",
    )
    module_id: str = Field(
        ...,
        min_length=1,
        max_length=30,
        description="当前场景所属模组的唯一标识。",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="场景对玩家或守密人展示的名称。",
    )
    description: str = Field(
        ...,
        min_length=0,
        max_length=1000,
        description="场景的静态描述文本，用于展示空间氛围与基本信息。",
    )
    tags: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="场景标签列表，用于分类、筛选或规则判定。",
    )
    is_entry: bool = Field(
        default=False,
        description="该场景是否可作为会话或地图的初始进入点。",
    )
    is_safe_zone: bool = Field(
        default=False,
        description="该场景是否属于默认安全区。",
    )
    is_exit: bool = Field(
        default=False,
        description="该场景是否可作为当前地图或流程的出口。",
    )

    key_items: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="场景内的关键物品列表，用于规则判定或事件触发。",
    )


class SceneLink(BaseModel):
    from_scene_id: str = Field(
        ...,
        min_length=1,
        max_length=30,
        description="单向连线起点场景的 scene_id。",
    )
    to_scene_id: str = Field(
        ...,
        min_length=1,
        max_length=30,
        description="单向连线终点场景的 scene_id。",
    )
    is_locked: bool = Field(
        default=False,
        description="该单向场景连线当前是否处于锁定状态。",
    )
    required_flags: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="通过该单向连线所需满足的状态标记列表。",
    )
    block_reason: str = Field(
        default="",
        max_length=200,
        description="当该单向连线不可通过时，返回给上层的阻塞原因说明。",
    )
