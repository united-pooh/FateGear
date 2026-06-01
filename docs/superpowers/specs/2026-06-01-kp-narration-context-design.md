# KP Narration Context Design

## Objective

FateGear needs a Keeper narration layer that improves causal consistency first, atmosphere second, and NPC presence third. The narration system must combine the useful parts of MVU-style variable updates, Magic Context-style managed memory, and vector retrieval without letting model-generated text become the source of game truth.

The current runtime already produces deterministic turn results through `SceneRuntime.resolve_turn()`, `TurnResolution`, and `RuntimeEvent`. The proposed narration design builds on that boundary: committed runtime facts remain authoritative, while model output is limited to narration text and auditable narrative-memory patch proposals.

## Approved Priorities

1. Causal consistency is the first priority.
2. Atmosphere and prose quality are the second priority.
3. NPC presence is the third priority.
4. Multi-user private/public perspective splitting is out of scope for the first version, though the data model keeps a future `scope` field.

## Chosen Approach

Use a hybrid of:

- Runtime-authoritative facts from `TurnResolution`, `RuntimeEvent`, session snapshot, scene state, and story state.
- MVU-style structured narrative patches that update only `NarrativeState`.
- Magic Context-style layered context management.
- First-version vector retrieval through `VectorContextStore`, restricted to auxiliary memory and style continuity.

The key rule is simple: narration may be beautiful, but facts must come from committed runtime data.

## Current Project Fit

The design follows existing README boundaries:

- One turn is split into `KeeperAgent(Plan)` and `KeeperAgent(Render)`.
- `KeeperAgent(Render)` generates text after rule results are committed.
- Session snapshots support high-frequency prompt construction.
- Event logs support audit and replay.
- Existing README checklist entries for `PromptBuilder + two-stage Agent` already include prompt layers, structured outputs, read-only render behavior, fallback templates, and replayable agent output.

This proposal narrows the next narration feature to the Render side. It does not replace the rule engine, story transition validator, or session state store.

## Architecture

The first version adds a narration pipeline after deterministic turn resolution:

```text
SceneRuntime.resolve_turn()
  -> TurnResolution + RuntimeEvent[]
  -> NarrationContextBuilder
  -> NarrationInputPacket
  -> VectorContextStore.retrieve()
  -> NarrationPromptBuilder
  -> KeeperAgent(Render)
  -> KeeperNarrationDraft
  -> NarrationValidator
  -> KeeperNarrationRecord
  -> NarrativeState patch application
  -> VectorContextStore async write
```

### Component Responsibilities

`NarrationContextBuilder`

- Builds the factual render input from committed runtime state.
- Includes current scene, story stage, rule facts, state diffs, current `NarrativeState`, and forbidden facts.
- Does not read the full chat history directly.

`VectorContextStore`

- Retrieves long-running narrative memory, NPC memory, scene memory, and clue memory.
- Stores summaries and metadata after a narration record is accepted.
- Cannot be used as a source of game truth.

`NarrationPromptBuilder`

- Compiles a layered prompt with explicit priority.
- Places committed facts above vector memories and narrative continuity state.
- Preserves event ids and memory ids for audit.

`KeeperAgent(Render)`

- Produces public narration, NPC lines, keeper notes, cited event ids, cited memory ids, and patch proposals.
- Does not change state directly.

`NarrationValidator`

- Validates schema, fact consistency, forbidden fact leakage, memory citations, and patch legality.
- Rejects unsafe text or unsafe patches before persistence.

`NarrativeState`

- Stores narration continuity only.
- Tracks atmosphere, tension, sensory anchors, NPC surface attitudes, revealed clues, unresolved questions, and continuity constraints.
- Does not store authoritative flags, clock values, locations, story stages, or check results.

`KeeperNarrationRecord`

- Persists final narration text, accepted patches, rejected patches, event citations, memory citations, model metadata, and fallback state.
- Serves audit, replay, and debugging.

## Data Model

### NarrationInputPacket

`NarrationInputPacket` is the only trusted input to Render. It is built from committed state.

Suggested fields:

