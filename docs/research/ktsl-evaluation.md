# KTSL deterministic evaluation

This report records a deterministic simulated research fixture evaluation for
the KTSL method. It is not a real empirical playtest, transcript audit, or
blind annotation result. The numbers below are generated locally from the
fixtures in `src/scenario/ktsl/` and should be treated as a reproducible
engineering check of the paper hypotheses, not as evidence about real tables.

## Hypotheses

- H1: Compared with baseline play, the Schedule layer reduces causal violation
  count and/or retcon count.
- H2: Compared with Schedule-only, the full KTSL Filter layer reduces
  unauthorized action and public high-sensitivity payload leak counts, while
  increasing declassification completeness.
- H3: Compared with Schedule-only, the full KTSL Coupling layer does not worsen
  spotlight maximum gap and reduces high-coupling time drift.

## Modes

- `baseline`: deterministic experienced-hosting baseline. Events are committed
  by spotlight declaration order and may contain local time overlap across
  causal dependencies.
- `schedule_only`: applies Schedule barriers and happened-before checks, but
  does not apply full Filter declassification/redaction or Coupling
  synchronization.
- `ktsl_full`: applies Schedule, Filter redaction/declassification, and
  high-coupling synchronization.

## Metrics

- `causal_violation`: settleable committed events with unmet, late, or
  overlapping causal dependencies.
- `unauthorized_action`: settleable actor decisions that reference unauthorized
  sensitive information.
- `public_payload_leak`: unauthorized sensitive information exposed through a
  public payload.
- `spotlight_max_gap`: maximum gap in minutes between consecutive committed
  spotlight windows.
- `declassification`: expected declassification pair coverage, from 0.00 to
  1.00.
- `retcon`: settleable events marked as retconned.
- `high_coupling_time_drift`: total drift minutes across high-coupling scene
  links.
- `barrier_wait`: wait minutes introduced by Schedule barriers.
- `committed_events`: settleable committed events counted by the audit.
- `blocked_events`: settleable blocked events counted by the audit.

## Actual Metric Data

Command:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m scenario.ktsl.evaluate
```

| fixture | mode | causal_violation | unauthorized_action | public_payload_leak | spotlight_max_gap | declassification | retcon | high_coupling_time_drift | barrier_wait | committed_events | blocked_events |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| library_sewer_church | baseline | 1 | 0 | 1 | 0 | 0.00 | 0 | 5 | 0 | 3 | 0 |
| library_sewer_church | schedule_only | 0 | 0 | 1 | 0 | 0.00 | 0 | 3 | 2 | 3 | 0 |
| library_sewer_church | ktsl_full | 0 | 0 | 0 | 0 | 1.00 | 0 | 0 | 2 | 3 | 0 |
| police_station_hospital_old_house | baseline | 1 | 1 | 2 | 0 | 0.00 | 0 | 5 | 0 | 3 | 0 |
| police_station_hospital_old_house | schedule_only | 0 | 1 | 2 | 0 | 0.00 | 0 | 3 | 2 | 3 | 0 |
| police_station_hospital_old_house | ktsl_full | 0 | 0 | 0 | 0 | 1.00 | 0 | 0 | 2 | 3 | 0 |

## Conclusions

H1 is supported by this deterministic fixture check for causal violations:
both fixtures produce one baseline causal violation and zero Schedule-only
causal violations. Retcon count remains zero in all modes, so the retcon part
of H1 is inconclusive in these fixtures.

H2 is supported in both fixtures. Schedule-only still exposes public sensitive
payloads, while `ktsl_full` reduces public payload leaks to zero and raises
declassification completeness from 0.00 to 1.00. The police/hospital/old-house
fixture also shows unauthorized action dropping from 1 to 0.

H3 is supported by this deterministic fixture check. `ktsl_full` keeps
`spotlight_max_gap` equal to Schedule-only and reduces high-coupling time drift
from 3 to 0 in both fixtures.

Because this is simulated fixture data, the next empirical step is still the
paper's proposed transcript audit: run baseline, Schedule-only, and KTSL-full
conditions on comparable 60 to 90 minute investigation segments and have
external annotators code the same metrics.
