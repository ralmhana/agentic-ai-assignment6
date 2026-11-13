# Assignment 6: predictions before implementation

Model: OpenAI gpt-4o, copied from Assignment 5. No experimental split has been
implemented or run when this prediction is written. These are hypotheses, not
measured results. This file is to be committed by itself on main and never revised.

## Proposed roles and dependencies

An investigator reads one issue, searches the repository, reads candidate files,
and returns a typed finding. It cannot write. A publisher receives one validated
finding and may apply its label, open its draft PR, and post its comment, in that
order. It cannot search or reinterpret the investigation. A deterministic
coordinator assigns work, meters it, validates returns, owns shared state, and
checks the final tracker state. All registry calls retain the existing policy.

For one issue, the publisher depends on the investigator's label, file and
evidence. The handoff duplicates context and adds validation and latency, while
the dependent work cannot overlap. For five unrelated issues, investigations can
run independently; the coordinator joins the findings and serializes writes.

## Four gates, in order

| Gate | One issue | Batch of five | Reason |
|---|---|---|---|
| 1. Parts work mostly without talking | fail | pass | A single issue's research and publication are dependent; investigations of unrelated issues are independent. |
| 2. Each result can be checked independently | not_reached | pass | Each return can be checked for schema, observed reads and issue ownership; each issue's final state has explicit invariants. This checks consistency, not semantic correctness. |
| 3. Team buys something one agent cannot get more cheaply | not_reached | pass | Hypothesis: overlapping independent model requests reduces batch latency relative to serial processing. A sequential split would not buy this benefit. |
| 4. Result is worth the multiplier | not_reached | fail | No measured accuracy or latency gain yet justifies extra context and coordination. Keep the single agent until evidence supports changing this gate. |

## Falsifiable expectations

- Single issues: M will have similar accuracy and greater coordination cost than S.
  S-plus should match or exceed M's accuracy at similar actual spend. Prefer single.
- Batches: M may reduce wall-clock time by overlapping investigations, but a task
  passes only if all five issues pass. The split is not guaranteed to improve this
  stricter score. Context isolation may reduce cross-issue mistakes.
- Predict M/S token multipliers of roughly 1.2-2.0 for single issues and 0.7-1.5
  for batches, well below the lecture's illustrative 15x. Smaller batch contexts
  might offset duplicated prompts; these intervals are predictions, not targets.
- Compare S, M and S-plus on all eight fixed tasks, three sweeps each. S and M get
  250,000 tokens per issue. S-plus uses --match split after M finishes. Record
  actual spend task by task; a budget match alone is not evidence of a spend match.
- Keep model, registry definitions, evaluator, task set, reviewer and ceilings
  fixed. Never expose task answers to the agents. Scripted runs test plumbing only.
- Reconsider a batch split only with comparable or better all-five accuracy,
  a material wall-clock improvement (at least 25%), and M's token multiplier no
  greater than 1.5, confirmed on a larger held-out set if this small study suggests it.

## AI assistance

Codex drafted this pre-experiment analysis from the starter README, report
template and checks/FORMATS.md section 14. The independent instructor handout
has not been located; no claim is made to have read it. Predictions were not fitted
to experimental results.
