# PROCESS.md

The engineering ledger has **one row for each slice of work**. Before starting a slice, I wrote down its goal, gave it its own check, and reran the full quality gate before committing it.

I built the project with **Claude Code** and my own tooling for managing coding agents against a deadline. That tooling includes:

* a hook that blocks specific dangerous commands
* a work ledger
* a checkpoint after each small increment

The tooling lives in a separate private repository and is not part of this submission.

This file comes directly from two records:

* `slices.jsonl`, which records planned vs. actual work with timestamps
* `plan.md`, which records decisions as they were made

Nothing here is based on memory. If information was missing, I say so.

### Timings

Early in the project, I found that a subagent's reported start and finish times were unreliable, including **two fabricated entries**.

Those entries are marked:

```text
estimated: true
```

and are excluded from the timing figures.

Later timings came from my own clock.

Slices **0, 1 and 2** are marked as estimated because their times were reconstructed afterwards.

Slice **14** also had an impossible finish time. I corrected it using the tool call's reported duration. That is more reliable, but it is still not a live timestamp.

### Reverted slice

Slice:

```text
n=3
```

was stopped before any file was written because of the timing issue above.

It is still listed as **reverted**, rather than being removed.

The same work was redone cleanly as:

```text
n=4
```

### Skipped slice

Slice:

```text
n=35
```

was deliberately not built.

It would only have added a nice-to-have header to the evaluation summary. I dropped it because the same information was already visible through:

```text
--split
```

and through the denominators in the report.

It is still listed in the ledger, together with the reason it was skipped.

## Session 1: building the accuracy measurement system, slices 0 to 12

The goal was **zero model spend**, so I could define and freeze the scoring metric before seeing any model results.

There was one small exception.

Slice **12** spent less than:

```text
$0.05
```

on:

```text
3 real conversations
```

This was done early to test one design question before continuing.


| n | type | intent | decision | planned | actual |
|---|---|---|---|---|---|
| 0 | scaffold | Gate: ruff `--no-fix`, mypy, pytest+cov+randomly, `Makefile` `check`. | none — followed the brief's gate as given | 15 | 3* |
| 1 | measurement | Freeze tolerance + scale-flip rule from dev gold, no model call. | 0.1% tolerance — the point matching gold goes from partial (945/1486) to complete. | 12 | 8* |
| 2 | measurement | Check the tolerance choice with a sweep across several values. | Real floor ≈0.074%; 0.1% sits just above with a small margin; 1% adds nothing. | 8 | 3* |
| 3 | feature | Domain models + loader (attempt). | none — reverted before any code existed | 14 | not recorded |
| 4 | feature | Domain models + loader, redo of n=3. | none — schema follows `dataset.md`; counts/overlap asserted as a test | 14 | 3 |
| 5 | feature | Executor: six ops + within-turn refs + constants. | none — implements the already-inventoried six-op vocabulary | 17 | 3 |
| 6 | measurement | 1490-point gold replay vs. `executed_answers`. | none — validates n=1's tolerance and n=5's executor | 10 | 3 |
| 7 | feature | Scorer encoding the frozen tolerance/scale-flip/yes-no rules. | Scale-flip flagged, never auto-corrected; froze the 352/1486 exposure count. | 10 | 6 |
| 8 | feature | Model port + stub client + eval runner + `make eval-falsify`. | none — the falsification path proves the harness, not a judgement call | 15 | 4 |
| 9 | feature | Minimal per-turn results record. | none — stratification deferred to read-time | 6 | 3 |
| 10 | feature | CLI: `uv run main eval --client stub`. | none | 6 | 2 |
| 11 | feature | Real Anthropic adapter, fixture client, cache, fail-clean key handling. | Missing-key path fails clean, never falls back to a fixture silently. | 20 | 11 |
| 12 | risky-unknown | 3 real train conversations testing tool-routing and recall. | No design change needed — model uses the calculator and reuses prior answers; reported per-turn. | 25 | 6 |

