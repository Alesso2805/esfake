# ADR-0006: Non-inferiority margin against the LLM-only baseline, and the per-PR regression gate

- Status: Accepted (2026-10-07)
- Date: 2026-10-06, fixed before any measurement on `test`
- Deciders: Alessandro David
- Related: `docs/SPEC.md` (Métricas de éxito, Requisitos de calidad), `CLAUDE.md` rule 11, EF-08, EF-10, EF-15, EF-22, EF-30

## Context

The public claim of the project is that the layered pipeline (ADR-0001) is not meaningfully worse than a zero-shot LLM-only classifier at catching scams, while being cheaper and faster. It also adds what the LLM alone does not give: a modality, a concrete action, cost control and floors against manipulation.

The `test` split holds about 90 messages (15 % of at least 600), roughly half of them scams, so about 45 positives. At 90 % recall, a Wilson 95 % interval on 45 cases is about ±9 points. With a handful of discordant cases, the paired difference between two systems has a 95 % interval of roughly ±7 to ±11 points even when both are equally good. This test cannot show superiority or tight equivalence.

A margin chosen after looking at results would be worthless, so it is fixed here first.

The pipeline also needs a per-PR gate that catches clear regressions on `eval` without calling the model in CI.

## Decision A: Non-inferiority against the LLM-only baseline

- **Population.** The scam cases in `test`, at release time (EF-30). Both systems are scored on exactly the same cases.
- **Outcome.** Detected = `likely_scam` or `suspicious`.
- **Statistic.** Δ = recall(pipeline) − recall(LLM-only), in percentage points.
- **Interval.** A paired bootstrap percentile interval at 95 %:
  - Resample scam cases with replacement, keeping both systems' predictions for each case together.
  - Use 10 000 resamples with a fixed seed, recorded in the evaluation file.
- **Criterion.** The pipeline is non-inferior if the lower bound of the interval is greater than **−10 points**. This is equivalent to a one-sided test at 2.5 %.
- **Model runs.** The primary analysis uses the recorded model responses committed for the release. The live evaluation (N = 3) is reported to show model variance; the claim is stated only if the primary analysis meets it.
- **What we publish (EF-22, EF-30):**
  - Δ and its interval.
  - The discordant cases: which scams each system missed.
  - The difference in false positives with its interval, which is reported but not part of the criterion.
  - Mean cost per verification and p95 latency for both systems. The cost and latency claim requires the pipeline to be lower on both.
  - The other two baselines (keywords, embeddings with logistic regression), side by side.

### Why −10 points

- **A tighter margin is unattainable.** With about 45 positives, the interval of a paired difference is roughly ±7 to ±11 points even when the systems are equal. A tighter margin would make the claim fail because of sampling noise.
- **A wider margin is unacceptable.** It would let us call "non-inferior" a pipeline that misses more than 1 extra scam in 10, which goes against the priority of not under-alarming.
- **If the interval still crosses −10,** we publish the result as "inconclusive at this sample size", not as non-inferior.
- **Changes need a new ADR, made before measuring.** A larger `test` set in a later version could justify a tighter margin, but only through a new ADR dated before that measurement. Any change after the first measurement on `test` is published as a deviation.

## Decision B: Per-PR regression gate on `eval`

- **Baseline.** The per-case predictions stored for the latest published version, in `docs/evals/<version>.json` (case_id, level, route). Old code is never run again.
- **Cases compared.** Only the case_ids present in both datasets. New cases count from the next published version.
- **Mode.** `cached-strict`: a missing model response fails with "run make eval-record". In record mode, responses recorded live during that run are left out of the comparison.
- **Outcomes, paired by case:**
  - On scam cases: detected or not.
  - On legitimate cases: a false positive (any level other than `no_signals`) or not.
- **Test.** Exact McNemar, one-sided, α = 0.05, on the discordant cases of each outcome.
- **The gate fails if either holds:**
  1. Recall regresses significantly.
  2. False positives rise significantly **and** recall does not improve significantly. The improvement is tested the same way, one-sided, α = 0.05.

  Reason for rule 2: the product prefers over-alarming to under-alarming, so a rise in false positives is acceptable only when it buys a significant recall gain. This also lets the first real rules (EF-11) pass against version 0. Version 0 is policy v0 published by EF-08 before any rule exists, so it outputs almost only `no_signals`: no false positives and near-zero recall.
- **Absolute floors.** Recall ≥ 85 % and false positives ≤ 8 % on `eval`, enforced only when `absolute_floors_enabled` is on. That flag turns on with the first version published after EF-15. These floors cap the false-positive drift that rule 2 allows.
- **Before version 0.** The gate passes with a warning.
- **Report.** Every run prints the discordant cases and the false-positive counts per hard-negative subcategory.

## Alternatives considered

- **Superiority test against the LLM alone.** Underpowered at this size, and not the claim we need.
- **Equivalence with a symmetric margin.** Penalises the pipeline for being better, and is just as underpowered.
- **Absolute thresholds per PR instead of a paired comparison.** Noisy at this size, and blind to which cases changed.
- **Gate on accuracy only.** It hides a fall in recall behind a fall in false positives, which is the trade we least want.
- **Gate on recall only.** It lets false positives grow without limit until the floors turn on after EF-15.

## Consequences

- The non-inferiority claim is pre-registered and narrow: "not worse by more than 10 points of recall", stated with its interval.
- A true difference of a few points cannot be detected with this test set. The README must say so.
- The gate catches only clear regressions, because exact McNemar on few discordant cases has little power. Release-time evaluation on `test` and the absolute floors complement it.
- Rule 2 allows false positives to grow while recall grows. That growth is visible in every report and is capped by the floors after EF-15.
