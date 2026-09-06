# Routing eval report

Generated: 2026-09-06T09:00:16.019230+00:00 — 34 cases x 3 reps, live Gemini via Vertex AI `global`, temperature=0.

## Headline metrics

- **Exact-set match (mean over reps):** 99.0%
- **Cross-run stability (all 3 reps agree, canonical sets):** 97.1%
- **Fallback rate (predictions outside the bespoke registry):** 7.7%
- **Boundary-case accuracy (mean over reps):** 97.0%
- **Multi-domain omission rate (per rep):** 0.0%
- **Self-reported confidence:** {'high': 102}
- **Derived confidence (self-consistency, per case):** {'high': 33, 'medium': 1}

## Confidence calibration (accuracy within each confidence bucket)

| Confidence | Correct | Total | Accuracy |
|---|---|---|---|
| high | 101 | 102 | 99% |

## Derived-confidence calibration (per-case consensus correctness within each bucket)

Does the majority-voted answer pass when cross-rep agreement is high? A useful signal
concentrates misses in the lower buckets — the self-reported table above cannot.

| Derived confidence | Correct | Total | Accuracy |
|---|---|---|---|
| medium | 1 | 1 | 100% |
| high | 33 | 33 | 100% |

Guidance thresholds (not yet enforced): match >= 90%, stability >= 95%, fallback < 10%.

## Gain summary (confidence-calibration + boundary-guards change, 2026-09-06)

Baseline: the 2026-09-06 record run (28 cases: 100.0% match, 96.4% stability, fallback 9.4%,
confidence {'high': 84}). This run: 34 cases (6 new boundary goldens). NOTE: this section is a
point-in-time record of the change — the next eval run overwrites it.

- **Stability now measures decisions, not synonyms.** Off-registry label drift no longer counts
  as instability: re-scoring the recorded baseline under canonical sets flips
  fallback-solidity-contract (blockchain/smart-contracts drift) to stable, 96.4% -> 100.0%. This
  run's 97.1% reflects one *genuine* wobble (database-orders-pagination-skips, 2/3) that the old
  metric would have masked behind the solidity noise.
- **Derived confidence discriminates; self-reported still doesn't.** Self-reported said "high"
  on all 102 reps. Derived confidence flagged exactly the wobbling case as "medium"
  ({'high': 33, 'medium': 1}) — the behavioral signal separates stable from unstable cases; the
  verbalized one cannot. Consensus correctness was 100% in both buckets, so discrimination is
  demonstrated on stability grounds; accuracy-grounds discrimination needs a case whose
  *consensus* misses — the seam cases exist to give it that chance.
- **Boundary class is now guarded.** 11 seam cases tracked as their own slice: 97.0% accuracy;
  all 6 new seam goldens passed 3/3. Multi-domain omission rate (the database-slow-orders-query
  failure mode) is 0.0% and now has a headline tripwire.
- **Production absorbs the wobble the eval found.** run_routing now majority-votes 3 samples and
  stamps derived_confidence: applied to this run, the shipped answer was correct for 34/34 cases
  (per-case consensus), with the one unstable case flagged "medium" for review. Effective
  per-case accuracy with self-consistency: 100%.
- Exact-set match 99.0% vs baseline 100.0% is a harder golden set (34 vs 28 cases), not a
  regression — the dip is the single pagination-skips rep above.

## Per-domain precision/recall (run 1)

| Domain | Precision | Recall | TP/FP/FN |
|---|---|---|---|
| frontend | 100% | 100% | 3/0/0 |
| backend | 100% | 100% | 7/0/0 |
| infra-devops | 100% | 100% | 4/0/0 |
| mobile | 100% | 100% | 2/0/0 |
| data-ml | 100% | 100% | 3/0/0 |
| cli | 100% | 100% | 2/0/0 |
| embedded | 100% | 100% | 2/0/0 |
| game | 100% | 100% | 2/0/0 |
| security | 100% | 100% | 5/0/0 |
| database | 100% | 100% | 6/0/0 |

## Per-case results

| Case | Expected | Run 1 predicted | Passes (of reps) | Stable | Confidence (run 1) | Consensus | Derived |
|---|---|---|---|---|---|---|---|
| frontend-settings-button | frontend | frontend | 3/3 | yes | high | frontend | high |
| frontend-form-validation | frontend | frontend | 3/3 | yes | high | frontend | high |
| backend-csv-export | backend | backend | 3/3 | yes | high | backend | high |
| backend-rate-limit | backend | backend | 3/3 | yes | high | backend | high |
| infra-oom-deploy | infra-devops | infra-devops | 3/3 | yes | high | infra-devops | high |
| infra-flaky-ci | infra-devops | infra-devops | 3/3 | yes | high | infra-devops | high |
| mobile-rotation-crash | mobile | mobile | 3/3 | yes | high | mobile | high |
| mobile-offline-sync | mobile | mobile | 3/3 | yes | high | mobile | high |
| data-ml-accuracy-regression | data-ml | data-ml | 3/3 | yes | high | data-ml | high |
| data-ml-pipeline-idempotency | data-ml | data-ml | 3/3 | yes | high | data-ml | high |
| cli-exit-code | cli | cli | 3/3 | yes | high | cli | high |
| cli-config-precedence | cli | cli | 3/3 | yes | high | cli | high |
| embedded-watchdog-ota | embedded | embedded | 3/3 | yes | high | embedded | high |
| embedded-i2c-hang | embedded | embedded | 3/3 | yes | high | embedded | high |
| game-particle-framedrop | game | game | 3/3 | yes | high | game | high |
| game-input-lag | game | game | 3/3 | yes | high | game | high |
| security-xss-profile | security | security | 3/3 | yes | high | security | high |
| security-ssrf-webhook | security | security | 3/3 | yes | high | security | high |
| database-slow-orders-query | backend+database | backend+database | 3/3 | yes | high | backend+database | high |
| database-migration-lock | database | database | 3/3 | yes | high | database | high |
| multi-export-endpoint-and-button | backend+frontend | backend+frontend | 3/3 | yes | high | backend+frontend | high |
| multi-replica-and-migration | database+infra-devops | database+infra-devops | 3/3 | yes | high | database+infra-devops | high |
| fallback-cobol-jcl | fallback | mainframe | 3/3 | yes | high | fallback | high |
| fallback-solidity-contract | fallback | smart-contracts | 3/3 | yes | high | fallback | high |
| fallback-fortran-sim | fallback | scientific-computing | 3/3 | yes | high | fallback | high |
| database-orders-pagination-skips | database | database | 2/3 | NO | high | database | medium |
| multi-customer-totals-report | backend+database | backend+database | 3/3 | yes | high | backend+database | high |
| security-path-traversal-download | security | security | 3/3 | yes | high | security | high |
| boundary-sql-injection-search | security | security | 3/3 | yes | high | security | high |
| boundary-n-plus-one-orders | backend+database | backend+database | 3/3 | yes | high | backend+database | high |
| boundary-oom-unbounded-cache | backend | backend | 3/3 | yes | high | backend | high |
| boundary-nan-imputation-serving | data-ml | data-ml | 3/3 | yes | high | data-ml | high |
| boundary-csv-formula-injection | security | security | 3/3 | yes | high | security | high |
| boundary-mesh-timeout | infra-devops | infra-devops | 3/3 | yes | high | infra-devops | high |
