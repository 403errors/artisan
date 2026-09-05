# Domain-expert eval report

Generated: 2026-09-05T18:00:29.823706+00:00 — 20 cases x 2 reps, live Gemini, domain pinned correct by goldens (routing measured separately).

## Headline metrics (hard)

- **Relevant-files recall (mean over reps):** 100.0%
- **Relevant-files precision (mean over reps):** 40%
- **Hallucinated paths:** 0 across 168 predicted paths (0%)

## Judge-scored summary quality (SOFT — reference-based LLM judge, not a headline)

- root_cause_identified: 100.0%
- correct_area: 100.0%
- actionable: 100.0%

Guidance thresholds (not yet enforced): recall >= 80%, hallucination rate < 5%.

## Per-domain (run 1)

| Domain | Recall | Precision | Hallucinated |
|---|---|---|---|
| backend | 100% | 22% | 0 |
| cli | 100% | 53% | 0 |
| data-ml | 100% | 37% | 0 |
| database | 100% | 46% | 0 |
| embedded | 100% | 37% | 0 |
| frontend | 100% | 45% | 0 |
| game | 100% | 45% | 0 |
| infra-devops | 100% | 29% | 0 |
| mobile | 100% | 35% | 0 |
| security | 100% | 45% | 0 |

## Per-case results

| Case | Domain | Recall (reps) | Precision (reps) | Hallucinated | Judge (reps) |
|---|---|---|---|---|---|
| frontend-settings-button | frontend | 100%/100% | 40%/40% | 0 | 3/3/3/3 |
| frontend-form-validation | frontend | 100%/100% | 50%/50% | 0 | 3/3/3/3 |
| backend-csv-export | backend | 100%/100% | 25%/25% | 0 | 3/3/3/3 |
| backend-rate-limit | backend | 100%/100% | 20%/33% | 0 | 3/3/3/3 |
| infra-oom-deploy | infra-devops | 100%/100% | 25%/33% | 0 | 3/3/3/3 |
| infra-flaky-ci | infra-devops | 100%/100% | 33%/33% | 0 | 3/3/3/3 |
| mobile-rotation-crash | mobile | 100%/100% | 50%/50% | 0 | 3/3/3/3 |
| mobile-offline-sync | mobile | 100%/100% | 20%/20% | 0 | 3/3/3/3 |
| data-ml-accuracy-regression | data-ml | 100%/100% | 40%/40% | 0 | 3/3/3/3 |
| data-ml-pipeline-idempotency | data-ml | 100%/100% | 33%/33% | 0 | 3/3/3/3 |
| cli-exit-code | cli | 100%/100% | 67%/67% | 0 | 3/3/3/3 |
| cli-config-precedence | cli | 100%/100% | 40%/40% | 0 | 3/3/3/3 |
| embedded-watchdog-ota | embedded | 100%/100% | 33%/33% | 0 | 3/3/3/3 |
| embedded-i2c-hang | embedded | 100%/100% | 40%/40% | 0 | 3/3/3/3 |
| game-particle-framedrop | game | 100%/100% | 50%/50% | 0 | 3/3/3/3 |
| game-input-lag | game | 100%/100% | 40%/40% | 0 | 3/3/3/3 |
| security-xss-profile | security | 100%/100% | 40%/50% | 0 | 3/3/3/3 |
| security-ssrf-webhook | security | 100%/100% | 50%/50% | 0 | 3/3/3/3 |
| database-slow-orders-query | database | 100%/100% | 67%/67% | 0 | 3/3/3/3 |
| database-migration-lock | database | 100%/100% | 25%/25% | 0 | 3/3/3/3 |
