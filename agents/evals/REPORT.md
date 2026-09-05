# Routing eval report

Generated: 2026-09-05T15:41:50.719585+00:00 — 25 cases x 3 reps, live Gemini via Vertex AI `global`, temperature=0.

## Headline metrics

- **Exact-set match (mean over reps):** 92.0%
- **Cross-run stability (all 3 reps agree):** 96.0%
- **Fallback rate (predictions outside the bespoke registry):** 11.1%
- **Self-reported confidence:** {'high': 75}

## Confidence calibration (accuracy within each confidence bucket)

| Confidence | Correct | Total | Accuracy |
|---|---|---|---|
| high | 69 | 75 | 92% |

Guidance thresholds (not yet enforced): match >= 90%, stability >= 95%, fallback < 10%.

## Per-domain precision/recall (run 1)

| Domain | Precision | Recall | TP/FP/FN |
|---|---|---|---|
| frontend | 100% | 100% | 3/0/0 |
| backend | 80% | 100% | 4/1/0 |
| infra-devops | 100% | 100% | 3/0/0 |
| mobile | 100% | 100% | 2/0/0 |
| data-ml | 100% | 100% | 2/0/0 |
| cli | 100% | 100% | 2/0/0 |
| embedded | 100% | 100% | 2/0/0 |
| game | 100% | 100% | 2/0/0 |
| security | 100% | 50% | 1/0/1 |
| database | 100% | 67% | 2/0/1 |

## Per-case results

| Case | Expected | Run 1 predicted | Passes (of reps) | Stable | Confidence (run 1) |
|---|---|---|---|---|---|
| frontend-settings-button | frontend | frontend | 3/3 | yes | high |
| frontend-form-validation | frontend | frontend | 3/3 | yes | high |
| backend-csv-export | backend | backend | 3/3 | yes | high |
| backend-rate-limit | backend | backend | 3/3 | yes | high |
| infra-oom-deploy | infra-devops | infra-devops | 3/3 | yes | high |
| infra-flaky-ci | infra-devops | infra-devops | 3/3 | yes | high |
| mobile-rotation-crash | mobile | mobile | 3/3 | yes | high |
| mobile-offline-sync | mobile | mobile | 3/3 | yes | high |
| data-ml-accuracy-regression | data-ml | data-ml | 3/3 | yes | high |
| data-ml-pipeline-idempotency | data-ml | data-ml | 3/3 | yes | high |
| cli-exit-code | cli | cli | 3/3 | yes | high |
| cli-config-precedence | cli | cli | 3/3 | yes | high |
| embedded-watchdog-ota | embedded | embedded | 3/3 | yes | high |
| embedded-i2c-hang | embedded | embedded | 3/3 | yes | high |
| game-particle-framedrop | game | game | 3/3 | yes | high |
| game-input-lag | game | game | 3/3 | yes | high |
| security-xss-profile | security | security | 3/3 | yes | high |
| security-ssrf-webhook | security | backend | 0/3 | yes | high |
| database-slow-orders-query | backend+database | backend | 0/3 | yes | high |
| database-migration-lock | database | database | 3/3 | yes | high |
| multi-export-endpoint-and-button | backend+frontend | backend+frontend | 3/3 | yes | high |
| multi-replica-and-migration | database+infra-devops | database+infra-devops | 3/3 | yes | high |
| fallback-cobol-jcl | fallback | mainframe | 3/3 | yes | high |
| fallback-solidity-contract | fallback | smart-contract | 3/3 | NO | high |
| fallback-fortran-sim | fallback | scientific-computing | 3/3 | yes | high |
