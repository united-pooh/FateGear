from __future__ import annotations

from collections.abc import Callable

from cards.domain.enums import MentalState
from scenario.runtime import SceneRuntime, TurnResolution
from scenario.runtime.coc_rules import (
    ChaseParticipantState,
    ChaseState,
    CheckRequest,
    CocRuleEngine,
    CombatantState,
    InvestigatorInsanityState,
    OpposedCheckRequest,
    ResourceDelta,
    advance_chase,
    apply_combat_damage,
    apply_insanity_event,
    apply_luck_spend,
    apply_resource_delta_to_session,
    build_combat_round,
    chase_move_advantage,
    check_value_from_card,
    check_value_from_session,
    luck_spend_to_dice_roll_audit,
)
from scenario.view import TurnViewBuilder
from tests.scene.card_fixtures import build_player_cards, build_test_card


def _provider(values: list[int]) -> Callable[[], int]:
    iterator = iter(values)
    return lambda: next(iterator)


def test_bonus_die_records_all_dice_and_selects_lowest_candidate() -> None:
    engine = CocRuleEngine(roll_provider=_provider([7, 8, 2]))

    result = engine.resolve_check(
        CheckRequest(
            actor_id="p1",
            check_kind="skill",
            key="spot_hidden",
            value=70,
            bonus_dice=1,
            stakes="notice the hidden mark",
            failure_consequence="miss the clue",
        )
    )

    assert result.success is True
    assert result.success_level == "hard"
    assert result.roll_value == 27
    assert result.selected_ones_digit == 7
    assert result.selected_tens_digit == 2
    assert result.dice.ones_die == 7
    assert result.dice.tens_dice == [8, 2]
    assert result.dice.candidate_values == [87, 27]
    assert result.dice.selected_value == 27
    assert result.dice.selection_policy == "lowest"
    assert result.stakes == "notice the hidden mark"
    assert result.failure_consequence == "miss the clue"


def test_penalty_die_records_all_dice_and_selects_highest_candidate() -> None:
    engine = CocRuleEngine(roll_provider=_provider([7, 2, 8]))

    result = engine.resolve_check(
        CheckRequest(
            actor_id="p1",
            check_kind="attribute",
            key="DEX",
            value=50,
            penalty_dice=1,
            pushed=True,
            pushed_roll_allowed=True,
        )
    )

    assert result.success is False
    assert result.success_level == "fail"
    assert result.roll_value == 87
    assert result.dice.tens_dice == [2, 8]
    assert result.dice.candidate_values == [27, 87]
    assert result.dice.selected_value == 87
    assert result.dice.selection_policy == "highest"
    assert result.pushed is True
    assert result.pushed_roll_allowed is True


def test_luck_roll_uses_structured_check_result() -> None:
    engine = CocRuleEngine(roll_provider=_provider([2, 4]))

    result = engine.resolve_luck_roll(actor_id="p1", luck_value=50)

    assert result.check_kind == "luck"
    assert result.key == "luck"
    assert result.threshold == 50
    assert result.roll_value == 42
    assert result.success is True
    assert result.resource_deltas == []


def test_apply_luck_spend_persists_authoritative_session_resource() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    card = session.player_states["p1"].investigator
    luck_before = card.attributes.luck

    result = apply_luck_spend(
        session,
        player_id="p1",
        amount=3,
        reason="raise failed skill roll",
    )

    assert hasattr(card.state, "luck") is False
    assert result.accepted is True
    assert result.resource_delta.resource == "luck"
    assert result.resource_delta.before == luck_before
    assert result.resource_delta.after == luck_before - 3
    assert result.resource_delta.delta == -3
    assert result.resource_delta.applied is True
    assert session.player_states["p1"].resource_state["luck"] == luck_before - 3
    assert check_value_from_session(
        session,
        player_id="p1",
        check_kind="luck",
        key="luck",
    ) == luck_before - 3
    assert card.attributes.luck == luck_before


def test_luck_spend_audit_reaches_keeper_view_and_is_filtered_for_player() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    result = apply_luck_spend(
        session,
        player_id="p1",
        amount=4,
        reason="improve failed pushed roll",
    )
    audit = luck_spend_to_dice_roll_audit(
        result,
        turn_no=1,
        scene_id=session.player_states["p1"].current_scene_id,
        visibility="keeper",
    )
    resolution = TurnResolution(
        session_id=session.session_id,
        turn_no=1,
        next_turn=2,
        dice_rolls=[audit],
        current_stage_id=session.story_state.current_stage_id,
    )

    keeper_view = TurnViewBuilder().build_keeper_turn_view(
        resolution=resolution,
        session=session,
    )
    player_view = TurnViewBuilder().build_player_turn_view(
        resolution=resolution,
        session=session,
        player_id="p1",
    )

    assert session.player_states["p1"].resource_state["luck"] == 46
    assert keeper_view.dice_rolls[0].roll_kind == "resource_delta"
    assert keeper_view.dice_rolls[0].status_target == "luck"
    assert keeper_view.dice_rolls[0].status_before == 50
    assert keeper_view.dice_rolls[0].status_after == 46
    assert "Luck: 50->46" in keeper_view.dice_rolls[0].display_text
    assert player_view.dice_rolls == []