\* `estimated: true` — see the timing note above.

## Session 2 — building the agent, first real numbers, train only (slices 13–18)

No dev calls, by design — the split I can't re-measure stays unspent until every other
question is settled.

| n | type | intent | decision | planned | actual |
|---|---|---|---|---|---|
| 13 | feature | Capture `response.usage` + cost telemetry; record the model decision. | Kept `claude-haiku-4-5-20251001`, reasoned from n=12's check. | 20 | 8 |
| 14 | measurement | Percentage-form A/B, 120 divide-turns, paired. | Adopted the raw-ratio instruction — p=0.000977, scale_flip 19/120→11/120. | 40 | 11† |
| 15 | risky-unknown | Diagnose arm B's below-floor accuracy before `TurnState`. | Root cause: the filter over-selects continuation questions needing `TurnState` — proceed. | 35 | 14 |
| 16 | feature | Wire `TurnState` into `AnthropicClient.answer()`. | `TurnState.add()`'s missing write-time check named as a gap, deferred to a later slice. | 35 | 14 |
| 17 | feature | CLI: `chat`/`eval` on the real client, `.env` loading. | Found and fixed a real spend-guard bypass (`--limit -1`); added `--confirm-dev-run` early. | 15 | 26 |
| 18 | measurement | First real numbers — 12-conversation train sample. | A prediction stated before the run held (divide accuracy 17.5%→36.4%, `no_answer` 51.7%→9.1%). | 25 | 8 |

† Timing carries a correction note, not a live capture — see above.

## Session 3 — fixes and the report (slices 19–26)

I wrote the report before running dev — every number in it comes from train and from
decisions already frozen, so none of it depends on a measurement I deliberately hadn't taken
yet.

| n | type | intent | decision | planned | actual |
|---|---|---|---|---|---|
| 19 | feature | `TurnState.add()` numeric-or-yes/no check at write time. | none — small, mechanical, per n=16's deferred item | 15 | 4 |
| 20 | measurement | Reviewer path checked live, with and without a key. | Argued keyless-`stub` was adequate — reversed at n=21 (kept struck through, not deleted). | 15 | 2 |
| 21 | feature | `chat --client fixture` — a real keyless demo. | n=20 retracted; built `FixtureClient`, explicitly not exercising tool-routing or repair. | 15 | 5 |
| 22 | report | Method: tolerance, exact-match ceiling, scale-flip, split, as argued decisions. | none — writes up decisions already made at n=1/2/7 | 35 | 2 |
| 23 | report | Error Analysis: cluster n=18's 16 failures by root cause. | Read as 2 systematic conversations (8/16), not 16 independent ones. | 25 | 2 |
| 24 | fix | Fix a services→adapter layering violation in `eval_falsify_check.py`. | Inject `ModelClient` rather than import `StubClient` directly. | 15 | 3 |
| 25 | report | Future Work + AI-tool disclosure. | none — reporting slice | 25 | 3 |
| 26 | fix | Pre-merge fixes: verify a disclosure claim, strip template scaffolding. | Guard-denial claim checked against a real transcript, kept; a second instance added. | 15 | 1 |

## Session 4 — polish, and a response to outside review (slices 27–29)

| n | type | intent | decision | planned | actual |
|---|---|---|---|---|---|
| 27 | report | Expand the disclosure with a checked count and session-ordering reasoning; add this file. | none — documentation slice | 25 | 4 |
| 28 | measurement | Remove the prompt's percentage exception (wrong against gold on 13.9% of dev) and re-run the slice-14 A/B to confirm before landing it. | Removed either way; the re-run also confirmed improvement (17.5%→30.0%, scale_flip 9.2%→0%, p=0.000275). | not pre-planned | 12 |
| 29 | report | Rewrite `REPORT.md`/`PROCESS.md` for plain language — same content and numbers. | none — register pass, no new facts | not pre-planned | 11 |