- `session_id`
- `turn_no`
- `turn_resolution`
- `scene_snapshot`
- `story_snapshot`
- `rule_facts`
- `recent_narration_summary`
- `narrative_state`
- `forbidden_facts`

Field notes:

- `turn_resolution` keeps the raw `TurnResolution`.
- `scene_snapshot` includes current scene, scene description, completed actions, and local flags.
- `story_snapshot` includes current `StoryState`, current stage description, and allowed current-stage hints.
- `rule_facts` normalizes check results, success or failure, effects, clock changes, and story transition diffs.
- `recent_narration_summary` is only style and continuity memory, not a fact source.
- `forbidden_facts` lists hidden facts that cannot be leaked in public narration.

### NarrativeState

`NarrativeState` is an MVU-like variable layer for narrative continuity.

Suggested fields:

- `scene_mood`
- `tension_level`
- `sensory_anchors`
- `npc_attitudes`
- `revealed_clues`
- `unresolved_questions`
- `continuity_constraints`

Example value meanings:

- `scene_mood`: current atmosphere such as pressure, silence, confusion, dread, urgency.
- `tension_level`: integer range `0..5`.
- `sensory_anchors`: recurring sensory details such as iron smell, wheel rhythm, cold wind.
- `npc_attitudes`: NPC surface behavior and tone visible in narration.
- `revealed_clues`: clues already explicitly described to players.
- `unresolved_questions`: mysteries the players have perceived but not explained.
- `continuity_constraints`: facts of prior narration that must not be contradicted.

### NarrationPatchProposal

`NarrationPatchProposal` is the only way model output can request changes to `NarrativeState`.

Suggested fields:

- `path`
- `old_value`
- `new_value`
- `reason`
- `source_event_ids`
- `confidence`
- `scope`

Validation rules:

- `old_value` must match the current `NarrativeState` value at `path`.
- `path` must be in an allowlist.
- `new_value` must match the target type and range.
- `reason` must be grounded in runtime events or accepted memory.
- `source_event_ids` must resolve to current turn events or trusted historical summaries.
- `scope` accepts only `public` in the first version.
- Patches cannot update `StoryState`, scene location, global flags, local flags, clocks, check results, completed actions, or endings.

### KeeperNarrationDraft

`KeeperNarrationDraft` is model output before validation.

Suggested fields:

- `public_text`
- `npc_lines`
- `keeper_notes`
- `patch_proposals`
- `source_event_ids`
- `cited_memory_ids`
- `style_notes`

### KeeperNarrationRecord

`KeeperNarrationRecord` is the persisted, validated record.

Suggested fields:

- `public_text`
- `npc_lines`
- `keeper_notes`
- `accepted_patches`
- `rejected_patches`
- `source_event_ids`
- `cited_memory_ids`
- `model_info`
- `fallback_used`
- `validation_warnings`

## PromptBuilder And Vector Context

The PromptBuilder is a layered context compiler, not a chat-history concatenator.

### Layer 1: Permanent Rules

Stable and cache-friendly rules:

- Render is read-only.
- Do not rewrite check results.
- Do not invent uncommitted movement, flags, clocks, endings, or story transitions.
- Do not reveal forbidden facts.
- Do not treat vector retrieval as authoritative truth.
- If vector memory conflicts with committed facts, ignore the vector memory.
- Output must include factual citations and patch proposals.

### Layer 2: Authoritative Facts

This layer has the highest priority and is never removed.

Inputs:

- Current `RuntimeEvent` list.
- Check success or failure.
- Applied flags and removed flags.
- Clock deltas and triggered clock events.
- Story transition diff.
- Player action results.
- Current scene and current story stage.

This layer should be rendered as a concise fact list, not prose.

### Layer 3: Module Static Context

Only include currently relevant static module content:

- Current module tone.
- Current scene source description.
- Current stage description.
- Related NPC static definitions.
- Clues allowed in the current stage.

Do not include future scenes, future clues, or future endings in the first version.

### Layer 4: Vector Retrieval Context

`VectorContextStore` retrieves auxiliary memories.

Retrieval query sources:

