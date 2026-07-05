"""Structured Call of Cthulhu rule helpers for runtime checks.

This module is intentionally independent from the scene engine. It follows the
same RollProvider convention as RuleEngine while returning explicit audit and
resource-delta models that callers can persist or expose through views.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cards.domain.card import InvestigatorCard
from cards.domain.enums import MentalState, PhysicalState

from ..session.state import SessionMapState, SessionPlayerState
from .contracts import DiceRollAudit
from .rule_engine import RollProvider

CheckKind = Literal["skill", "attribute", "luck", "sanity", "opposed"]
Difficulty = Literal["regular", "hard", "extreme"]
SuccessLevel = Literal["critical", "extreme", "hard", "regular", "fail", "fumble"]
Visibility = Literal["public", "keeper"]
ResourceName = Literal["luck", "sanity", "hit_points", "magic_points"]
OpposedTieRule = Literal[
    "higher_check_value",
    "higher_roll",
    "initiator",
    "defender",
    "tie",
]
OpposedWinner = Literal["actor", "opponent", "tie"]

PercentileValue = Annotated[int, Field(ge=0, le=99, strict=True)]
DiceCount = Annotated[int, Field(ge=0, le=2, strict=True)]
DigitValue = Annotated[int, Field(ge=0, le=9, strict=True)]

_SUCCESS_RANK: dict[str, int] = {
    "fumble": -1,
    "fail": 0,
    "regular": 1,
    "hard": 2,
    "extreme": 3,
    "critical": 4,
}
_DIFFICULTY_RANK: dict[str, int] = {
    "regular": 1,
    "hard": 2,
    "extreme": 3,
}


class CheckRequest(BaseModel):
    """A single percentile check request.

    ``value`` is the authoritative target value supplied by the caller after it
    has read the relevant skill, attribute, Luck, or SAN from session state.
    """

    model_config = ConfigDict(validate_assignment=True)

    actor_id: str = Field(default="", max_length=80)
    check_kind: CheckKind = "skill"
    key: str = Field(default="", max_length=80)
    value: PercentileValue | None = None
    difficulty: Difficulty = "regular"
    bonus_dice: DiceCount = 0
    penalty_dice: DiceCount = 0
    pushed: bool = False
    pushed_roll_allowed: bool = False
    stakes: str = Field(default="", max_length=500)
    failure_consequence: str = Field(default="", max_length=500)
    visibility: Visibility = "public"


class D100RollAudit(BaseModel):
    """All dice needed to reconstruct a CoC 7e percentile roll."""

    bonus_dice: int = 0
    penalty_dice: int = 0
    effective_bonus_dice: int = 0
    effective_penalty_dice: int = 0
    selection_policy: Literal["normal", "lowest", "highest"] = "normal"
    ones_die: DigitValue
    tens_dice: list[DigitValue] = Field(default_factory=list)
    selected_ones_digit: DigitValue
    selected_tens_digit: DigitValue
    candidate_values: list[int] = Field(default_factory=list)
    selected_value: int = Field(ge=1, le=100)


class ResourceDelta(BaseModel):
    """Structured resource mutation or attempted mutation."""

    owner_id: str = Field(default="", max_length=80)
    resource: ResourceName
    before: int | None = None
    after: int | None = None
    delta: int = 0
    applied: bool = False
    reason: str = Field(default="", max_length=300)


class CheckResult(BaseModel):
    """Resolved check result with complete audit data."""

    actor_id: str = Field(default="", max_length=80)
    check_kind: CheckKind
    key: str = Field(default="", max_length=80)
    difficulty: Difficulty
    target_value: int = Field(ge=0, le=99)
    threshold: int = Field(ge=0, le=99)
    roll_value: int = Field(ge=1, le=100)
    selected_ones_digit: DigitValue
    selected_tens_digit: DigitValue
    success: bool
    success_level: SuccessLevel
    raw_success_level: SuccessLevel
    pushed: bool = False
    pushed_roll_allowed: bool = False
    stakes: str = ""
    failure_consequence: str = ""
    resource_deltas: list[ResourceDelta] = Field(default_factory=list)
    dice: D100RollAudit
    audit_text: str = ""
    visibility: Visibility = "public"


class OpposedCheckRequest(BaseModel):
    """Two checks resolved together using CoC opposed-check comparison."""

    actor: CheckRequest
    opponent: CheckRequest
    tie_rule: OpposedTieRule = "higher_check_value"
    stakes: str = Field(default="", max_length=500)
    failure_consequence: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _reject_nested_opposed(self) -> "OpposedCheckRequest":
        if self.actor.check_kind == "opposed" or self.opponent.check_kind == "opposed":
            raise ValueError("opposed check sides must be skill/attribute/luck/sanity")
        return self


class OpposedCheckResult(BaseModel):
    actor: CheckResult
    opponent: CheckResult
    winner: OpposedWinner
    tie_rule: OpposedTieRule
    stakes: str = ""
    failure_consequence: str = ""
    audit_text: str = ""


class LuckSpendResult(BaseModel):
    player_id: str = Field(default="", max_length=80)
    requested_spend: int = Field(ge=0)
    accepted: bool = False
    resource_delta: ResourceDelta
    reason: str = Field(default="", max_length=300)


class CombatantState(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    combatant_id: str = Field(..., min_length=1, max_length=80)
    dexterity: int = Field(ge=0, le=99)
    hit_points: int = Field(ge=0)
    hit_points_max: int = Field(ge=1)
    armor: int = Field(default=0, ge=0)
    state: Literal["ready", "major_wound", "dying", "dead"] = "ready"


class CombatRoundState(BaseModel):
    round_no: int = Field(default=1, ge=1)
    turn_order: list[str] = Field(default_factory=list)


class CombatDamageResult(BaseModel):
    combatant: CombatantState
    damage: int = Field(ge=0)
    armor: int = Field(ge=0)
    damage_applied: int = Field(ge=0)
    resource_delta: ResourceDelta
    state_before: str
    state_after: str


class ChaseParticipantState(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    participant_id: str = Field(..., min_length=1, max_length=80)
    move: int = Field(ge=0)
    position: int = 0
    status: Literal["running", "escaped", "caught", "out"] = "running"


class ChaseState(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    round_no: int = Field(default=1, ge=1)
    participants: dict[str, ChaseParticipantState] = Field(default_factory=dict)
    escape_position: int = Field(default=5)
    caught_position: int = Field(default=-1)
    status: Literal["active", "escaped", "caught", "ended"] = "active"


class ChaseAdvanceResult(BaseModel):
    chase: ChaseState
    participant_id: str
    position_before: int
    position_after: int
    status_before: str
    status_after: str


class InvestigatorInsanityState(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    investigator_id: str = Field(..., min_length=1, max_length=80)
    phase: Literal[
        "stable",
        "temporary_insanity",
        "indefinite_insanity",
        "bout_of_madness",
        "recovering",
    ] = "stable"
    accumulated_sanity_loss: int = Field(default=0, ge=0)
    started_turn: int | None = Field(default=None, ge=1)
    recovery_turn: int | None = Field(default=None, ge=1)
    bout_entry: str = Field(default="", max_length=200)


class InsanityTransition(BaseModel):
    before: InvestigatorInsanityState
    after: InvestigatorInsanityState
    event: Literal[
        "sanity_loss",
        "indefinite_threshold",
        "bout_of_madness",
        "recover",
    ]
    sanity_loss: int = Field(default=0, ge=0)
    reason: str = Field(default="", max_length=300)


class CocRuleEngine:
    """Small deterministic CoC rules engine for checks and audits."""

    def __init__(self, *, roll_provider: RollProvider | None = None) -> None:
        self._roll_provider = roll_provider or self._random_percentile

    def resolve_check(self, request: CheckRequest) -> CheckResult:
        if request.value is None:
            raise ValueError("check request value is required")
        dice = self._roll_d100(
            bonus_dice=request.bonus_dice,
            penalty_dice=request.penalty_dice,
        )
        threshold = difficulty_threshold(request.value, request.difficulty)
        raw_level = success_level(dice.selected_value, request.value)
        success = _SUCCESS_RANK[raw_level] >= _DIFFICULTY_RANK[request.difficulty]
        visible_level = raw_level if success or raw_level == "fumble" else "fail"
        key = request.key or request.check_kind
        audit_text = (
            f"{request.actor_id}:{request.check_kind}:{key} "
            f"roll={dice.selected_value} threshold={threshold} "
            f"level={visible_level} success={success}"
        )
        return CheckResult(
            actor_id=request.actor_id,
            check_kind=request.check_kind,
            key=key,
            difficulty=request.difficulty,
            target_value=request.value,
            threshold=threshold,
            roll_value=dice.selected_value,
            selected_ones_digit=dice.selected_ones_digit,
            selected_tens_digit=dice.selected_tens_digit,
            success=success,
            success_level=visible_level,
            raw_success_level=raw_level,
            pushed=request.pushed,
            pushed_roll_allowed=request.pushed_roll_allowed,
            stakes=request.stakes,
            failure_consequence=request.failure_consequence,
            dice=dice,
            audit_text=audit_text,
            visibility=request.visibility,
        )

    def resolve_luck_roll(
        self,
        *,
        actor_id: str,
        luck_value: int,
        difficulty: Difficulty = "regular",
        bonus_dice: int = 0,
        penalty_dice: int = 0,
        stakes: str = "",
        failure_consequence: str = "",
    ) -> CheckResult:
        return self.resolve_check(
            CheckRequest(
                actor_id=actor_id,
                check_kind="luck",
                key="luck",
                value=luck_value,
                difficulty=difficulty,
                bonus_dice=bonus_dice,
                penalty_dice=penalty_dice,
                stakes=stakes,
                failure_consequence=failure_consequence,
            )
        )

    def resolve_opposed_check(self, request: OpposedCheckRequest) -> OpposedCheckResult:
        actor = self.resolve_check(request.actor)
        opponent = self.resolve_check(request.opponent)
        winner = compare_opposed_results(
            actor,
            opponent,
            tie_rule=request.tie_rule,
        )
        audit_text = (
            f"opposed winner={winner} "
            f"actor={actor.success_level}/{actor.roll_value} "
            f"opponent={opponent.success_level}/{opponent.roll_value}"
        )
        return OpposedCheckResult(
            actor=actor,
            opponent=opponent,
            winner=winner,
            tie_rule=request.tie_rule,
            stakes=request.stakes,
            failure_consequence=request.failure_consequence,
            audit_text=audit_text,
        )

    def _roll_d100(self, *, bonus_dice: int, penalty_dice: int) -> D100RollAudit:
        effective_bonus = max(0, bonus_dice - penalty_dice)
        effective_penalty = max(0, penalty_dice - bonus_dice)
        extra_tens = max(effective_bonus, effective_penalty)
        ones = self._next_digit()
        tens_dice = [self._next_digit() for _ in range(extra_tens + 1)]
        candidates = [_compose_percentile(tens, ones) for tens in tens_dice]
        if effective_bonus:
            selected_value = min(candidates)
            policy: Literal["normal", "lowest", "highest"] = "lowest"
        elif effective_penalty:
            selected_value = max(candidates)
            policy = "highest"
        else:
            selected_value = candidates[0]
            policy = "normal"
        selected_index = candidates.index(selected_value)
        selected_tens = tens_dice[selected_index]
        return D100RollAudit(
            bonus_dice=bonus_dice,
            penalty_dice=penalty_dice,
            effective_bonus_dice=effective_bonus,
            effective_penalty_dice=effective_penalty,
            selection_policy=policy,
            ones_die=ones,
            tens_dice=tens_dice,
            selected_ones_digit=ones,
            selected_tens_digit=selected_tens,
            candidate_values=candidates,
            selected_value=selected_value,
        )

    def _next_digit(self) -> int:
        return self._next_roll() % 10

    def _next_roll(self) -> int:
        rolled = self._roll_provider()
        if rolled < 1 or rolled > 100:
            raise ValueError(f"roll provider values must be in 1..100, got: {rolled}")
        return rolled

    @staticmethod
    def _random_percentile() -> int:
        from random import randint

        return randint(1, 100)


def difficulty_threshold(value: int, difficulty: Difficulty) -> int:
    if difficulty == "regular":
        return value
    if difficulty == "hard":
        return value // 2
    return value // 5


def success_level(roll: int, value: int) -> SuccessLevel:
    if roll == 1:
        return "critical"
    if roll == 100 or (value < 50 and roll >= 96):
        return "fumble"
    if roll <= value // 5:
        return "extreme"
    if roll <= value // 2:
        return "hard"
    if roll <= value:
        return "regular"
    return "fail"


def compare_opposed_results(
    actor: CheckResult,
    opponent: CheckResult,
    *,
    tie_rule: OpposedTieRule = "higher_check_value",
) -> OpposedWinner:
    actor_rank = _SUCCESS_RANK[actor.success_level]
    opponent_rank = _SUCCESS_RANK[opponent.success_level]
    if actor_rank > opponent_rank:
        return "actor"
    if opponent_rank > actor_rank:
        return "opponent"

    if tie_rule == "higher_check_value":
        if actor.target_value > opponent.target_value:
            return "actor"
        if opponent.target_value > actor.target_value:
            return "opponent"
        return "tie"
    if tie_rule == "higher_roll":
        if actor.roll_value > opponent.roll_value:
            return "actor"
        if opponent.roll_value > actor.roll_value:
            return "opponent"
        return "tie"
    if tie_rule == "initiator":
        return "actor"
    if tie_rule == "defender":
        return "opponent"
    return "tie"


def apply_luck_spend(
    session: SessionMapState,
    *,
    player_id: str,
    amount: int,
    reason: str = "",
) -> LuckSpendResult:
    """Safely spend mutable Luck if the session card shape supports it."""

    if amount < 0:
        raise ValueError("luck spend amount must be non-negative")
    player_state = session.player_states.get(player_id)
    if player_state is None:
        return _luck_spend_rejected(
            player_id=player_id,
            amount=amount,
            before=None,
            after=None,
            reason=f"unknown player_id: {player_id}",
        )

    mutable_luck = _read_authoritative_luck(player_state)
    if mutable_luck is None:
        return _luck_spend_rejected(
            player_id=player_id,
            amount=amount,
            before=None,
            after=None,
            reason="investigator luck is not available",
        )

    if mutable_luck < amount:
        return _luck_spend_rejected(
            player_id=player_id,
            amount=amount,
            before=mutable_luck,
            after=mutable_luck,
            reason="insufficient luck",
        )

    after = mutable_luck - amount
    committed = _write_authoritative_luck(player_state, after)
    if not committed:
        return _luck_spend_rejected(
            player_id=player_id,
            amount=amount,
            before=mutable_luck,
            after=mutable_luck,
            reason="luck write failed",
        )

    delta = ResourceDelta(
        owner_id=player_id,
        resource="luck",
        before=mutable_luck,
        after=after,
        delta=-amount,
        applied=True,
        reason=reason,
    )
    return LuckSpendResult(
        player_id=player_id,
        requested_spend=amount,
        accepted=True,
        resource_delta=delta,
        reason=reason,
    )


def apply_resource_delta_to_session(
    session: SessionMapState,
    delta: ResourceDelta,
) -> ResourceDelta:
    """Commit a CoC resource delta into authoritative session state."""

    player_state = session.player_states.get(delta.owner_id)
    if player_state is None:
        return delta.model_copy(
            update={
                "applied": False,
                "reason": delta.reason or f"unknown player_id: {delta.owner_id}",
            }
        )

    investigator = player_state.investigator
    if delta.resource == "luck":
        before = _read_authoritative_luck(player_state)
        if before is None:
            return delta.model_copy(
                update={
                    "before": None,
                    "after": None,
                    "delta": 0,
                    "applied": False,
                    "reason": delta.reason or "investigator luck is not available",
                }
            )
        after = _target_after(before=before, delta=delta)
        if after is None:
            return delta.model_copy(
                update={
                    "before": before,
                    "after": before,
                    "delta": 0,
                    "applied": False,
                    "reason": delta.reason or "luck delta has no target",
                }
            )
        after = max(0, min(99, after))
        if not _write_authoritative_luck(player_state, after):
            return delta.model_copy(
                update={
                    "before": before,
                    "after": before,
                    "delta": 0,
                    "applied": False,
                    "reason": delta.reason or "luck write failed",
                }
            )
        return delta.model_copy(
            update={
                "before": before,
                "after": after,
                "delta": after - before,
                "applied": True,
            }
        )

    if delta.resource == "sanity":
        before = investigator.state.sanity
        after = _target_after(before=before, delta=delta)
        if after is None:
            return delta.model_copy(
                update={"before": before, "after": before, "delta": 0, "applied": False}
            )
        investigator.modify_sanity(after - before)
        after = investigator.state.sanity
        if after == 0:
            investigator.state.mental_state = MentalState.INDEFINITE_INSANITY
            investigator.state.special_state = "SAN归零"
        elif before - after >= 5:
            investigator.state.mental_state = MentalState.TEMPORARY_INSANITY
            investigator.state.special_state = "短时失控"
        return delta.model_copy(
            update={"before": before, "after": after, "delta": after - before, "applied": True}
        )

    if delta.resource == "hit_points":
        before = investigator.state.hit_points
        after = _target_after(before=before, delta=delta)
        if after is None:
            return delta.model_copy(
                update={"before": before, "after": before, "delta": 0, "applied": False}
            )
        investigator.modify_hit_point(after - before)
        after = investigator.state.hit_points
        if after == 0:
            investigator.state.physical_state = PhysicalState.DYING
            investigator.state.special_state = "濒死"
        return delta.model_copy(
            update={"before": before, "after": after, "delta": after - before, "applied": True}
        )

    if delta.resource == "magic_points":
        before = investigator.state.magic_points
        after = _target_after(before=before, delta=delta)
        if after is None:
            return delta.model_copy(
                update={"before": before, "after": before, "delta": 0, "applied": False}
            )
        investigator.modify_magic_point(after - before)
        after = investigator.state.magic_points
        return delta.model_copy(
            update={"before": before, "after": after, "delta": after - before, "applied": True}
        )

    return delta.model_copy(update={"applied": False})


def check_result_to_dice_roll_audit(
    result: CheckResult,
    *,
    turn_no: int = 0,
    scene_id: str = "",
    scene_name: str = "",
    action_id: str = "",
    action_name: str = "",
    source: Literal[
        "static_action_check",
        "dynamic_agent_check",
        "runtime_freeform_check",
    ] = "runtime_freeform_check",
) -> DiceRollAudit:
    """Adapt a structured CoC check into the runtime audit payload."""

    label = f"{result.key or result.check_kind} CHECK"
    level_label = _roll_level_label(result.success_level)
    display_text = (
        f"{label}\n"
        f"投掷骰子 d100={result.roll_value}\n"
        f"目标值 {result.threshold}：{level_label or ('成功' if result.success else '失败')}"
    )
    return DiceRollAudit(
        source=source,
        turn_no=turn_no,
        player_id=result.actor_id,
        scene_id=scene_id,
        scene_name=scene_name,
        action_id=action_id,
        action_name=action_name,
        skill_key=result.key,
        difficulty=result.difficulty,
        roll_value=result.roll_value,
        threshold=result.threshold,
        success=result.success,
        success_level=result.success_level,
        reason=result.stakes,
        note=result.failure_consequence or result.audit_text,
        visibility=result.visibility,
        roll_kind=result.check_kind,
        label=label,
        notation="d100",
        roll_values=result.dice.candidate_values or [result.roll_value],
        total=result.roll_value,
        penalty_dice=result.dice.effective_penalty_dice,
        display_text=display_text,
    )


def luck_spend_to_dice_roll_audit(
    result: LuckSpendResult,
    *,
    turn_no: int = 0,
    scene_id: str = "",
    scene_name: str = "",
    visibility: Visibility = "keeper",
) -> DiceRollAudit:
    """Represent Luck spend as a keeper/player-filterable runtime audit."""

    delta = result.resource_delta
    before = delta.before if delta.before is not None else 0
    after = delta.after if delta.after is not None else before
    prefix = "[暗骰] " if visibility == "keeper" else ""
    status = "accepted" if result.accepted else "rejected"
    display_text = f"{prefix}LUCK SPEND {status}\nLuck: {before}->{after}"
    return DiceRollAudit(
        source="status_consequence",
        turn_no=turn_no,
        player_id=result.player_id,
        scene_id=scene_id,
        scene_name=scene_name,
        visibility=visibility,
        roll_kind="resource_delta",
        label="LUCK SPEND",
        status_target="luck",
        status_before=before,
        status_after=after,
        status_delta=after - before,
        reason=result.reason,
        display_text=display_text,
    )


def build_combat_round(combatants: list[CombatantState], *, round_no: int = 1) -> CombatRoundState:
    ordered = sorted(combatants, key=lambda item: (-item.dexterity, item.combatant_id))
    return CombatRoundState(
        round_no=round_no,
        turn_order=[item.combatant_id for item in ordered],
    )


def apply_combat_damage(combatant: CombatantState, *, damage: int) -> CombatDamageResult:
    if damage < 0:
        raise ValueError("damage must be non-negative")
    before_hp = combatant.hit_points
    before_state = combatant.state
    applied = max(0, damage - combatant.armor)
    after_hp = max(0, before_hp - applied)
    if after_hp == 0 and applied >= combatant.hit_points_max:
        after_state = "dead"
    elif after_hp == 0:
        after_state = "dying"
    elif applied >= max(1, combatant.hit_points_max // 2):
        after_state = "major_wound"
    else:
        after_state = before_state
    after = combatant.model_copy(
        update={
            "hit_points": after_hp,
            "state": after_state,
        }
    )
    return CombatDamageResult(
        combatant=after,
        damage=damage,
        armor=combatant.armor,
        damage_applied=applied,
        resource_delta=ResourceDelta(
            owner_id=combatant.combatant_id,
            resource="hit_points",
            before=before_hp,
            after=after_hp,
            delta=-applied,
            applied=True,
            reason="combat_damage",
        ),
        state_before=before_state,
        state_after=after_state,
    )


def advance_chase(
    chase: ChaseState,
    *,
    participant_id: str,
    segments: int,
) -> ChaseAdvanceResult:
    if participant_id not in chase.participants:
        raise ValueError(f"unknown chase participant: {participant_id}")
    next_chase = chase.model_copy(deep=True)
    participant = next_chase.participants[participant_id]
    before_position = participant.position
    before_status = participant.status
    participant.position += segments
    if participant.position >= next_chase.escape_position:
        participant.status = "escaped"
        next_chase.status = "escaped"
    elif participant.position <= next_chase.caught_position:
        participant.status = "caught"
        next_chase.status = "caught"
    return ChaseAdvanceResult(
        chase=next_chase,
        participant_id=participant_id,
        position_before=before_position,
        position_after=participant.position,
        status_before=before_status,
        status_after=participant.status,
    )


def chase_move_advantage(
    *,
    quarry: ChaseParticipantState,
    pursuer: ChaseParticipantState,
) -> int:
    return quarry.move - pursuer.move


def apply_insanity_event(
    state: InvestigatorInsanityState,
    *,
    event: Literal[
        "sanity_loss",
        "indefinite_threshold",
        "bout_of_madness",
        "recover",
    ],
    sanity_loss: int = 0,
    current_turn: int = 1,
    reason: str = "",
    bout_entry: str = "",
) -> InsanityTransition:
    if sanity_loss < 0:
        raise ValueError("sanity_loss must be non-negative")
    before = state.model_copy(deep=True)
    after = state.model_copy(deep=True)
    if event == "sanity_loss":
        after.accumulated_sanity_loss += sanity_loss
        if sanity_loss >= 5:
            after.phase = "temporary_insanity"
            after.started_turn = current_turn
    elif event == "indefinite_threshold":
        after.accumulated_sanity_loss += sanity_loss
        after.phase = "indefinite_insanity"
        after.started_turn = current_turn
    elif event == "bout_of_madness":
        after.phase = "bout_of_madness"
        after.started_turn = current_turn
        after.bout_entry = bout_entry
    elif event == "recover":
        after.phase = "recovering"
        after.recovery_turn = current_turn
    return InsanityTransition(
        before=before,
        after=after,
        event=event,
        sanity_loss=sanity_loss,
        reason=reason,
    )


def check_value_from_card(
    card: InvestigatorCard,
    *,
    check_kind: Literal["skill", "attribute", "luck", "sanity"],
    key: str,
) -> int | None:
    """Read a check value from the current card shape without mutating it."""

    if check_kind == "skill":
        skill = card.skills.get(key)
        return skill.value if skill is not None else None
    if check_kind == "attribute":
        return _attribute_values(card).get(key.upper())
    if check_kind == "luck":
        return _read_card_luck(card)
    if check_kind == "sanity":
        return card.state.sanity
    return None


def check_value_from_session(
    session: SessionMapState,
    *,
    player_id: str,
    check_kind: Literal["skill", "attribute", "luck", "sanity"],
    key: str,
) -> int | None:
    """Read a check value from authoritative session state when available."""

    player_state = session.player_states.get(player_id)
    if player_state is None:
        return None
    if check_kind == "luck":
        return _read_authoritative_luck(player_state)
    return check_value_from_card(
        player_state.investigator,
        check_kind=check_kind,
        key=key,
    )


def _compose_percentile(tens: int, ones: int) -> int:
    value = tens * 10 + ones
    return 100 if value == 0 else value


def _target_after(*, before: int, delta: ResourceDelta) -> int | None:
    if delta.after is not None:
        return delta.after
    if delta.delta != 0:
        return before + delta.delta
    if delta.before is not None:
        return before
    return None


def _read_authoritative_luck(player_state: SessionPlayerState) -> int | None:
    stored = player_state.resource_state.get("luck")
    if isinstance(stored, int) and not isinstance(stored, bool):
        return stored
    card_luck = _read_mutable_luck(player_state.investigator)
    if card_luck is None:
        card_luck = _read_card_luck(player_state.investigator)
    if card_luck is not None:
        player_state.resource_state["luck"] = card_luck
    return card_luck


def _write_authoritative_luck(
    player_state: SessionPlayerState,
    value: int,
) -> bool:
    player_state.resource_state["luck"] = value
    state = player_state.investigator.state
    if _read_mutable_luck(player_state.investigator) is None:
        return True
    try:
        setattr(state, "luck", value)
    except (AttributeError, TypeError, ValueError):
        return False
    return True


def _read_mutable_luck(card: InvestigatorCard) -> int | None:
    value = getattr(card.state, "luck", None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _read_card_luck(card: InvestigatorCard) -> int | None:
    value = getattr(card.attributes, "luck", None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _luck_spend_rejected(
    *,
    player_id: str,
    amount: int,
    before: int | None,
    after: int | None,
    reason: str,
) -> LuckSpendResult:
    return LuckSpendResult(
        player_id=player_id,
        requested_spend=amount,
        accepted=False,
        resource_delta=ResourceDelta(
            owner_id=player_id,
            resource="luck",
            before=before,
            after=after,
            delta=0,
            applied=False,
            reason=reason,
        ),
        reason=reason,
    )


def _attribute_values(card: InvestigatorCard) -> Mapping[str, int]:
    values = card.attributes.as_dict()
    return {key: value for key, value in values.items() if isinstance(value, int)}


def _roll_level_label(success_level: str) -> str:
    return {
        "critical": "大成功",
        "extreme": "极难成功",
        "hard": "困难成功",
        "regular": "成功",
        "fail": "失败",
        "fumble": "大失败",
    }.get(success_level, "")


__all__ = [
    "CheckRequest",
    "CheckResult",
    "CocRuleEngine",
    "CombatDamageResult",
    "CombatRoundState",
    "CombatantState",
    "D100RollAudit",
    "InsanityTransition",
    "InvestigatorInsanityState",
    "LuckSpendResult",
    "OpposedCheckRequest",
    "OpposedCheckResult",
    "ResourceDelta",
    "ChaseAdvanceResult",
    "ChaseParticipantState",
    "ChaseState",
    "advance_chase",
    "apply_combat_damage",
    "apply_insanity_event",
    "apply_luck_spend",
    "apply_resource_delta_to_session",
    "build_combat_round",
    "chase_move_advantage",
    "check_value_from_card",
    "check_value_from_session",
    "check_result_to_dice_roll_audit",
    "compare_opposed_results",
    "difficulty_threshold",
    "luck_spend_to_dice_roll_audit",
    "success_level",
]
