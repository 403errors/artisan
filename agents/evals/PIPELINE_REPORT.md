# Artisan pipeline quality report

Generated: 2026-09-05T20:45:56.708136+00:00 — aggregated from the eval harnesses' JSON sidecars (agents/evals/). All stages run live Gemini against golden datasets or seeded-bug fixture repos; nothing here is self-reported by the pipeline.

## The funnel

| Stage | Metric | Value | Details |
|---|---|---|---|
| Routing | Exact-set domain match | 100.0% | 28 cases x 3 reps; stability 96.4%; fallback 9.4% |
| Routing | Confidence calibration (accuracy per level) | — | high: 100.0% (84/84) |
| Domain expert | Files-to-modify recall | 93.8% | precision 60.4%; hallucination rate 0.0%; union-recall guard 100.0% |
| Domain expert | Summary quality (SOFT, LLM judge) | — | root_cause_identified 100.0%; correct_area 100.0%; actionable 100.0% |
| Verification | Verdict agreement with oracle | 100.0% | criteria agreement 100.0%; feedback-on-red 100.0% |
| **End-to-end** | **Verified-correct rate** | **100.0%** | false-green 0.0%; escalations 0.0%; mean attempts 1.2 |

## How to read this

- **Routing** answers: did the right specialist get the ticket? (exact-set match on a golden dataset, plus confidence calibration — a calibrated router is right more often when it says "high".)
- **Domain expert** answers: given the right specialist, did it identify the right files and root cause? (file recall/precision are hard metrics scored on the files-to-modify list, with union-of-both-lists recall as the anti-gaming guard; summary quality is judge-scored and deliberately not a headline.)
- **Verification** answers: does the gate agree with a known-correct oracle? (Criteria agreement is what #17's hard-gating was gated on — flipped ON in wave 1.7 at 100%.)
- **End-to-end** answers: on seeded real bugs, how often does the pipeline ship a fix that passes tests it never saw? And how often does it ship a wrong fix believing it's right (false green) — the number verification exists to keep at zero.

Stage reports: REPORT.md (routing), EXPERT_REPORT.md, VERIFICATION_REPORT.md, E2E_REPORT.md.
