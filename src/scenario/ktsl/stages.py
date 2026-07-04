"""Turn stage implementations used by the KTSL pipeline."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .models import ModuleKTSLSpec


class SchemaValidationIssue(BaseModel):
    """Single validation problem in a ModuleKTSLSpec."""

    field: str
    message: str
    severity: Literal["error", "warning"] = "error"


class SchemaValidationReport(BaseModel):
    """Result of validating a ModuleKTSLSpec."""

    is_valid: bool
    issues: list[SchemaValidationIssue] = Field(default_factory=list)


class SchemaValidatorStage:
    """Validates a ModuleKTSLSpec for required fields and contradictions.

    Checks performed:
    - Every info_label with sensitivity >= medium must have a non-empty redaction.
    - Every info_label with sensitivity >= high must have a public_payload.
    - Every scene must have at least one participant_character_id.
    """

    def validate(self, spec: ModuleKTSLSpec) -> SchemaValidationReport:
        issues: list[SchemaValidationIssue] = []

        for info in spec.info_labels:
            if info.sensitivity in {"medium", "high", "keeper"} and not info.redaction:
                issues.append(
                    SchemaValidationIssue(
                        field=f"info_labels.{info.info_id}.redaction",
                        message=(
                            f"Sensitive info '{info.info_id}' "
                            f"(sensitivity={info.sensitivity}) requires redaction text."
                        ),
                    )
                )
            if info.sensitivity in {"high", "keeper"} and not info.public_payload:
                issues.append(
                    SchemaValidationIssue(
                        field=f"info_labels.{info.info_id}.public_payload",
                        message=(
                            f"High-sensitivity info '{info.info_id}' "
                            f"needs a public_payload."
                        ),
                    )
                )

        for scene in spec.scenes:
            if not scene.participant_character_ids:
                issues.append(
                    SchemaValidationIssue(
                        field=f"scenes.{scene.scene_id}.participant_character_ids",
                        message=f"Scene '{scene.scene_id}' has no participants.",
                    )
                )

        return SchemaValidationReport(is_valid=not issues, issues=issues)
