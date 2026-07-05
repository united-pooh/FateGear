# Scenario State Store Contract

REQ-006 keeps `ScenarioStateStore` as the small runtime persistence boundary:
save/load/delete session snapshots, save/load turn resolutions, and list durable
session ids. Health and observability are intentionally a side protocol
(`ScenarioStateStoreHealth`) so `SceneRuntime` does not need extra runtime hooks.

## JSON Store Consistency

`JsonScenarioStateStore` is local-first and stdlib-only. Each public store
operation takes a non-blocking file lock at `<root>/.scenario-state.lock`. If
another process owns the lock, the operation raises
`ScenarioStateStoreLockError` and records the conflict in the health snapshot.

JSON writes use this order:

1. Serialize the full payload in memory.
2. Write to a unique hidden `*.tmp` file in the target directory.
3. Flush and `fsync` the temp file.
4. Atomically replace the target with `os.replace`.
5. Best-effort `fsync` the parent directory.

Scans only load `*.json` files, so abandoned temp files are observable but never
treated as valid state. Invalid JSON or schema-invalid state files are moved to
`<root>/quarantine/<category>/...` by default. The runtime then continues with
the remaining valid files, while `health_snapshot()` reports the last error,
quarantine count, operation counts, failure counts, and latency samples.

## Runtime And Audit Ordering

`SceneRuntime.resolve_turn` writes KTSL per-turn audit logs before durable store
updates. It then persists the `TurnResolution` before the latest
`SessionMapState` snapshot. The intended replay rule is:

1. Restored session snapshots are authoritative for current live state.
2. Restored turn resolutions are authoritative for idempotent replay of already
   resolved turns.
3. KTSL/KP audit logs are an audit trail for stage traces, interventions, and
   ledger snapshots. They should be ordered by session id and turn number, but
   they are not the source of truth for recovering runtime state.

This means a crash between audit-log write and store write can leave an audit
artifact for a turn that is not yet durable in the runtime store. REQ-006 accepts
that ordering for the MVP; recovery should prefer the JSON store and surface any
orphaned audit files as audit diagnostics rather than replaying them as state.
