# Artisan pipeline quality report

Generated: 2026-09-05T18:25:33.271037+00:00 — aggregated from the eval harnesses' JSON sidecars (agents/evals/). All stages run live Gemini against golden datasets or seeded-bug fixture repos; nothing here is self-reported by the pipeline.

## The funnel

| Stage | Metric | Value | Details |
|---|---|---|---|
| Routing | Exact-set domain match | 100.0% | 25 cases x 3 reps; stability 96.0%; fallback 10.7% |
| Routing | Confidence calibration (accuracy per level) | — | high: 100.0% (75/75) |
| Domain expert | Relevant-files recall | 100.0% | precision 40.2%; hallucination rate 0.0% |
| Domain expert | Summary quality (SOFT, LLM judge) | — | root_cause_identified 100.0%; correct_area 100.0%; actionable 100.0% |
| Verification | Verdict agreement with oracle | 100.0% | criteria agreement 88.9%; feedback-on-red 100.0% |
| **End-to-end** | **Verified-correct rate** | **100.0%** | false-green 0.0%; escalations 0.0%; mean attempts 1.1 |

## How to read this

- **Routing** answers: did the right specialist get the ticket? (exact-set match on a 25-case golden dataset, plus confidence calibration — a calibrated router is right more often when it says "high".)
- **Domain expert** answers: given the right specialist, did it identify the right files and root cause? (file recall/precision are hard metrics; summary quality is judge-scored and deliberately not a headline.)
- **Verification** answers: does the gate agree with a known-correct oracle? (This is the number #17's criteria hard-gating decision waits on.)
- **End-to-end** answers: on seeded real bugs, how often does the pipeline ship a fix that passes tests it never saw? And how often does it ship a wrong fix believing it's right (false green) — the number verification exists to keep at zero.

Stage reports: REPORT.md (routing), EXPERT_REPORT.md, VERIFICATION_REPORT.md, E2E_REPORT.md.