- Current scene id and scene name.
- Player action summaries.
- Current runtime event types.
- Current `StoryStage`.
- Related NPC ids or names.
- Current unresolved questions and sensory anchors.

Initial collections:

- `narration_memory`: historical narration summaries, motifs, and foreshadowing.
- `npc_memory`: NPC tone, lines, attitude, and disclosed information.
- `scene_memory`: how the scene has been described before.
- `clue_memory`: public clues and questions the players have noticed.

Each retrieved item must include metadata:

- `memory_id`
- `source_turn`
- `source_event_ids`
- `scope`
- `kind`
- `confidence`
- `created_from`
- `summary_text`

Vector retrieval rules:

- Retrieval results cannot prove game facts.
- Retrieval results with matching `source_event_ids` can be strong auxiliary context.
- Retrieval results without event provenance can only influence style.
- Retrieval results that conflict with current `TurnResolution` are discarded.
- Retrieval results that conflict with current `NarrativeState` are de-prioritized or flagged.

### Layer 5: NarrativeState

This deterministic snapshot stores current narration continuity.

If `NarrativeState` conflicts with committed runtime facts, committed runtime facts win. If it conflicts with retrieved memory, `NarrativeState` wins for the current turn and the conflict is logged.

### Layer 6: Output Contract

The final prompt section specifies the expected structured output:

- `public_text`
- `npc_lines`
- `keeper_notes`
- `patch_proposals`
- `source_event_ids`
- `cited_memory_ids`
- `style_notes`

## Token Strategy

The first version uses a deterministic context budget with vector retrieval.

Priority order:

1. Permanent rules are fixed and short.
2. Authoritative facts are never removed.
3. Current scene and current story stage are included.
4. High-confidence vector memories with event provenance are included.
5. Current `NarrativeState` is included with field limits.
6. Lower-confidence vector memories are trimmed first.
7. Recent summaries are compressed before being dropped.

Trimming order:

1. Remove low-confidence vector memories.
2. Remove vector memories without event provenance.
3. Compress recent narration summaries.
4. Trim long `NarrativeState` lists to the most relevant items.
5. Compress module static text to current scene and current stage essentials.

Never trim:

- Current turn event ids.
- Check results.
- Applied state diffs.
- Forbidden facts.
- Output schema.

## Vector Write Strategy

After a `KeeperNarrationRecord` is accepted, write memories asynchronously.

Write targets:

- `public_text` summary to `narration_memory`.
- `npc_lines` and accepted NPC attitude patches to `npc_memory`.
- accepted scene mood and sensory anchors to `scene_memory`.
- accepted revealed clues and unresolved questions to `clue_memory`.

Metadata should include source turn, source event ids, scope, kind, confidence, and source record id.

Rejected patches should not be written to vector memory. They should remain in audit logs only.

## Validation

### Schema Validation

All model output must pass schema validation first.

Required behavior:

- Missing `public_text` rejects the model output.
- Invalid `patch_proposals` reject those patches.
- `cited_memory_ids` must exist in this turn's retrieval result.
- `source_event_ids` must be a list.

Schema failure uses fallback narration.

### Fact Validation

`NarrationValidator` compares draft text and citations against `NarrationInputPacket`.

It rejects or falls back when:

- A failed check is narrated as success.
- A success effect is described without being committed.
- A movement, ending, clock change, flag, or story transition is invented.
- A forbidden fact appears in public narration.
- A vector memory contradicts authoritative facts and is still used as a fact.

### Patch Validation

`NarrationPatchProposal` validation follows MVU-style old-value checking.

It rejects a patch when:

- `old_value` does not match the current state.
- `path` is not allowlisted.
- `new_value` has the wrong type or invalid range.
- `scope` is not `public`.
- `source_event_ids` cannot be resolved.
- The patch tries to change authoritative game state.

Patch rejection does not necessarily reject the narration text. Narration text is rejected only when it is factually unsafe or leaks hidden facts.

## Fallback Behavior

Fallbacks are explicit and audited.

### Schema Error

If model output is structurally invalid:

- Generate a safe template narration.
- Set `fallback_used` to `schema_error`.
- Do not apply patches.

