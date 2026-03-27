"""基础设施层 IO 入口。"""

from .module_loader import MODULE_ROOT, load_module_by_id, load_module_definition

__all__ = [
    "MODULE_ROOT",
    "load_module_by_id",
    "load_module_definition",
]
