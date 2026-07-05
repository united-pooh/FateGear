"""Clue graph models and fail-forward planning helpers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DiscoveryState = Literal[
    "unknown",
    "discovered",
    "missed",
    "misinterpreted",
    "redundant",
    "delivered_by_fail_forward",
]
ClueEdgeKind = Literal["prerequisite", "redundancy", "points_to"]
FailForwardDeliveryVia = Literal[
    "missed_hint",
    "redundant_clue",
    "points_to_clue",
    "route_fallback",
]

DISCOVERY_STATES: tuple[DiscoveryState, ...] = (
    "unknown",
    "discovered",
    "missed",
    "misinterpreted",
    "redundant",
    "delivered_by_fail_forward",
)
PLAYER_VISIBLE_STATES: frozenset[DiscoveryState] = frozenset(
    {
        "discovered",
        "misinterpreted",
        "redundant",
        "delivered_by_fail_forward",
    }
)
ROUTE_COVERING_STATES: frozenset[DiscoveryState] = frozenset(
    {"discovered", "delivered_by_fail_forward", "redundant"}
)


class ModuleClue(BaseModel):
    """Static clue definition authored with a module.

    ``info_id`` and ``output_info_ids`` intentionally mirror the KTSL
    ``ClueRecord`` naming so a future runtime adapter can map between the two
    without touching KTSL core models.
    """

    id: str = Field(..., min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=120)
    scene_id: str = Field(..., min_length=1, max_length=60)
    info_id: str = Field(default="", max_length=80)
    public_hint: str = Field(default="", max_length=800)
    private_payload: str = Field(default="", max_length=2000)
    route_ids: list[str] = Field(default_factory=list, max_length=20)
    required_info_ids: list[str] = Field(default_factory=list, max_length=20)
    prerequisite_clue_ids: list[str] = Field(default_factory=list, max_length=20)
    redundant_with_clue_ids: list[str] = Field(default_factory=list, max_length=20)
    points_to_clue_ids: list[str] = Field(default_factory=list, max_length=20)
    fail_forward_hint: str = Field(default="", max_length=800)
    fail_forward_route_ids: list[str] = Field(default_factory=list, max_length=20)
    output_info_ids: list[str] = Field(default_factory=list, max_length=20)
    visible_to_player_ids: list[str] = Field(default_factory=list, max_length=40)

    @classmethod
    def from_ktsl_record(cls, record: object) -> "ModuleClue":
        """Build a module clue from a KTSL-like ``ClueRecord`` object."""

        return cls(
            id=str(getattr(record, "id")),
            title=str(getattr(record, "title")),
            scene_id=str(getattr(record, "scene_id")),
            info_id=str(getattr(record, "info_id")),
            public_hint=str(getattr(record, "public_hint", "")),
            private_payload=str(getattr(record, "keeper_detail", "")),
            required_info_ids=list(getattr(record, "required_info_ids", [])),
            output_info_ids=list(getattr(record, "output_info_ids", [])),
        )

    def visible_to_player(self, player_id: str) -> bool:
        return not self.visible_to_player_ids or player_id in self.visible_to_player_ids


class ClueEdge(BaseModel):
    kind: ClueEdgeKind
    source_clue_id: str = Field(..., min_length=1, max_length=80)
    target_clue_id: str = Field(..., min_length=1, max_length=80)


class ClueRouteCoverage(BaseModel):
    route_id: str = Field(..., min_length=1, max_length=80)
    clue_ids: list[str] = Field(default_factory=list)
    covered_clue_ids: list[str] = Field(default_factory=list)
    missed_clue_ids: list[str] = Field(default_factory=list)
    reachable_clue_ids: list[str] = Field(default_factory=list)
    is_covered: bool = False
    is_reachable: bool = False


class FailForwardDelivery(BaseModel):
    clue_id: str = Field(..., min_length=1, max_length=80)
    state: DiscoveryState = "delivered_by_fail_forward"
    via: FailForwardDeliveryVia
    route_ids: list[str] = Field(default_factory=list)
    info_id: str = Field(default="", max_length=80)
    output_info_ids: list[str] = Field(default_factory=list)
    required_info_ids: list[str] = Field(default_factory=list)
    public_hint: str = Field(default="", max_length=800)
    reason: str = Field(default="", max_length=1000)


class FailForwardPlan(BaseModel):
    missed_clue_id: str = Field(..., min_length=1, max_length=80)
    deliveries: list[FailForwardDelivery] = Field(default_factory=list)
    route_coverage: dict[str, ClueRouteCoverage] = Field(default_factory=dict)
    core_routes_reachable: bool = True
    unresolved_core_route_ids: list[str] = Field(default_factory=list)


class SessionClueState(BaseModel):
    """Serializable per-session clue discovery state."""

    model_config = ConfigDict(validate_assignment=True)

    clue_states: dict[str, DiscoveryState] = Field(default_factory=dict)
    delivered_by_fail_forward: list[str] = Field(default_factory=list)
    last_updated_turn: dict[str, int] = Field(default_factory=dict)

    def state_for(self, clue_id: str) -> DiscoveryState:
        return self.clue_states.get(clue_id, "unknown")

    def mark(
        self,
        clue_id: str,
        state: DiscoveryState,
        *,
        turn: int | None = None,
    ) -> None:
        self.clue_states[clue_id] = state
        if turn is not None:
            self.last_updated_turn[clue_id] = turn
        if state == "delivered_by_fail_forward":
            if clue_id not in self.delivered_by_fail_forward:
                self.delivered_by_fail_forward.append(clue_id)
        elif clue_id in self.delivered_by_fail_forward:
            self.delivered_by_fail_forward.remove(clue_id)

    def apply_fail_forward_plan(
        self,
        plan: FailForwardPlan,
        *,
        turn: int | None = None,
    ) -> "SessionClueState":
        next_state = self.model_copy(deep=True)
        next_state.mark(plan.missed_clue_id, "missed", turn=turn)
        for delivery in plan.deliveries:
            next_state.mark(delivery.clue_id, delivery.state, turn=turn)
        return next_state


class PlayerClueView(BaseModel):
    clue_id: str
    title: str
    scene_id: str
    state: DiscoveryState
    info_id: str = ""
    public_hint: str = ""
    route_ids: list[str] = Field(default_factory=list)
    required_info_ids: list[str] = Field(default_factory=list)
    output_info_ids: list[str] = Field(default_factory=list)


class KeeperClueView(BaseModel):
    clue_id: str
    title: str
    scene_id: str
    state: DiscoveryState
    info_id: str = ""
    public_hint: str = ""
    private_payload: str = ""
    route_ids: list[str] = Field(default_factory=list)
    prerequisite_clue_ids: list[str] = Field(default_factory=list)
    required_info_ids: list[str] = Field(default_factory=list)
    redundant_with_clue_ids: list[str] = Field(default_factory=list)
    points_to_clue_ids: list[str] = Field(default_factory=list)
    fail_forward_hint: str = ""
    fail_forward_route_ids: list[str] = Field(default_factory=list)
    output_info_ids: list[str] = Field(default_factory=list)


class ClueGraph(BaseModel):
    """Serializable module clue graph plus deterministic helper methods."""

    module_id: str = Field(..., min_length=1, max_length=30)
    clues: list[ModuleClue] = Field(default_factory=list)
    edges: list[ClueEdge] = Field(default_factory=list)
    core_route_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_graph_refs(self) -> "ClueGraph":
        clue_ids = [clue.id for clue in self.clues]
        if len(clue_ids) != len(set(clue_ids)):
            raise ValueError("clue ids must be unique")

        clue_id_set = set(clue_ids)
        for clue in self.clues:
            for ref in clue.prerequisite_clue_ids:
                if ref not in clue_id_set:
                    raise ValueError(
                        f"clue {clue.id!r} prerequisite {ref!r} not in clues"
                    )
            for ref in clue.redundant_with_clue_ids:
                if ref not in clue_id_set:
                    raise ValueError(
                        f"clue {clue.id!r} redundancy {ref!r} not in clues"
                    )
            for ref in clue.points_to_clue_ids:
                if ref not in clue_id_set:
                    raise ValueError(
                        f"clue {clue.id!r} points_to {ref!r} not in clues"
                    )

        for edge in self.edges:
            if edge.source_clue_id not in clue_id_set:
                raise ValueError(
                    f"edge source {edge.source_clue_id!r} not in clues"
                )
            if edge.target_clue_id not in clue_id_set:
                raise ValueError(
                    f"edge target {edge.target_clue_id!r} not in clues"
                )
        return self

    def clue_map(self) -> dict[str, ModuleClue]:
        return {clue.id: clue for clue in self.clues}

    def all_route_ids(self) -> list[str]:
        route_ids: set[str] = set(self.core_route_ids)
        for clue in self.clues:
            route_ids.update(clue.route_ids)
            route_ids.update(clue.fail_forward_route_ids)
        return sorted(route_ids)

    def all_edges(self) -> list[ClueEdge]:
        edge_keys: set[tuple[ClueEdgeKind, str, str]] = set()
        edges: list[ClueEdge] = []

        def add(kind: ClueEdgeKind, source: str, target: str) -> None:
            key = (kind, source, target)
            if key in edge_keys:
                return
            edge_keys.add(key)
            edges.append(
                ClueEdge(
                    kind=kind,
                    source_clue_id=source,
                    target_clue_id=target,
                )
            )

        for edge in self.edges:
            add(edge.kind, edge.source_clue_id, edge.target_clue_id)
        for clue in self.clues:
            for prerequisite_id in clue.prerequisite_clue_ids:
                add("prerequisite", prerequisite_id, clue.id)
            for redundant_id in clue.redundant_with_clue_ids:
                add("redundancy", clue.id, redundant_id)
            for target_id in clue.points_to_clue_ids:
                add("points_to", clue.id, target_id)
        return edges

    def core_route_coverage(
        self,
        session_state: SessionClueState | None = None,
    ) -> dict[str, ClueRouteCoverage]:
        state = session_state or SessionClueState()
        routes = self.core_route_ids or self.all_route_ids()
        coverage: dict[str, ClueRouteCoverage] = {}
        for route_id in routes:
            clues = [
                clue
                for clue in self.clues
                if route_id in clue.route_ids or route_id in clue.fail_forward_route_ids
            ]
            covered = [
                clue.id
                for clue in clues
                if state.state_for(clue.id) in ROUTE_COVERING_STATES
            ]
            missed = [
                clue.id
                for clue in clues
                if state.state_for(clue.id) == "missed"
            ]
            reachable = [
                clue.id
                for clue in clues
                if self._is_reachable(clue, state)
            ]
            coverage[route_id] = ClueRouteCoverage(
                route_id=route_id,
                clue_ids=[clue.id for clue in clues],
                covered_clue_ids=covered,
                missed_clue_ids=missed,
                reachable_clue_ids=reachable,
                is_covered=bool(covered),
                is_reachable=bool(covered or reachable),
            )
        return coverage

    def plan_fail_forward_delivery(
        self,
        session_state: SessionClueState,
        missed_clue_id: str,
    ) -> FailForwardPlan:
        clue_by_id = self.clue_map()
        if missed_clue_id not in clue_by_id:
            raise ValueError(f"missed clue {missed_clue_id!r} not in clues")

        missed_clue = clue_by_id[missed_clue_id]
        after_miss = session_state.model_copy(deep=True)
        after_miss.mark(missed_clue_id, "missed")

        impacted_core_routes = self._impacted_core_routes(missed_clue)
        if not impacted_core_routes:
            coverage = self.core_route_coverage(after_miss)
            return FailForwardPlan(
                missed_clue_id=missed_clue_id,
                deliveries=[],
                route_coverage=coverage,
                core_routes_reachable=True,
            )

        planned_state = after_miss.model_copy(deep=True)
        deliveries: list[FailForwardDelivery] = []
        delivered_ids: set[str] = set()
        for route_id in impacted_core_routes:
            route_coverage = self.core_route_coverage(planned_state).get(route_id)
            if route_coverage and route_coverage.is_covered:
                continue

            for candidate, via in self._delivery_candidates(missed_clue, route_id):
                if candidate.id in delivered_ids:
                    continue
                delivery = self._delivery_for_candidate(candidate, route_id, via)
                if delivery is None:
                    continue
                deliveries.append(delivery)
                delivered_ids.add(candidate.id)
                planned_state.mark(candidate.id, "delivered_by_fail_forward")
                break

        coverage_after_plan = self.core_route_coverage(planned_state)
        unresolved = [
            route_id
            for route_id in impacted_core_routes
            if not coverage_after_plan.get(
                route_id,
                ClueRouteCoverage(route_id=route_id),
            ).is_reachable
        ]
        return FailForwardPlan(
            missed_clue_id=missed_clue_id,
            deliveries=deliveries,
            route_coverage=coverage_after_plan,
            core_routes_reachable=not unresolved,
            unresolved_core_route_ids=unresolved,
        )

    def player_view(
        self,
        session_state: SessionClueState,
        *,
        player_id: str,
    ) -> list[PlayerClueView]:
        views: list[PlayerClueView] = []
        for clue in self.clues:
            state = session_state.state_for(clue.id)
            if state not in PLAYER_VISIBLE_STATES:
                continue
            if not clue.visible_to_player(player_id):
                continue
            views.append(
                PlayerClueView(
                    clue_id=clue.id,
                    title=clue.title,
                    scene_id=clue.scene_id,
                    state=state,
                    info_id=clue.info_id,
                    public_hint=clue.public_hint,
                    route_ids=list(clue.route_ids),
                    required_info_ids=list(clue.required_info_ids),
                    output_info_ids=list(clue.output_info_ids),
                )
            )
        return views

    def keeper_view(
        self,
        session_state: SessionClueState | None = None,
    ) -> list[KeeperClueView]:
        state = session_state or SessionClueState()
        return [
            KeeperClueView(
                clue_id=clue.id,
                title=clue.title,
                scene_id=clue.scene_id,
                state=state.state_for(clue.id),
                info_id=clue.info_id,
                public_hint=clue.public_hint,
                private_payload=clue.private_payload,
                route_ids=list(clue.route_ids),
                prerequisite_clue_ids=list(clue.prerequisite_clue_ids),
                required_info_ids=list(clue.required_info_ids),
                redundant_with_clue_ids=list(clue.redundant_with_clue_ids),
                points_to_clue_ids=list(clue.points_to_clue_ids),
                fail_forward_hint=clue.fail_forward_hint,
                fail_forward_route_ids=list(clue.fail_forward_route_ids),
                output_info_ids=list(clue.output_info_ids),
            )
            for clue in self.clues
        ]

    def _impacted_core_routes(self, missed_clue: ModuleClue) -> list[str]:
        core_routes = set(self.core_route_ids)
        route_ids = set(missed_clue.route_ids) | set(missed_clue.fail_forward_route_ids)
        if not core_routes:
            return sorted(route_ids)
        return sorted(route_ids & core_routes)

    def _is_reachable(self, clue: ModuleClue, state: SessionClueState) -> bool:
        clue_state = state.state_for(clue.id)
        if clue_state == "missed":
            return False
        if clue_state in ROUTE_COVERING_STATES:
            return True
        for prerequisite_id in clue.prerequisite_clue_ids:
            prerequisite_state = state.state_for(prerequisite_id)
            if prerequisite_state not in ROUTE_COVERING_STATES:
                return False
        return True

    def _delivery_candidates(
        self,
        missed_clue: ModuleClue,
        route_id: str,
    ) -> Iterable[tuple[ModuleClue, FailForwardDeliveryVia]]:
        clue_by_id = self.clue_map()
        if route_id in missed_clue.route_ids or route_id in missed_clue.fail_forward_route_ids:
            yield missed_clue, "missed_hint"

        redundant_ids: set[str] = set(missed_clue.redundant_with_clue_ids)
        for edge in self.all_edges():
            if edge.kind != "redundancy":
                continue
            if edge.source_clue_id == missed_clue.id:
                redundant_ids.add(edge.target_clue_id)
            if edge.target_clue_id == missed_clue.id:
                redundant_ids.add(edge.source_clue_id)
        for clue_id in sorted(redundant_ids):
            candidate = clue_by_id[clue_id]
            if route_id in candidate.route_ids or route_id in candidate.fail_forward_route_ids:
                yield candidate, "redundant_clue"

        points_to_ids: set[str] = set(missed_clue.points_to_clue_ids)
        for edge in self.all_edges():
            if edge.kind == "points_to" and edge.source_clue_id == missed_clue.id:
                points_to_ids.add(edge.target_clue_id)
        for clue_id in sorted(points_to_ids):
            candidate = clue_by_id[clue_id]
            if route_id in candidate.route_ids or route_id in candidate.fail_forward_route_ids:
                yield candidate, "points_to_clue"

        for candidate in sorted(self.clues, key=lambda clue: clue.id):
            if route_id in candidate.fail_forward_route_ids:
                yield candidate, "route_fallback"

    def _delivery_for_candidate(
        self,
        candidate: ModuleClue,
        route_id: str,
        via: FailForwardDeliveryVia,
    ) -> FailForwardDelivery | None:
        hint = candidate.fail_forward_hint or candidate.public_hint
        if not hint:
            return None
        return FailForwardDelivery(
            clue_id=candidate.id,
            via=via,
            route_ids=[route_id],
            info_id=candidate.info_id,
            required_info_ids=list(candidate.required_info_ids),
            output_info_ids=list(candidate.output_info_ids),
            public_hint=hint,
            reason=f"Preserve core route {route_id!r} after missed clue.",
        )


__all__ = [
    "ClueEdge",
    "ClueEdgeKind",
    "ClueGraph",
    "ClueRouteCoverage",
    "DISCOVERY_STATES",
    "DiscoveryState",
    "FailForwardDelivery",
    "FailForwardDeliveryVia",
    "FailForwardPlan",
    "KeeperClueView",
    "ModuleClue",
    "PlayerClueView",
    "SessionClueState",
]
