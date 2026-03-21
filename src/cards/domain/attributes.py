from __future__ import annotations

from dataclasses import dataclass


def _validate_int(name: str, value: int, *, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}, got {value}")


@dataclass(frozen=True, slots=True)
class InvestigatorAttributes:
    """第七版克苏鲁调查员的属性块。"""

    strength: int
    constitution: int
    size: int
    dexterity: int
    appearance: int
    intelligence: int
    power: int
    education: int
    luck: int | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "strength",
            "constitution",
            "size",
            "dexterity",
            "appearance",
            "intelligence",
            "power",
            "education",
        ):
            _validate_int(field_name, getattr(self, field_name), minimum=1, maximum=99)
        if self.luck is not None:
            _validate_int("luck", self.luck, minimum=0, maximum=99)

    @property
    def strength_plus_size(self) -> int:
        return self.strength + self.size

    def as_dict(self) -> dict[str, int | None]:
        return {
            "STR": self.strength,
            "CON": self.constitution,
            "SIZ": self.size,
            "DEX": self.dexterity,
            "APP": self.appearance,
            "INT": self.intelligence,
            "POW": self.power,
            "EDU": self.education,
            "Luck": self.luck,
        }
