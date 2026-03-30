# tests/cards/domain/test_card.py

from cards.domain.build import build_investigator_card


def test_card_state_respects_max_bounds() -> None:
    card = build_investigator_card(
        name="测试员",
        age=20,
        strength=50,
        constitution=60,
        size=60,
        dexterity=50,
        appearance=50,
        intelligence=50,
        power=60,
        education=50,
    )
    assert card.skills == {}

    card.modify_hit_point(-5)
    assert card.state.hit_points == 7
    assert card.derived.hit_points_max == 12

    card.modify_hit_point(10)
    assert card.state.hit_points == 12
    assert card.derived.hit_points_max == 12

    card.modify_magic_point(-5)
    assert card.state.magic_points == 7
    assert card.derived.magic_points_max == 12

    card.modify_magic_point(10)
    assert card.state.magic_points == 12
    assert card.derived.magic_points_max == 12

    card.modify_sanity(-40)
    assert card.state.sanity == 20
    assert card.derived.sanity_max == 99

    card.modify_sanity(80)
    assert card.state.sanity == 99
    assert card.derived.sanity_max == 99
