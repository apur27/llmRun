# ConvFinQA Report

*The headers here are guidelines, you can structure your report however you like.*

## Running it

Three paths, in the order a reviewer with no key would want them.

**1. No key — a real conversation, replayed:**

```bash
uv run main chat "Single_SLG/2013/page_133.pdf-4" --client fixture
```

No key, no network. This demonstrates the real questions, the real recorded answers (4 real
values from an earlier real Anthropic call this project made), and the real `chat`/`TurnState`
loop (`chat` calls `turn_state.add()` after every answer regardless of client) — but
**`FixtureClient` is a flat `(record, turn_index)` lookup that ignores `turn_state` on replay
(see its own docstring), so tool routing and the parse-repair path are not exercised by this
demo**, only by the live `--client anthropic` path. What you're seeing is genuine recorded model
output, displayed through the real interface, not a live call and not staged data.

**2. No key — the real pipeline, a known-wrong predictor:**

```bash
uv run main eval --client stub
```

Runs the complete pipeline end to end against the real dataset — loader, program executor,
scorer, denominator — with a predictor that is guaranteed wrong on every turn by construction.
Prints strict/tolerant accuracy (both `0.0`, by design) with their denominator. This is the
harness proving itself, not a demo: `make eval-falsify` runs the same check as part of the gate.
No network call is made.

**3. With a key — a live conversation:**

```bash
uv run main chat <record_id>
```

Walks one record's own questions against the real Anthropic client, one turn at a time (enter to
continue, `exit` to stop). Without a key this fails clean — one line naming the missing variable,
exit 1, no traceback — rather than doing nothing silently or crashing.

To see accuracy on a real sample rather than a single conversation:

```bash
uv run main eval --client anthropic --split train --limit <N>
```

`--limit` is required (real spend is never sized implicitly). `--split dev` additionally requires
`--confirm-dev-run`, since `dev` is measured once, at the end of the engagement, and cannot be
un-spent — see Method for why.

The full gate (`make check`) requires no key and no network.

## Method

The metric was designed and frozen before any model call was made — derived entirely from dev's
own `executed_answers` and `turn_program` fields, zero API spend, zero model in the loop. Four
decisions below, each with what was chosen, what the alternatives were, what the data said, and
what the choice costs.

