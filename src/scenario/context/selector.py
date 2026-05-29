"""确定性的叙事上下文选择器。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..module.models import (
    ModuleDefinition,
    ModuleLorebookEntry,
)
from ..session.state import SessionMapState
from .models import (
    NarrativeContextLayer,
    SelectedAtmosphereContext,
    SelectedLorebookEntry,
    SelectedNPCContext,
    SelectedProseControls,
    SelectedSafetyBoundary,
)


class NarrativeContextSelector:
    """从模组与会话快照中选择本回合应注入的只读叙事上下文。"""

    def select(
        self,
        *,
        module: ModuleDefinition,
        session: SessionMapState,
        scene_id: str,
        recent_events: Sequence[object] | None = None,
        pending_intents: Mapping[str, Mapping[str, object]] | None = None,
        include_keeper: bool = True,
    ) -> NarrativeContextLayer:
        context = module.narrative_context
        stage_id = session.story_state.current_stage_id
        intent_map = pending_intents if pending_intents is not None else session.pending_intents
        action_ids = self._pending_action_ids(
            session=session,
            scene_id=scene_id,
            pending_intents=intent_map,
        )
        scan_text = self._scan_text(
            module=module,
            scene_id=scene_id,
            stage_id=stage_id,
            action_ids=action_ids,
            recent_events=recent_events or [],
        )
        skipped: dict[str, str] = {}
        selected_npcs = self._select_npcs(
            module=module,
            scene_id=scene_id,
            stage_id=stage_id,
            include_keeper=include_keeper,
            skipped=skipped,
        )
        selected_lore = self._select_lore(
            module=module,
            scene_id=scene_id,
            stage_id=stage_id,
            action_ids=action_ids,
            scan_text=scan_text,
            selected_npc_ids={npc.npc_id for npc in selected_npcs},
            include_keeper=include_keeper,
            skipped=skipped,
        )
        selected_safety = self._select_safety(
            module=module,
            scene_id=scene_id,
            stage_id=stage_id,
        )

        selected_ids = [
            *(f"npc:{npc.npc_id}" for npc in selected_npcs),
            *(f"lore:{entry.entry_id}" for entry in selected_lore),
            *(f"safety:{boundary.boundary_id}" for boundary in selected_safety),
        ]
        budget_used = len(context.worldview_brief)
        budget_used += sum(len(entry.content) for entry in selected_lore)
        budget_used += sum(len(npc.public_description) + len(npc.persona) for npc in selected_npcs)
        budget_used += sum(len(boundary.note) for boundary in selected_safety)

        return NarrativeContextLayer(
            worldview_brief=context.worldview_brief,
            selected_npcs=selected_npcs,
            selected_lorebook_entries=selected_lore,
            selected_safety_boundaries=selected_safety,
            atmosphere=SelectedAtmosphereContext(
                tone=context.atmosphere.tone,
                sensory_palette=context.atmosphere.sensory_palette,
                pacing_hint=context.atmosphere.pacing_hint,
                tension_axis=context.atmosphere.tension_axis,
                escalation_rules=context.atmosphere.escalation_rules,
                forbidden_reveals=context.atmosphere.forbidden_reveals,
                style_rules=context.atmosphere.style_rules,
            ),
            prose_controls=SelectedProseControls(
                language=context.prose_controls.language,
                narrative_person=context.prose_controls.narrative_person,
                tense=context.prose_controls.tense,
                paragraph_limit=context.prose_controls.paragraph_limit,
                horror_intensity=context.prose_controls.horror_intensity,
                dice_visibility=context.prose_controls.dice_visibility,
                clue_fairness=context.prose_controls.clue_fairness,
                avoid_fourth_wall=context.prose_controls.avoid_fourth_wall,
                style_rules=context.prose_controls.style_rules,
            ),
            selected_ids=selected_ids,
            skipped_ids=skipped,
            budget_used_chars=budget_used,
            max_context_chars=context.max_context_chars,
            channel="keeper" if include_keeper else "public",
        )

    def _select_npcs(
        self,
        *,
        module: ModuleDefinition,
        scene_id: str,
        stage_id: str,
        include_keeper: bool,
        skipped: dict[str, str],
    ) -> list[SelectedNPCContext]:
        selected: list[SelectedNPCContext] = []
        for npc in sorted(module.narrative_context.npcs, key=lambda item: item.id):
            if npc.visibility == "keeper" and not include_keeper:
                skipped[f"npc:{npc.id}"] = "keeper_only"
                continue
            reason = self._npc_activation_reason(
                scene_ids=npc.active_scene_ids,
                stage_ids=npc.active_stage_ids,
                scene_id=scene_id,
                stage_id=stage_id,
            )
            if reason is None:
                skipped[f"npc:{npc.id}"] = "scope_not_matched"
                continue
            selected.append(
                SelectedNPCContext(
                    npc_id=npc.id,
                    name=npc.name,
                    role=npc.role,
                    public_description=npc.public_description,
                    persona=npc.persona,
                    speaking_style=npc.speaking_style,
                    goals=npc.goals,
                    knowledge_boundary=npc.knowledge_boundary,
                    secrets=npc.secrets if include_keeper else [],
                    visibility=npc.visibility,
                    selection_reason=reason,
                )
            )
        return selected

    def _npc_activation_reason(
        self,
        *,
        scene_ids: Sequence[str],
        stage_ids: Sequence[str],
        scene_id: str,
        stage_id: str,
    ) -> str | None:
        if not scene_ids and not stage_ids:
            return "global_npc"
        if scene_ids and scene_id not in scene_ids:
            return None
        if stage_ids and stage_id not in stage_ids:
            return None
        if scene_ids and stage_ids:
            return "scene_and_stage_scope"
        if scene_ids:
            return "scene_scope"
        return "stage_scope"

    def _select_lore(
        self,
        *,
        module: ModuleDefinition,
        scene_id: str,
        stage_id: str,
        action_ids: set[str],
        scan_text: str,
        selected_npc_ids: set[str],
        include_keeper: bool,
        skipped: dict[str, str],
    ) -> list[SelectedLorebookEntry]:
        selected: list[SelectedLorebookEntry] = []
        used_chars = len(module.narrative_context.worldview_brief)
        candidates = sorted(
            module.narrative_context.lorebook_entries,
            key=lambda item: (-item.priority, item.insertion_order, item.id),
        )
        for entry in candidates:
            key = f"lore:{entry.id}"
            if not entry.enabled:
                skipped[key] = "disabled"
                continue
            if entry.visibility == "keeper" and not include_keeper:
                skipped[key] = "keeper_only"
                continue
            reason = self._lore_activation_reason(
                entry=entry,
                scene_id=scene_id,
                stage_id=stage_id,
                action_ids=action_ids,
                scan_text=scan_text,
                selected_npc_ids=selected_npc_ids,
            )
            if reason is None:
                skipped[key] = "trigger_not_matched"
                continue
            if len(selected) >= module.narrative_context.max_lore_entries:
                skipped[key] = "max_lore_entries_reached"
                continue
            next_used = used_chars + len(entry.content)
            if next_used > module.narrative_context.max_context_chars:
                skipped[key] = "context_budget_exceeded"
                continue
            used_chars = next_used
            selected.append(
                SelectedLorebookEntry(
                    entry_id=entry.id,
                    title=entry.title,
                    content=entry.content,
                    visibility=entry.visibility,
                    priority=entry.priority,
                    insertion_order=entry.insertion_order,
                    selection_reason=reason,
                )
            )
        return selected

    def _select_safety(
        self,
        *,
        module: ModuleDefinition,
        scene_id: str,
        stage_id: str,
    ) -> list[SelectedSafetyBoundary]:
        selected: list[SelectedSafetyBoundary] = []
        for boundary in sorted(
            module.narrative_context.safety_boundaries,
            key=lambda item: (item.severity, item.id),
        ):
            reason = self._activation_reason(
                scene_ids=boundary.scope_scene_ids,
                stage_ids=boundary.scope_stage_ids,
                scene_id=scene_id,
                stage_id=stage_id,
                empty_reason="global_safety",
            )
            if reason is None:
                continue
            selected.append(
                SelectedSafetyBoundary(
                    boundary_id=boundary.id,
                    note=boundary.note,
                    severity=boundary.severity,
                    selection_reason=reason,
                )
            )
        return selected

    def _lore_activation_reason(
        self,
        *,
        entry: ModuleLorebookEntry,
        scene_id: str,
        stage_id: str,
        action_ids: set[str],
        scan_text: str,
        selected_npc_ids: set[str],
    ) -> str | None:
        if entry.always_on:
            return "always_on"
        if scene_id in entry.scope_scene_ids:
            return "scene_scope"
        if stage_id in entry.scope_stage_ids:
            return "stage_scope"
        if action_ids.intersection(entry.scope_action_ids):
            return "action_scope"
        if selected_npc_ids.intersection(entry.npc_ids):
            return "npc_scope"
        lowered = scan_text.lower()
        for keyword in entry.keywords:
            if keyword.lower() in lowered:
                return f"keyword:{keyword}"
        return None

    def _activation_reason(
        self,
        *,
        scene_ids: Sequence[str],
        stage_ids: Sequence[str],
        scene_id: str,
        stage_id: str,
        empty_reason: str,
    ) -> str | None:
        if not scene_ids and not stage_ids:
            return empty_reason
        if scene_ids and scene_id in scene_ids:
            return "scene_scope"
        if stage_ids and stage_id in stage_ids:
            return "stage_scope"
        return None

    def _pending_action_ids(
        self,
        *,
        session: SessionMapState,
        scene_id: str,
        pending_intents: Mapping[str, Mapping[str, object]],
    ) -> set[str]:
        action_ids: set[str] = set()
        for player_id, intent in pending_intents.items():
            player_state = session.player_states.get(player_id)
            if player_state is None or player_state.current_scene_id != scene_id:
                continue
            if intent.get("type") == "action":
                action_id = str(intent.get("action_id", ""))
                if action_id:
                    action_ids.add(action_id)
        return action_ids

    def _scan_text(
        self,
        *,
        module: ModuleDefinition,
        scene_id: str,
        stage_id: str,
        action_ids: set[str],
        recent_events: Sequence[object],
    ) -> str:
        scene = module.scene_map().get(scene_id)
        stage = module.story_stage_map().get(stage_id)
        action_map = module.action_map()
        parts: list[str] = []
        if scene is not None:
            parts.extend([scene.id, scene.name, scene.description, *scene.tags])
        if stage is not None:
            parts.extend([stage.id, stage.name, stage.description])
        for action_id in sorted(action_ids):
            action = action_map.get(action_id)
            parts.append(action_id)
            if action is not None:
                parts.extend([action.name, action.kind])
        parts.extend(
            str(message)
            for event in recent_events
            if (message := getattr(event, "message", ""))
        )
        return "\n".join(parts)