## Session 5 — the dev run (slices 30–33)

| n | type | intent | decision | planned | actual |
|---|---|---|---|---|---|
| 30 | code | Bounded retry-with-backoff around `messages.create` for transient failures (429/5xx); non-transient fails fast. | New `provider_error` reason, denominator retained, loop continues. | 25 | 4 |
| 31 | code | Close a double-retry gap: the SDK's own client defaults (600s timeout, 2 internal retries) stacked underneath ours, unbounded and uncounted. | Explicit `timeout=30.0, max_retries=0` on client construction — exactly one retry policy, ours. | 15 | 2 |
| 32 | code | `on_turn` progress callback; `--out` flush-to-disk with resume-safe truncate-at-start; `--cost-cap` one-time warning. | Verified with a real cache-replay resume test, not just design intent. | 30 | 14 |
| 33 | measurement | THE dev run: 421 conversations / 1490 turns, `--client anthropic --confirm-dev-run`, frozen from the moment it fired. | Completed clean: 3143s, $5.6207 of a $25 cap, no crash, no cap warning, no `provider_error`. | not pre-planned | 52 |

## Session 6 — verification (slices 34–35)

| n | type | intent | decision | planned | actual |
|---|---|---|---|---|---|
| 34 | fix | Suppress eval's per-turn progress lines when the client isn't the real Anthropic one — reviewer-experience only. | `--out`/`--cost-cap` stay unconditional; verified `--client stub` output drops from 11,105 lines to 5. | 15 | 7 |
| 35 | fix | Add a header line to eval's summary naming split/client/turn-count, so a reviewer can't confuse a train run's total with dev's 1490. | Cut, not deferred — the split is already visible via the invocation and this report's stated denominators. | 8 | 4 |

## Totals

There are **36 ledger rows across 6 sessions**:

* **34** became commits.
* **1** was reverted before any file was written, `n=3`, then redone as `n=4`.
* **1** was skipped without changing product code, `n=35`.

The branch had **42 commits** for this work, plus occasional follow-up fixes added immediately after a slice landed.

The current commit count can be checked with:

```text
git rev-list --count main..HEAD
```

because the number continued to grow before submission.

The full quality gate passed before every commit. I reran it myself each time rather than relying on a subagent's report.

Across the 6 sessions, the planned session budget was **975 minutes**:

```text
150, 150, 150, 120, 360, 45
```

The actual spend against that budget is reported in `REPORT.md`, because it continued changing until submission.

## Why the sessions ran in this order

**Session 1 — the measurement apparatus, zero model spend.** The scorer, the tolerance, the
scale-flip rule and the train/dev split were all fixed before any model call existed. That is the
whole point of the ordering: a metric decided after seeing a result is a metric that can be
adjusted to flatter it, and no amount of good intent removes that possibility once the number is
visible. The only exception was slice 12, which spent under $0.05 on three real conversations to
settle one design question — whether the model would route arithmetic to the calculator at all —
before building on the assumption that it would.

**Session 2 — the agent, first real numbers, train only.** Everything that changed model behaviour
was measured on train, where a result can be re-measured freely. Dev stayed unspent.

**Session 3 — the report, written before the dev run.** Every figure in the first draft came from
train and from decisions already frozen, so the report's structure and reasoning could not have
been assembled to fit a dev score that did not exist yet.

**Sessions 4–6 — polish, external review response, the dev run, verification.** Session 4 responded
to an outside review of the code and prose. Session 5 hardened the run path (retry, telemetry,
resume-safe flushing) and then fired the dev measurement. Session 6 was CLI verification and the
reproduction script.

## What was delegated, and what was not

Scoped implementation slices went to subagents: the executor, the scorer, the Anthropic adapter,
CLI wiring, and the tests for each. Each had an intent written before any edit, a limited file
list, and a check command.

