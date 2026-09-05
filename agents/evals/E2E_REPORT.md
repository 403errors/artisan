# End-to-end Gate 2 eval report (SWE-bench-mini)

Generated: 2026-09-05T16:24:06.442795+00:00 — 8 scenario runs (8 fixtures x 1 reps), live Gemini for every agent, real coding agent on local fixture repos, externals faked.

## Headline metrics

- **Verified-correct rate (PR opened AND held-out oracle passes):** 87.5%
- **False-green rate (PR opened but oracle REJECTS the fix):** 12.5%
- **Escalation rate (pipeline gave up):** 0.0%
- **Routing exact-match:** 62.5%
- **Verification-vs-oracle agreement (model-judged attempts):** 87.5%
- **Mean attempts per scenario:** 1.0

## Per-scenario results

| Scenario | Routing | Attempts | Terminal | Oracle (final) | Outcome |
|---|---|---|---|---|---|
| backend-invoice-discount | ✓ | 1 | pr_open | pass | verified-correct |
| cli-exit-code | ✓ | 1 | pr_open | pass | verified-correct |
| data-ml-pipeline-idempotent | ✓ | 1 | pr_open | pass | verified-correct |
| database-orders-pagination | ✗ (backend) | 1 | pr_open | pass | verified-correct |
| frontend-cart-total | ✓ | 1 | pr_open | pass | verified-correct |
| game-fixed-timestep | ✓ | 1 | pr_open | pass | verified-correct |
| multi-orders-report | ✗ (backend) | 1 | pr_open | pass | verified-correct |
| security-path-traversal | ✗ (backend) | 1 | pr_open | FAIL | FALSE GREEN |
