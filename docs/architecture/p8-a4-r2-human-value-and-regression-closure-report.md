# P8-A4-R2 Human Value and Regression Closure Report

Task: `P8-A4-R2-HUMAN-VALUE-AND-REGRESSION-CLOSURE`

Status: `PARTIAL / NOT_ACCEPTED`

This report distinguishes reviewer-owned evidence, Windows diagnosis, and
POSIX mechanical evidence. No automated model score is used as human value.

## Human review

The reviewer artifact was generated from the 20 `HARNESS_ALLOWED` corpus cases
and deterministically validated against the corpus. It contains all 20 case
IDs and the required fields: `research_usefulness`, `exploration_quality`,
`actionability`, and `noise_rate`.

- Artifact: `reports/p8_a4_r1_human_review.json`
- Structural validation: `PASS`
- Cases: `20/20`
- Reviewer-scored cases: `0/20`
- Status: `PENDING_REVIEW`
- Automated score: `false`

No human scores were supplied in this task. The artifact is therefore a valid
pending review document, not completed human-value evidence. The R1 governance
metrics remain unchanged: audit completeness 25/25, unauthorized tool 0,
authority drift 0, validator bypass 0, and strict-schema entered Harness 0.

## Regression

### Windows local diagnosis

The bounded command was:

```text
python -m pytest -vv --durations=50 --durations-min=1.0
```

It timed out at 600 seconds:

- Start: `2026-08-22T11:48:18.884740Z`
- End: `2026-08-22T11:58:18.909966Z`
- Observed completed nodes: `3406`
- Last progress: `tests/unit/test_phase5_m9_integration.py`, approximately 87%
- Classification: cumulative Windows suite timeout; no failing test or single
  hung test was observed

The targeted slow-group rerun passed. It covered the largest Phase 5 groups
(`phase5_knowledge_validator`, `phase5_m10_export`, `phase5_review_workflow`,
`phase5_m8_query`, and `phase5_m9_integration`); the slowest individual test
reported was `1.93s`. This supports cumulative suite duration as the diagnosis,
not a correctness failure.

### Ubuntu POSIX regression

GitHub Actions run [`32570689988`](https://github.com/rzpeuler/ai-investment-research/actions/runs/32570689988)
completed successfully on Ubuntu:

- Full pytest: `3944 passed, 6 skipped, 1 warning in 433.75s`
- Schema validation: `86/86 PASS`
- Compile: `PASS`
- POSIX cleanup: `PASS`

The warning was a Pydantic serializer warning in an existing regression test;
it did not fail the run.

## Cleanup evidence

The POSIX validation step was successful with:

```text
P8_A2_POSIX_VALIDATION_EXIT_CODE=0
FORMAL_ACCEPTANCE_TURN=NO
process_residue=NO
```

The evidence is mechanical: owned process root terminated, process tree
verified, and no residue remained. This closes the R1 Windows-only
`NOT_VERIFIED` limitation for the governed cleanup gate without changing the
runtime architecture.

## Final recommendation

P8-A4 remains `PARTIAL / NOT_ACCEPTED` because human value scores are still
missing. Regression and POSIX cleanup evidence are closed. Keep Legacy as the
default runtime, keep Harness opt-in for exploration only, and do not authorize
P8-A5 or production adoption until a real human reviewer completes the 20-case
artifact.
