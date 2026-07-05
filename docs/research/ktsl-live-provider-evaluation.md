# KTSL live provider evaluation

This report records a real API-provider run of the KTSL live evaluation
runner. It compares model-produced audit metrics against the deterministic KTSL
oracle from `python -m scenario.ktsl.evaluate`.

The provider API keys were loaded from whitelisted variables in `~/.zshrc`.
No API key values are stored in this report.

## Provider Setup

- `longcat`: OpenAI-compatible endpoint `https://api.longcat.chat/openai/v1`,
  model `LongCat-2.0`.
- `deepseek`: OpenAI-compatible endpoint `https://api.deepseek.com`, model
  `deepseek-v4-pro`, with provider thinking disabled through the same
  compatibility option used by the existing FateGear DeepSeek agents.

LongCat's current `/models` response reported `LongCat-2.0`; the older
`LongCat-Flash-Chat` name returned `Unsupported model`.

## Command

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  python -m scenario.ktsl.live_evaluate \
  --provider longcat --provider deepseek \
  --format markdown --timeout 120
```

The live runner executes two fixtures across three modes for each provider:
`baseline`, `schedule_only`, and `ktsl_full`.

## Final Summary

This final run used canonical KTSL intermediate outputs in the live prompt:
`schedule_steps`, `filter_decisions`, `coupling_decisions`, `audit_entries`, and
expected declassification pairs. The models no longer had to infer committed
state from raw fixture seed fields.

| provider | model | cases | ok | json_valid | metric_match_rate | H1 | H2 | H3 | avg_latency_ms | total_tokens |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| longcat | LongCat-2.0 | 6 | 6 | 6 | 1.00 | 2/2 | 2/2 | 2/2 | 10132 | 30966 |
| deepseek | deepseek-v4-pro | 6 | 6 | 6 | 1.00 | 2/2 | 2/2 | 2/2 | 5897 | 32515 |

## Case Metrics

`oracle causal/leak/declass/drift` uses deterministic KTSL metrics. `model
causal/leak/declass/drift` uses the provider-returned JSON metrics.

| provider | fixture | mode | status | exact | oracle causal/leak/declass/drift | model causal/leak/declass/drift | latency_ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| longcat | library_sewer_church | baseline | ok | 10/10 | 1/1/0.0/5 | 1/1/0.0/5 | 11658 |
| longcat | library_sewer_church | schedule_only | ok | 10/10 | 0/1/0.0/3 | 0/1/0/3 | 10205 |
| longcat | library_sewer_church | ktsl_full | ok | 10/10 | 0/0/1.0/0 | 0/0/1/0 | 9266 |
| longcat | police_station_hospital_old_house | baseline | ok | 10/10 | 1/2/0.0/5 | 1/2/0/5 | 9877 |
| longcat | police_station_hospital_old_house | schedule_only | ok | 10/10 | 0/2/0.0/3 | 0/2/0/3 | 10028 |
| longcat | police_station_hospital_old_house | ktsl_full | ok | 10/10 | 0/0/1.0/0 | 0/0/1/0 | 9760 |
| deepseek | library_sewer_church | baseline | ok | 10/10 | 1/1/0.0/5 | 1/1/0.0/5 | 5998 |
| deepseek | library_sewer_church | schedule_only | ok | 10/10 | 0/1/0.0/3 | 0/1/0/3 | 4914 |
| deepseek | library_sewer_church | ktsl_full | ok | 10/10 | 0/0/1.0/0 | 0/0/1.0/0 | 5909 |
| deepseek | police_station_hospital_old_house | baseline | ok | 10/10 | 1/2/0.0/5 | 1/2/0.0/5 | 6325 |
| deepseek | police_station_hospital_old_house | schedule_only | ok | 10/10 | 0/2/0.0/3 | 0/2/0.0/3 | 5719 |
| deepseek | police_station_hospital_old_house | ktsl_full | ok | 10/10 | 0/0/1.0/0 | 0/0/1.0/0 | 6519 |

## Findings

Both providers were reachable and produced parseable JSON for all six final
cases after the runner added invalid-JSON retry support, a 1600-token output
budget, and canonical KTSL intermediate outputs in the prompt.

The earlier failing run showed both models reading raw `fixture.events[].status`
as authoritative and excluding proposed-but-settleable events. That made them
under-count causal violations, public leaks, declassification completeness, and
high-coupling drift. The fixed runner explicitly states that
`fixture.events[].status` is only a seed/proposal state and that
`schedule_steps[].status`, `filter_decisions`, `coupling_decisions`, and
`audit_entries` are authoritative.

After this change, both LongCat and DeepSeek matched the deterministic KTSL
oracle exactly for all 12 provider cases. H1, H2, and H3 all score `2/2` for
both providers in the final bench.

The token totals are provider-reported usage and should be treated as real API
accounting for this run only.