**The tolerance epsilon is 1e-3 relative error, and the number was measured, not picked by
convention.** Recomputing every one of dev's 1486 numeric turns' `turn_program` with an executor
independently proven correct (it reproduces gold on 1490/1490 turns under this same tolerance,
the harness's own falsification-proof) and sweeping the comparison tolerance gives:

| relative epsilon | turns matching gold (of 1486) |
|---|---|
| 0 (exact `==`) | 945 |
| 1e-6 | 1166 |
| 1e-5 | 1317 |
| 1e-4 | 1455 |
| 1e-3 | 1486 (full agreement) |
| 1e-2 | 1486 (unchanged) |

1e-5 was rejected because agreement is still incomplete there: 1317 of 1486 (88.6%), meaning a
tolerance that tight would score 169 turns *wrong* even though a from-scratch executor already
proven correct reproduces gold under a slightly looser comparison — those 169 failures are gold's
own storage precision leaking into the metric, not the executor being wrong. 1e-2 was rejected for
the opposite reason: it accepts exactly zero turns beyond what 1e-3 already accepts — a
ten-times-looser tolerance that changes nothing is not a real choice, it's slack that only makes
the metric look more forgiving than it needs to be. Between those two rejections, the true minimum
epsilon for full agreement — the largest relative error dev's own gold values actually exhibit
against an independently-correct executor — is ~7.4e-4. 1e-3 sits at **1.34x that floor**: a
deliberate margin, close enough to the empirical floor that it's clearly forgiving storage noise
and nothing else, loose enough that it isn't brittle to the next turn that happens to land at
7.41e-4. That margin, not the round number itself, is the actual decision.

**Exact match caps a perfect system at 63.6%, which is why a tolerance is a correction, not
leniency.** Comparing the same recomputed `turn_program` results to `executed_answers` with exact
float equality succeeds on only 945 of 1486 turns (63.6%) — using an executor with no known
errors on this data. A hypothetically perfect answering system, one that derives the
mathematically correct value on every single turn, would still score 63.6% under strict match, not
because it reasoned incorrectly but because gold itself is stored at rounded, inconsistent
precision: 354 of 1486 values (23.8%) need five or more decimal places to represent exactly, so it
isn't even a uniform two-decimal rounding rule that could be special-cased away. Reporting only
exact match would make an unreachable ceiling read as a system failure. This is why the frozen
METRIC reports strict and tolerant side by side rather than picking one — strict stays as the
number a reader can audit against raw storage precision, and tolerant is the number that actually
measures the system rather than the dataset's own recording precision.

**Scale-flip — a predicted value equal to `gold × 100` or `gold ÷ 100`, the ratio-vs-percentage
confusion `divide` invites — was decided strict and distinct: never coerced into a correct answer,
only flagged as a diagnostic.** The alternative was costed, not dismissed by assumption. In the
percentage-convention experiment (N=120 turns, top-level `divide`, `abs(gold) ∈ (0,1]`), 19 of 120
turns (15.8%) under the baseline system prompt were scale-flip. Had both forms been accepted as
correct instead, tolerant accuracy on that filtered sample would have roughly tripled — from 10/120
(8.3%) to 29/120 (24.2%) — without the system doing anything differently. That is what accepting
both forms would have bought: a systematic model bias absorbed into the headline instead of left
visible as an error to fix. And it *is* fixable — a one-line system-prompt change (variant B)
nearly halved the rate on its own, 19/120 to 11/120, a change that would never have been made if
scale-flip had simply been scored correct from the start. Refusing to auto-correct is what made
that fix findable.

The decision costs exposure, and it is stated here rather than left for a reader to work out: 352
of 1486 dev turns (23.7%) — every turn where the top-level operation is `divide` and gold falls in
`(0,1]`, the exact condition under which the confusion is possible — have their correctness riding
entirely on the model getting ratio-vs-percentage framing right, invisible in the headline number
unless the `scale_flip` flag is inspected specifically. 352, not the raw 411-turn `abs(gold) ∈
(0,1]` magnitude bucket, because 59 of those 411 turns have a non-`divide` top-level operation
where the ambiguity cannot occur at all — counting them would overstate the exposure.

**Train and dev split by design, not by convention: iterate on train, report dev exactly once.**
The dataset ships train (3037 records) and dev (421 records) with no third, held-out test split.
The reflex under that constraint is to carve dev in half — an iteration set and a reported set,
both drawn from the same 421 — and that was rejected. Train carries the same fields and the same
gold answers as dev, at seven times the volume, and whether it was safe to iterate on was checked,
not assumed: stripping each document id's `Single_`/`Double_` prefix and `.pdf` suffix and
comparing the two splits' underlying source documents (1588 in train, 218 in dev) found **zero
overlap** — no train document is a dev document under a different question. That fact licenses the
design: prompt iteration, the percentage-convention experiment, the arm-B diagnosis, and the first
real accuracy sample all ran against train, and none of it can have leaked into what dev reports,
because there is nothing shared to leak through. Dev itself is measured exactly once, at the end
of the engagement, behind an explicit `--confirm-dev-run` flag the CLI enforces — the split that
cannot be re-measured once spent is treated as exactly that.
## Error Analysis
Lorem ipsum dolor sit amet consectetur adipiscing elit
## Future Work 
Lorem ipsum dolor sit amet consectetur adipiscing elit
## [may not apply] If & how you've used coding assistants or gen AI tools to help with this assignment 
Please be honest.

Lorem ipsum dolor sit amet consectetur adipiscing elit