def test_resource_delta_commits_sanity_and_mental_state_to_session() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )

    committed = apply_resource_delta_to_session(
        session,
        ResourceDelta(
            owner_id="p1",
            resource="sanity",
            delta=-5,
            reason="failed sanity consequence",
        ),
    )

    investigator = session.player_states["p1"].investigator
    assert committed.applied is True
    assert committed.before == 50
    assert committed.after == 45
    assert investigator.state.sanity == 45
    assert investigator.state.mental_state == MentalState.TEMPORARY_INSANITY


def test_opposed_check_compares_success_level_and_keeps_both_audits() -> None:
    engine = CocRuleEngine(roll_provider=_provider([7, 4, 8, 2]))

    result = engine.resolve_opposed_check(
        OpposedCheckRequest(
            actor=CheckRequest(
                actor_id="investigator",
                check_kind="skill",
                key="fighting",
                value=70,
            ),
            opponent=CheckRequest(
                actor_id="cultist",
                check_kind="skill",
                key="dodge",
                value=60,
            ),
            tie_rule="higher_check_value",
        )
    )

    assert result.actor.roll_value == 47
    assert result.actor.success_level == "regular"
    assert result.opponent.roll_value == 28
    assert result.opponent.success_level == "hard"
    assert result.winner == "opponent"
    assert result.actor.dice.tens_dice == [4]
    assert result.opponent.dice.tens_dice == [2]


def test_opposed_check_uses_configured_tie_rule() -> None:
    engine = CocRuleEngine(roll_provider=_provider([1, 5, 5, 5]))

    result = engine.resolve_opposed_check(
        OpposedCheckRequest(
            actor=CheckRequest(actor_id="a", check_kind="skill", key="brawl", value=70),
            opponent=CheckRequest(
                actor_id="b",
                check_kind="skill",
                key="dodge",
                value=60,
            ),
            tie_rule="higher_check_value",
        )
    )

    assert result.actor.success_level == "regular"
    assert result.opponent.success_level == "regular"
    assert result.winner == "actor"


def test_card_value_reader_supports_skill_attribute_luck_and_sanity() -> None:
    card = build_test_card("p1")

    assert check_value_from_card(card, check_kind="skill", key="spot_hidden") == 80
    assert check_value_from_card(card, check_kind="attribute", key="POW") == 50
    assert check_value_from_card(card, check_kind="luck", key="luck") == 50
    assert check_value_from_card(card, check_kind="sanity", key="sanity") == 50


def test_minimal_combat_helpers_order_and_apply_damage() -> None:
    fast = CombatantState(
        combatant_id="fast",
        dexterity=80,
        hit_points=10,
        hit_points_max=10,
    )
    slow = CombatantState(
        combatant_id="slow",
        dexterity=40,
        hit_points=10,
        hit_points_max=10,
    )

    round_state = build_combat_round([slow, fast], round_no=2)
    wounded = apply_combat_damage(slow, damage=6)
    dead = apply_combat_damage(slow, damage=12)

    assert round_state.turn_order == ["fast", "slow"]
    assert wounded.combatant.hit_points == 4
    assert wounded.state_after == "major_wound"
    assert wounded.resource_delta.delta == -6
    assert dead.combatant.hit_points == 0
    assert dead.state_after == "dead"


def test_minimal_chase_helpers_advance_escape_and_caught_states() -> None:
    quarry = ChaseParticipantState(participant_id="quarry", move=9, position=4)
    pursuer = ChaseParticipantState(participant_id="pursuer", move=7, position=0)
    chase = ChaseState(
        participants={"quarry": quarry, "pursuer": pursuer},
        escape_position=5,
        caught_position=-1,
    )

    escaped = advance_chase(chase, participant_id="quarry", segments=1)
    caught = advance_chase(chase, participant_id="pursuer", segments=-1)

    assert chase_move_advantage(quarry=quarry, pursuer=pursuer) == 2
    assert escaped.position_before == 4
    assert escaped.position_after == 5
    assert escaped.status_after == "escaped"
    assert escaped.chase.status == "escaped"
    assert caught.position_after == -1
    assert caught.status_after == "caught"
    assert caught.chase.status == "caught"


def test_minimal_insanity_state_machine_transitions() -> None:
    state = InvestigatorInsanityState(investigator_id="p1")

    temporary = apply_insanity_event(
        state,
        event="sanity_loss",
        sanity_loss=5,
        current_turn=3,
    )
    bout = apply_insanity_event(
        temporary.after,
        event="bout_of_madness",
        current_turn=3,
        bout_entry="flee in panic",
    )
    recovered = apply_insanity_event(bout.after, event="recover", current_turn=4)
    indefinite = apply_insanity_event(
        state,
        event="indefinite_threshold",
        sanity_loss=20,
        current_turn=5,
    )

    assert temporary.before.phase == "stable"
    assert temporary.after.phase == "temporary_insanity"
    assert temporary.after.accumulated_sanity_loss == 5
    assert temporary.after.started_turn == 3
    assert bout.after.phase == "bout_of_madness"
    assert bout.after.bout_entry == "flee in panic"
    assert recovered.after.phase == "recovering"
    assert recovered.after.recovery_turn == 4
    assert indefinite.after.phase == "indefinite_insanity"
    assert indefinite.after.accumulated_sanity_loss == 20
