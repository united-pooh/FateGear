"""YAML 模组定义加载器。"""

from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]
from cards import load_skill_template_mapping
from pydantic import ValidationError

from ..module.models import ModuleDefinition
from ..module.validation import ModuleValidationError, validate_module_definition

MODULE_ROOT = Path(__file__).resolve().parents[3] / "module"


def load_module_definition(path: str | Path) -> ModuleDefinition:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"未找到模组文件: {file_path}")

    raw_text = file_path.read_text(encoding="utf-8")
    payload = yaml.safe_load(raw_text) or {}

    try:
        definition = ModuleDefinition.model_validate(payload)
    except ValidationError as exc:
        raise ModuleValidationError(
            f"模组文件 {file_path} 结构校验失败: {exc}"
        ) from exc

    validate_module_definition(
        definition=definition,
        source=file_path,
        skill_templates=load_skill_template_mapping(),
    )
    return definition


def load_module_by_id(
    module_id: str,
    *,
    module_root: str | Path | None = None,
) -> ModuleDefinition:
    root = Path(module_root) if module_root is not None else MODULE_ROOT
    return load_module_definition(root / module_id / "module.yaml")
