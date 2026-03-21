import pytest

from cards.domain.attributes import InvestigatorAttributes


def test_attributes_validate_percentile_range() -> None:
    with pytest.raises(ValueError):
        InvestigatorAttributes(
            strength=0,
            constitution=50,
            size=60,
            dexterity=70,
            appearance=40,
            intelligence=60,
            power=50,
            education=70,
        )


def test_attributes_expose_workbook_keys() -> None:
    attributes = InvestigatorAttributes(
        strength=80,
        constitution=50,
        size=60,
        dexterity=80,
        appearance=50,
        intelligence=50,
        power=50,
        education=80,
        luck=50,
    )

    assert attributes.as_dict() == {
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
