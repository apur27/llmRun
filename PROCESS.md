# PROCESS.md

This is the engineering ledger behind this submission: one row per unit of work ("slice"),
each defined by an intent written before any edit, a check specific to that slice, and the
full gate (`make check`) run again before the commit.

Built with Claude Code, driven by my own tooling for running coding agents against a
deadline — a pre-tool-use guard, a work ledger, and per-increment checkpoints. That tooling
and its artifacts (the ledger, the plan, the session notes referenced below) live in a
separate private repository and are not part of this submission. This file is sourced
directly from two of those artifacts — `slices.jsonl` (the machine-written ledger: what was
planned, what actually ran, when) and `plan.md` (the design decisions, written as they were
made). Nothing below is reconstructed from memory; where a field wasn't in either source, it
says so.

**Timing caveat, stated plainly.** Slices 0, 1 and 2 carry `estimated: true` in the ledger:
their `started`/`finished` timestamps were reconstructed after the fact rather than captured
live, so the "actual" minutes for those three rows are not measured data — treat them as
approximate. Slice 14 carries a separate note: its self-reported `finished` timestamp was
independently found to be impossible (later than wall clock at the time the *next* slice
started) and was corrected to a duration derived from the tool call's own reported elapsed
time — a proxy, not a live capture, though not flagged `estimated: true` in the ledger itself.
Every other row's timing was captured live by the process orchestrating the work, independent
of any subagent's self-report — a discipline adopted only after the first two fabricated
timestamps were caught (see the AI-tool disclosure in `REPORT.md`).

**The reverted slice.** `n=3` was started, then stopped before any file was written — not a
failure of the work itself, but a deliberate pause to fix the ledger-integrity issue described
above before continuing. It is listed below with `status: reverted`, not omitted; the loader
work it was meant to do was redone cleanly as `n=4`.

## Session 1 — measurement apparatus (slices 0–12)

Zero API spend was the design intent for this session — build and freeze the metric before
any model existed to tune it toward, per the frozen METRIC section in `plan.md`. One
exception: slice 12 pulled forward 3 real conversations (sub-$0.05) to de-risk a design
question early, disclosed as such in `REPORT.md`.

