"""模组静态定义与校验。"""

from .models import (
    ClockThresholdEvent,
    ModuleAction,
    ModuleClock,
    ModuleDefinition,
    ModuleEnding,
    ModuleLink,
    ModuleScene,
)
from .types import ModuleCondition, ModuleEffect
from .validation import ModuleValidationError, validate_module_definition

__all__ = [
    "ClockThresholdEvent",
    "ModuleAction",
    "ModuleClock",
    "ModuleCondition",
    "ModuleDefinition",
    "ModuleEffect",
    "ModuleEnding",
    "ModuleLink",
    "ModuleScene",
    "ModuleValidationError",
    "validate_module_definition",
]
