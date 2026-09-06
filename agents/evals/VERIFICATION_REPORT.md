# Verification eval report

Generated: 2026-09-05T20:35:12.445662+00:00 — 14 model-judged scenarios + 2 deterministic short-circuit scenarios x 2 reps, live Gemini.

## Headline metrics

- **Verdict agreement with oracle (model-judged):** 100.0%
- **Per-criterion status agreement (labeled subset):** 100.0%
- **Feedback present on red verdicts:** 100.0%
- **Deterministic short-circuit correct:** yes

#17 hard-gating is ON (wave 1.7): gate2 treats any not_met criterion as red. It was unlocked when criteria agreement reached 100% — the 95% reliability bar the report-first rollout waited on. If a future change drops agreement below 95%, consider reverting gate2's override to report-first.

## Per-scenario results

| Scenario | Expected | Verdict correct (reps) | Criteria hits | Feedback on red |
|---|---|---|---|---|
| clear-pass-backend | green | ✓/✓ | 4/4 | n/a |
| tests-failed-shortcircuit | red (short-circuit) | ✓/✓ | — | ✓/✓ |
| tests-failed-shortcircuit-security | red (short-circuit) | ✓/✓ | — | ✓/✓ |
| plan-match-misses-issue | red | ✓/✓ | — | ✓/✓ |
| partial-implementation | red | ✓/✓ | — | ✓/✓ |
| test-weakening | red | ✓/✓ | — | ✓/✓ |
| security-missing-auth | red | ✓/✓ | 2/2 | ✓/✓ |
| criteria-not-applicable-frontend | green | ✓/✓ | 2/2 | n/a |
| doc-only-diff | red | ✓/✓ | — | ✓/✓ |
| criteria-met-backend | green | ✓/✓ | 4/4 | n/a |
| database-unsafe-migration | red | ✓/✓ | 2/2 | ✓/✓ |
| cli-exit-code-fixed | green | ✓/✓ | 2/2 | n/a |
| dataml-train-serve-skew | red | ✓/✓ | 2/2 | ✓/✓ |
| unrelated-changes | red | ✓/✓ | — | ✓/✓ |
| scope-creep-but-correct | green | ✓/✓ | — | n/a |
| partial-issue-coverage | red | ✓/✓ | — | ✓/✓ |