Not delegated: the metric itself — the tolerance rule, the `scale_flip` policy, the train/dev
strategy — the plan and slice sequencing, and every checkpoint verification. Nothing was treated
as finished because a subagent reported it finished; the gate was re-run and the diff read before
each commit.

## Controls

A pre-tool-use hook blocks specific dangerous commands rather than asking an agent not to run
them. It fired twice during the project.

The first was a recursive force-delete on a scratch directory:

```text
BLOCKED: ... use targeted deletes, not recursive force. Ask the human if you truly need it.
```

I renamed the target instead. That one I saw directly.

The second was the soft-deadline stop: the first write attempt after a session's soft deadline is
refused until the ledger state is posted and scope is cut explicitly. That behaviour is in the
hook's source; the specific firing is corroborated from the transcript rather than something I
watched happen.

Alongside the hook: one commit per slice with the gate green before the next slice starts; a
separate reviewer role that reads diffs and reports findings by severity but never edits code and
never grades its own work; and a ledger recording planned against actual minutes for every slice.

## What the controls caught

**A spend-guard bypass.** `--limit -1` passed a `limit is not None` check but is Python's
slice-from-the-end, not "no records" — it silently selected nearly the entire train split. The
reviewer found it on an adversarial pass over a guard written an hour earlier. I reproduced it
live rather than reasoning about it, killed the run after 46 real calls, and fixed the validation
to reject any non-positive limit.

**A stale docstring.** `FixtureMissError` was documented as propagating uncaught. A handler was
added roughly five hours later, across a session boundary, and the docstring was not updated in
the same change. Found by the subagent implementing a later change, which read the existing
docstring while wiring a new handler and flagged the mismatch itself.

**A layering violation, before it landed.** A first draft of `eval_runner.py` imported
`estimate_cost_usd` directly from the concrete Anthropic adapter instead of keeping cost
conversion out of the service layer. Caught while reading the engineer's diff before checkpointing
— not by the reviewer agent, which was not invoked on that slice — and fixed before commit.

**An overstated claim in the report.** An early draft said the keyless demo used "the same tool
loop" as the live client. It does not: `FixtureClient` is a flat `(record_id, turn_index)` lookup
that ignores conversation state. Corrected against the source before commit.

**A second layering violation, found while writing.** Tracing the first one, I found
`eval_falsify_check.py` importing `StubClient` concretely — the exact defect class the
`import-linter` check I had declined would have caught. Fixed by injecting the interface, moving
the concrete import to the script's entry point, and adding the module's first test.

**A hidden retry layer.** The Anthropic SDK's client defaults (600s timeout, two internal retries)
were stacking underneath my own retry logic, unbounded and uncounted. Closed by constructing the
client with `timeout=30.0, max_retries=0` so exactly one retry policy exists.

## What the process got wrong

Twice, a subagent's self-reported slice timings were fabricated. In the first case the
`started`/`finished` fields were reconstructed after the fact rather than captured live. In the
second, a reported finish time was later than the moment the next task had already begun —
chronologically impossible, and believed until cross-checked.

Both are marked `estimated: true` in the ledger with a note, and excluded from this run's timing
figures, rather than quietly corrected to look like measured data. Slices 0, 1 and 2 carry that
mark; slice 14 carries a correction note where the impossible timestamp was replaced with the tool
call's own reported duration — more reliable, still not a live capture.

After that, every timestamp came from the orchestrator's own clock at the moment of writing, never
from a subagent's report. The lesson is recorded for the next engagement rather than applied
retroactively to make this one's numbers look cleaner.

## Verification

`docs/TESTING.md` records a manual CLI verification from a fresh clone: 16 steps, each with the
command, what it proves, and the observed result including exit code. Steps 9–14 are the guard
set — six distinct ways to misuse `eval --client anthropic`, every one refused by argument
validation before any client is constructed or any credential read. Verbatim output for the
captured steps is in `docs/cli-verification.txt`.