### Fact Conflict

If model text contradicts authoritative facts:

- Discard model text.
- Generate safe narration from `RuntimeEvent.to_log_line()` and normalized rule facts.
- Set `fallback_used` to `fact_conflict`.
- Store validation warnings.

### Partial Patch Rejection

If text is safe but some patches fail:

- Save the text.
- Apply accepted patches only.
- Store rejected patches with reasons.
- Set `fallback_used` to empty or `partial_patch_rejection`.

## Testing Strategy

The first version tests correctness before prose quality.

Required tests:

- Failed checks are not narrated as success.
- Untriggered flags do not appear in `public_text`.
- Forbidden facts do not appear in `public_text`.
- Conflicting vector memory loses to current `TurnResolution`.
- A patch with mismatched `old_value` is rejected.
- A patch targeting authoritative game state is rejected.
- A valid public `NarrativeState` patch is accepted.
- Schema-invalid model output falls back to template narration.
- `KeeperNarrationRecord` stores accepted patches, rejected patches, source event ids, cited memory ids, model info, and fallback status.
- The same `TurnResolution` plus mock agent output can be replayed deterministically.

Useful integration tests:

- One resolved action feeds `NarrationInputPacket` and produces safe narration.
- One retrieved NPC memory affects NPC wording without changing facts.
- One scene memory affects sensory continuity without changing flags or clocks.
- One rejected vector memory conflict is visible in validation warnings.

## Logging And Debugging

Each turn should expose enough information for the Keeper to debug a bad narration.

Log or panel fields:

- Prompt layer summary.
- Retrieved vector memories.
- Used source event ids.
- Used memory ids.
- Accepted patches.
- Rejected patches and rejection reasons.
- Fallback state.
- Validation warnings.

This supports the existing audit goal: when narration is wrong, the developer can tell whether the issue came from context building, retrieval, model output, validation, or fallback.

## Scope

### In Scope

- Public narration only.
- Render-stage context packet.
- Narrative-only state variables.
- MVU-style patch proposals for `NarrativeState`.
- Vector retrieval for narration, NPC, scene, and clue memory.
- Schema, fact, patch, and memory validation.
- Fallback template narration.
- Auditable narration records.

### Out Of Scope

- Multi-user private perspective routing.
- Independent NPC agents.
- Model-driven authoritative state changes.
- RuleEngine redesign.
- TransitionValidator redesign.
- Full module authoring UI.
- Prose-quality scoring beyond safety and consistency tests.

## Open Design Decisions

The following are implementation choices for the next planning stage, not blockers for this design:

- Which vector backend to use first.
- Whether the first prompt schema is plain Pydantic JSON or a provider-specific structured output API.
- Exact persistence shape for `KeeperNarrationRecord`.
- Whether text fact validation begins as rule-based checks, LLM critique, or both.

## Acceptance Criteria

The design is successful when:

- Render-stage narration can be generated only from committed facts and auxiliary context.
- The model cannot persist authoritative game state changes.
- Narrative continuity can improve over turns through accepted `NarrativeState` patches.
- Vector retrieval improves long-running atmosphere and NPC continuity without overriding runtime facts.
- Bad model output degrades into correct template narration.
- Logs show enough evidence to replay and debug every narration decision.

## Best-Practice Summary

1. Keep game state, narrative state, and vector memory separate.
2. Let the model propose narrative patches, not write final state.
3. Attach source event ids to every factual claim.
4. Treat vector retrieval as memory, not truth.
5. Preserve a deterministic current snapshot.
6. Validate before persistence.
7. Prefer safe fallback over creative contradiction.
8. Build debug visibility from the first version.

## References

- FateGear README: two-stage judgement and narration, session snapshot priority, and `PromptBuilder + KeeperAgent` checklist items.
- MagVarUpdate: MVU-style structured variable updates with old-value style validation and auditable patches.
- Magic Context: managed context lifecycle, retrieval, summarization, and background memory ideas.
- SillyTavern Data Bank and Chat Vectorization: external memory and retrieval patterns for long-running chat contexts.
