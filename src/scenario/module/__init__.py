"""模组静态定义与校验。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .types import ModuleCondition, ModuleEffect

if TYPE_CHECKING:
    from .models import (
        ClockThresholdEvent,
        ModuleAction,
        ModuleActionCheck,
        ModuleClock,
        ModuleDefinition,
        ModuleEnding,
        ModuleLink,
        ModuleScene,
    )
    from .validation import ModuleValidationError
    from .validation import validate_module_definition as validate_module_definition

__all__ = [
    "ClockThresholdEvent",
    "ModuleAction",
    "ModuleActionCheck",
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

_MODEL_EXPORTS = {
    "ClockThresholdEvent",
    "ModuleAction",
    "ModuleActionCheck",
    "ModuleClock",
    "ModuleDefinition",
    "ModuleEnding",
    "ModuleLink",
    "ModuleScene",
}
_VALIDATION_EXPORTS = {
    "ModuleValidationError",
    "validate_module_definition",
}


def __getattr__(name: str) -> Any:
    if name in _MODEL_EXPORTS:
        from . import models

        return getattr(models, name)
    if name in _VALIDATION_EXPORTS:
        from . import validation

        return getattr(validation, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
