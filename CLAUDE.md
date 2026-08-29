# llmRun — ConvFinQA conversational agent

A tool-calling agent for ConvFinQA. The model reads a financial document, resolves what a question
refers to, and names the calculation; a deterministic Python executor does the arithmetic. When an
answer is wrong the failure is in comprehension or reference resolution, never in the sums.

Measured once on the full dev split: **tolerant 1130/1490 = 75.84%**, strict 855/1490 = 57.38%,
conversation-level exact match 271/421 = 64.37%, $5.62.

## The rule that matters most

**The dev measurement is frozen.** It was taken once, at a specific commit, and the number in
`REPORT.md` describes that commit. Nothing that changes model behaviour may be edited — not the
system prompt, not the scorer, not the tolerance, not the executor, not the tool schema. A defect
found in any of them goes to `REPORT.md`'s Limitations with its evidence.

Documentation, tests, the CLI surface and tooling are all editable. Behaviour is not.

If a change genuinely must alter behaviour, the dev run has to be re-taken and every figure in
`REPORT.md` re-derived — which costs about $6 and an hour, and breaks the single-measurement
claim the report rests on. Say so out loud before doing it.

## Layering

```
src/cli → src/adapters → src/services → src/domain
```

- `src/domain` — record models, the six-operation executor, the scorer, the tolerance policy. No
  SDK, no network, no clock. Testable without a mock.
- `src/services` — the conversation loop, `TurnState`, the eval runner. Depends on the
  `ModelClient` protocol, never a concrete client.
- `src/adapters` — the only layer importing `anthropic`. Also holds `FixtureClient` (keyless
  replay), `StubClient` (falsification) and the response cache.
- `src/main.py` — wiring only.

Adapters sit above services because they implement ports services declares. **Nothing enforces
this** — `import-linter` was considered and declined for budget, and that gap already produced one
real violation. Treat a services→adapters import as a defect even though the gate will not catch
it.

## Running it

```bash
uv sync
uv run main chat "Single_SLG/2013/page_133.pdf-4" --client fixture   # no key, no network
uv run main eval --client stub                                       # falsification, scores 0.0
make check                                                           # full gate, keyless
make recompute-dev                                                   # every report figure, from the artifact
```

`--limit` is required with a real client. `--split dev` additionally requires `--confirm-dev-run`,
because dev is scored once and cannot be made unseen.

## Where the numbers come from

`results/dev_results.jsonl` — 1,490 lines, one per turn, written during the run and committed
unchanged. `make recompute-dev` re-derives every figure in `REPORT.md` from it, importing the real
`score_turn` rather than reimplementing scoring. If a figure in the report and a figure from that
command disagree, **the artifact is right and the report is wrong.**

## Reading order

- `REPORT.md` — method, metric reasoning, results, error analysis, limitations
- `docs/ARCHITECTURE.md` — how one turn flows through the system
- `docs/TESTING.md` — 16-step manual CLI verification with exit codes
- `PROCESS.md` — how it was built, slice by slice

## Conventions

- Ruff and mypy are in the gate. `ruff check --no-fix` — this repo's own config sets `fix = true`,
  so a bare `ruff check` rewrites files, and a gate that rewrites the tree is not a check.
- Docstrings are required on public functions (`D101`/`D102`/`D103`) and bare `print` is banned
  (`T201`) — use `rich_print`.
- `zip(..., strict=True)` unless truncation is deliberate and commented. Four bare zips were
  silently truncating until the Python floor was raised.
- Tests run with no API key and no network: `tests/conftest.py` blocks sockets for the whole
  suite, and `tests/test_network_is_blocked.py` proves the block by attempting a real socket.

## What is in `.claude/`

Skills for the two things that actually recur in this repo, and one review agent scoped to the
rules above. No hooks and no `allowed-tools` anywhere — a skill carrying either can act on the
machine of whoever clones this repo, and nothing here needs that.

`.mcp.json` points at `mcp_server/scorer_server.py` in this repo: stdio only, no network, no
credentials. Claude Code will ask you to approve it the first time. Read it before you do — that
is the right instinct for any project-scoped MCP server, not just this one.

Verify what actually loaded with `/context` and `/mcp` inside a session. `make harness-check`
validates everything checkable offline, but only `/context` proves an instruction file was read.
