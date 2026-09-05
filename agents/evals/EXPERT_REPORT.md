# Domain-expert eval report

Generated: 2026-09-05T15:45:18.204018+00:00 — 20 cases x 2 reps, live Gemini, domain pinned correct by goldens (routing measured separately).

## Headline metrics (hard)

- **Relevant-files recall (mean over reps):** 50.0%
- **Relevant-files precision (mean over reps):** 18%
- **Hallucinated paths:** 149 across 208 predicted paths (72%)

## Judge-scored summary quality (SOFT — reference-based LLM judge, not a headline)

- root_cause_identified: 100.0%
- correct_area: 100.0%
- actionable: 100.0%

Guidance thresholds (not yet enforced): recall >= 80%, hallucination rate < 5%.

## Per-domain (run 1)

| Domain | Recall | Precision | Hallucinated |
|---|---|---|---|
| backend | 50% | 7% | 10 |
| cli | 100% | 45% | 3 |
| data-ml | 50% | 12% | 8 |
| database | 75% | 21% | 7 |
| embedded | 25% | 7% | 10 |
| frontend | 25% | 12% | 6 |
| game | 0% | 0% | 9 |
| infra-devops | 100% | 45% | 1 |
| mobile | 25% | 20% | 9 |
| security | 0% | 0% | 10 |

## Per-case results

| Case | Domain | Recall (reps) | Precision (reps) | Hallucinated | Judge (reps) |
|---|---|---|---|---|---|
| frontend-settings-button | frontend | 0%/0% | 0%/0% | 9 | 3/3/3/3 |
| frontend-form-validation | frontend | 50%/50% | 25%/20% | 5 | 3/3/3/3 |
| backend-csv-export | backend | 0%/100% | 0%/17% | 9 | 3/3/3/3 |
| backend-rate-limit | backend | 100%/100% | 14%/17% | 9 | 3/3/3/3 |
| infra-oom-deploy | infra-devops | 100%/100% | 40%/20% | 4 | 3/3/3/3 |
| infra-flaky-ci | infra-devops | 100%/100% | 50%/50% | 1 | 3/3/3/3 |
| mobile-rotation-crash | mobile | 50%/100% | 40%/25% | 6 | 3/3/3/3 |
| mobile-offline-sync | mobile | 0%/0% | 0%/0% | 11 | 3/3/3/3 |
| data-ml-accuracy-regression | data-ml | 0%/0% | 0%/0% | 10 | 3/3/3/3 |
| data-ml-pipeline-idempotency | data-ml | 100%/100% | 25%/40% | 5 | 3/3/3/3 |
| cli-exit-code | cli | 100%/100% | 40%/50% | 4 | 3/3/3/3 |
| cli-config-precedence | cli | 100%/100% | 50%/60% | 2 | 3/3/3/3 |
| embedded-watchdog-ota | embedded | 50%/50% | 14%/17% | 11 | 3/3/3/3 |
| embedded-i2c-hang | embedded | 0%/0% | 0%/0% | 8 | 3/3/3/3 |
| game-particle-framedrop | game | 0%/0% | 0%/0% | 10 | 3/3/3/3 |
| game-input-lag | game | 0%/0% | 0%/0% | 11 | 3/3/3/3 |
| security-xss-profile | security | 0%/0% | 0%/0% | 11 | 3/3/3/3 |
| security-ssrf-webhook | security | 0%/0% | 0%/0% | 11 | 3/3/3/3 |
| database-slow-orders-query | database | 50%/100% | 17%/50% | 8 | 3/3/3/3 |
| database-migration-lock | database | 100%/100% | 25%/25% | 4 | 3/3/3/3 |