| n | type | intent | decision made | planned min | actual min |
|---|---|---|---|---|---|
| 0 | scaffold | Adopt the gate: ruff `--no-fix`, mypy, pytest+cov+randomly, `Makefile` `check` target. | none — mechanical (adopts the brief's prescribed gate verbatim) | 15 | 3* |
| 1 | measurement | Freeze the tolerance epsilon and scale-flip decision from dev gold data alone, no model call. | Epsilon = 1e-3 relative — the exact point exact-vs-tolerant agreement on gold goes from partial (945/1486) to total (1486/1486). | 12 | 8* |
| 2 | measurement | Defend the frozen epsilon with a parametrised sweep across `{0, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2}`. | True floor ≈7.4e-4; 1e-3 sits at 1.34x that floor; 1e-2 accepts zero turns beyond what 1e-3 already accepts. | 8 | 3* |
| 3 | feature | Domain models + record loader (attempt). | none — reverted before any code existed | 14 | not recorded |
| 4 | feature | Domain models + record loader, redo of n=3. | none — mechanical (schema follows `dataset.md`; train/dev counts and zero doc-overlap are asserted as a test, not decided) | 14 | 3 |
| 5 | feature | Program executor: six DSL ops + within-turn `#0`/`#1` refs + `const_*` constants. | none — mechanical (implements the six-operation vocabulary already inventoried before this slice) | 17 | 3 |
| 6 | measurement | 1490-point gold replay: every dev `turn_program` executed and compared to `executed_answers` within the frozen epsilon. | none — mechanical validation of n=1's frozen epsilon and n=5's executor | 10 | 3 |
| 7 | feature | Scorer + tolerance policy encoding the frozen epsilon/scale-flip/yes-no rules. | Scale-flip scored strict and distinct — never auto-corrected to correct, only flagged; 352/1486 exposure counted and frozen. | 10 | 6 |
| 8 | feature | Model port (Protocol) + stub client + eval runner + `make eval-falsify`. | none — mechanical (the falsification path is the harness proving itself, not a judgement call) | 15 | 4 |
| 9 | feature | Minimal per-turn results record (`outcome`/`reason`/`scale_flip`). | none — mechanical; stratification computation deliberately deferred to read-time | 6 | 3 |
| 10 | feature | CLI wiring: `uv run main eval --client stub`. | none — mechanical | 6 | 2 |
| 11 | feature | Real Anthropic adapter, fixture client, response cache, fail-clean missing-key handling. | Missing-key path fails clean (one line, distinct exit, no traceback) rather than a silent fixture fallback. | 20 | 11 |
| 12 | risky-unknown | THE RISKY UNKNOWN — 3 real train conversations testing tool-routing and cross-turn recall. | No design change forced: the model routes arithmetic to the calculator and reuses recorded prior answers; findings recorded per-turn, not as one verdict. | 25 | 6 |

\* Timing marked `estimated: true` in the ledger — see the caveat above.

## Session 2 — the agent, first real numbers on train only (slices 13–18)

`dev` is untouched this session by design — the split that cannot be re-measured once spent
(per `plan.md`'s METRIC section) stays unspent until every other design question is settled.

| n | type | intent | decision made | planned min | actual min |
|---|---|---|---|---|---|
| 13 | feature | Capture `response.usage` + cost telemetry; record the model decision. | Kept `claude-haiku-4-5-20251001`, reasoned from n=12's routing/recall validation rather than inherited silently from the probe. | 20 | 8 |
| 14 | measurement | Percentage-form convention experiment, N=120 divide-turns, paired A/B. | Variant B (raw-ratio instruction) adopted — McNemar exact p=0.000977, scale_flip 19/120→11/120. | 40 | 11† |
| 15 | risky-unknown | Diagnose arm B's below-floor accuracy before wiring `TurnState` on top of it. | Root cause: the divide/MOVES filter over-selects continuation questions needing `TurnState`, not a calculator/scorer/routing bug — proceed to `TurnState`. | 35 | 14 |
| 16 | feature | Wire `TurnState` into `AnthropicClient.answer()` for cross-turn recall. | `TurnState.add()` write-time validation named as a real gap and deliberately deferred to a later slice, not silently left. | 35 | 14 |
| 17 | feature | CLI wiring: `chat`/`eval` against the real client, `.env` loading. | A real spend-guard bypass (`--limit -1`) was found and fixed live; a `--confirm-dev-run` guard was added ahead of schedule. | 15 | 26 |
| 18 | measurement | First real numbers — 12-conversation stratified train sample. | Pre-stated prediction confirmed, not just measured after the fact (divide accuracy 17.5%→36.4%, `no_answer` 51.7%→9.1%). | 25 | 8 |

† Timing carries a correction note in the ledger (not a live capture) — see the caveat above.

## Session 3 — fixes and the report (slices 19–26)

The report was written before the `dev` run, not after — every number in it is sourced to
`train` and to decisions already frozen, so nothing in the write-up depends on a measurement
this session deliberately hadn't taken yet.

| n | type | intent | decision made | planned min | actual min |
|---|---|---|---|---|---|
| 19 | feature | `TurnState.add()` numeric-or-yes/no guard at write time. | none — fix scoped small and mechanical, per n=16's deferred decision | 15 | 4 |
| 20 | measurement | Reviewer path verified live, with and without a key. | Keyless-chat-via-stub argued adequate — later reversed at n=21 (kept struck through in `plan.md`, not deleted). | 15 | 2 |
| 21 | feature | `chat --client fixture` — a genuine keyless reviewer demo. | n=20's keyless-stub argument retracted; `FixtureClient` built instead, explicitly scoped as not exercising tool-routing or the parse-repair path. | 15 | 5 |
| 22 | report | `REPORT.md` Method: epsilon, exact-match ceiling, scale-flip, train/dev split as argued decisions. | none — writes up decisions already made at n=1/2/7 | 35 | 2 |
| 23 | report | `REPORT.md` Error Analysis: cluster n=18's 16 failures by root cause. | Failures read as 2 systematic conversations (8/16), not 16 independent occurrences — a framing decision for how the number is reported. | 25 | 2 |
| 24 | fix | Fix a services→adapter layering violation in `eval_falsify_check.py`. | Inject `ModelClient` rather than import `StubClient` concretely — found while researching the disclosure section, not by any prior review pass. | 15 | 3 |
| 25 | report | `REPORT.md` Future Work + AI-tool disclosure. | none — reporting slice | 25 | 3 |
| 26 | fix | `REPORT.md` pre-merge fixes: verify or remove a disclosure claim, strip template scaffolding. | The guard-denial claim was verified against a real transcript rather than removed under challenge; kept, with a second corroborated instance added. | 15 | 1 |

## Session 4 — polish and submission (in progress)

Not part of the "27 slices across 3 sessions" count in `REPORT.md`'s disclosure — that
paragraph deliberately describes the three-session build arc (measure → agent → report) as
designed. This table is the raw ledger and includes session 4's work for completeness.

| n | type | intent | decision made | planned min | actual min |
|---|---|---|---|---|---|
| 27 | report | Expand the AI-tool disclosure with a verified count and session-ordering rationale; add this file; scrub the internal tool's name from both. | none — reporting/documentation slice | 25 | 4 |
| 28 | measurement | Remove `_SYSTEM_INSTRUCTIONS`'s conditional percentage carve-out (proven wrong against gold on 13.9% of dev's denominator) and re-run the slice-14 paired A/B (N=120, same seed/candidates/scorer) to confirm before landing the change. | Carve-out removed unconditionally; measured improvement (17.5%→30.0% tolerant-correct, scale_flip 9.2%→0%, N=120 b=16 c=1 p=0.000275) confirms a decision already required by gold consistency alone. | not pre-planned (user-initiated mid-session) | 11 |

## Totals

29 ledger rows across this and the prior three sessions (26 landed as commits + 1 reverted
in sessions 1–3, plus 2 more in session 4), 3+1 sessions, 29 commits on the working branch
as of this slice (a few slices produced a small follow-on commit for a fix surfaced
immediately after landing — noted individually in the ledger's own result text, not hidden
inside a single commit's diff) — verifiable with `git rev-list --count main..HEAD`.
