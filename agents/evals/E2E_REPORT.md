# End-to-end Gate 2 eval report (SWE-bench-mini)

Generated: 2026-09-05T20:45:30.866425+00:00 — 11 scenario runs (11 fixtures x 1 reps), live Gemini for every agent, real coding agent on local fixture repos, externals faked.

## Headline metrics

- **Verified-correct rate (PR opened AND held-out oracle passes):** 100.0%
- **False-green rate (PR opened but oracle REJECTS the fix):** 0.0%
- **Escalation rate (pipeline gave up):** 0.0%
- **Routing exact-match:** 100.0%
- **Verification-vs-oracle agreement (model-judged attempts):** 100.0%
- **Mean attempts per scenario:** 1.2

## Per-scenario results

| Scenario | Routing | Attempts | Terminal | Oracle (final) | Outcome |
|---|---|---|---|---|---|
| backend-invoice-discount | ✓ | 1 | pr_open | pass | verified-correct |
| cli-exit-code | ✓ | 1 | pr_open | pass | verified-correct |
| data-ml-pipeline-idempotent | ✓ | 1 | pr_open | pass | verified-correct |
| database-orders-pagination | ✓ | 1 | pr_open | pass | verified-correct |
| frontend-cart-total | ✓ | 1 | pr_open | pass | verified-correct |
| game-fixed-timestep | ✓ | 1 | pr_open | pass | verified-correct |
| multi-orders-report | ✓ | 1 | pr_open | pass | verified-correct |
| security-path-traversal | ✓ | 1 | pr_open | pass | verified-correct |
| security-two-queries-same-injection | ✓ | 1 | pr_open | pass | verified-correct |
| backend-two-endpoints-same-validation | ✓ | 2 | pr_open | pass | verified-correct |
| security-xss-two-sinks | ✓ | 2 | pr_open | pass | verified-correct |
