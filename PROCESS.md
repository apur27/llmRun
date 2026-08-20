# PROCESS.md

The engineering ledger: one row per slice, each with an intent written down first, its own
check, and the full gate re-run before I committed it.

Built with Claude Code, using my own tooling for running coding agents against a deadline — a
hook that blocks specific dangerous commands, a work ledger, a checkpoint per increment. That
tooling lives in a separate private repository, not part of this submission. This file comes
directly from two of its records — `slices.jsonl` (planned vs. actual, timestamped) and
`plan.md` (the decisions, as made). Nothing here is from memory; a missing field says so.

**On the timings.** Early on a subagent's self-reported start/finish time proved unreliable,
including two fabricated entries; those are marked `estimated: true` and left out of the
timing figures below. Later timings came from my own clock. Slices 0, 1, 2 carry that flag
(reconstructed after the fact). Slice 14's reported finish time was impossible and was
corrected using the tool call's own reported duration — closer, but still not a live capture.

**The reverted slice.** `n=3` was stopped before any file was written, to fix the timing issue
above — listed below as reverted, not omitted; redone cleanly as `n=4`.

**The skipped slice.** `n=35` was cut, not built — a nice-to-have header line for the eval
summary, dropped because the split it would have named is already visible another way
(`--split` on the invocation, the denominators in this report). Listed below with its reason,
not omitted.

## Session 1 — building what measures accuracy (slices 0–12)

Zero spend was the goal, so the metric could be frozen before any model existed to tune it
toward. One exception: slice 12 spent under $0.05 on 3 real conversations early, to de-risk a
design question.

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

36 ledger rows across six sessions: 34 landed as commits, one reverted before any file was
written (`n=3`, redone as `n=4`), one skipped with no product-code edit (`n=35`). 42 commits on
this branch for that work, plus an occasional follow-on commit for a fix that surfaced right
after landing (noted individually, not folded into a later diff) — `git rev-list --count
main..HEAD` gives the live figure, since it keeps growing before submission. The gate ran green
before every one of those commits; I re-ran it myself each time, never took a subagent's word
for it.

975 minutes of session budget across the six sessions (150, 150, 150, 120, 360, 45). Real spend
against that budget is in the disclosure in `REPORT.md`, not repeated here since it's a
still-growing figure right up to submission.
