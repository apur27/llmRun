# TESTING.md

A manual CLI verification record — every command below was run by hand in a fresh clone, not
scripted, not replayed. Steps 9–14 confirm that every spend/input guard refuses *before* a
model client is ever constructed: no key is read, no network call is attempted, on any of
those six paths.

Output for steps 3, 5, 7, 9–14 is captured verbatim in `docs/cli-verification.txt`, committed
alongside this file. Steps 1, 2, 4, 6, 8, 15, 16 are recorded here from the same hand-run
session; their output wasn't separately captured to a file.

| # | Command | What it proves | Observed result |
|---|---|---|---|
| 1 | `git clone …` | The repo clones cleanly — no submodules, no missing LFS assets. | Clean clone, no errors. |
| 2 | `uv sync` | Dependencies install from the lockfile alone, no network surprises beyond package fetch. | Installed cleanly. |
| 3 | `uv run main --help` | The CLI is discoverable and its two commands (`chat`, `eval`) are documented. | Help text printed, `chat`/`eval` listed. Exit 0. |
| 4 | `uv run main chat "Single_SLG/2013/page_133.pdf-4" --client fixture` | The keyless demo path works with no key and no network — four real recorded answers replayed. | 4 correct answers printed, keyless. Exit 0. |
| 5 | `uv run main eval --client stub` | The falsification check: a predictor that's wrong on every turn by construction must score 0.0, proving the scorer can report failure, not just success. | `total turns: 11104`, strict 0.0 (0/11104), tolerant 0.0 (0/11104). Exit 0. |
| 6 | `uv run main chat <record_id>` with no `ANTHROPIC_API_KEY` set | Missing key fails clean, one error line, no crash, no silent fallback. | One clean error line. Exit 1. |
| 7 | `uv run main chat does-not-exist` | An unknown record id fails clean rather than crashing on a lookup miss. | `no record found with id 'does-not-exist'`. Exit 1. |
| 8 | `uv run main chat <valid_record_id>` with no matching fixture, `--client fixture` | A valid id with no recorded fixture fails clean and tells the reviewer what ids *are* available, rather than crashing. | Named the available fixture ids. Exit 1. |
| 9 | `uv run main eval --client anthropic` | `--client anthropic` without `--limit` is refused before any client is constructed — real spend is never sized by accident. | `Invalid value: --client anthropic requires --limit …`. Exit 2. |
| 10 | `uv run main eval --client anthropic --limit -1` | A negative `--limit` is refused rather than silently slicing from the end of the split (Python list-slicing semantics), which would select nearly the whole split. | `Invalid value: --limit must be a positive integer, got -1 …`. Exit 2. |
| 11 | `uv run main eval --client anthropic --limit 0` | Same guard, zero case. | `Invalid value: --limit must be a positive integer, got 0 …`. Exit 2. |
| 12 | `uv run main eval --client anthropic --split dev --limit 1` | `--split dev` is refused without `--confirm-dev-run` — dev is scored once, and this flag exists so that can't happen by accident. | `Invalid value: --client anthropic --split dev also requires --confirm-dev-run …`. Exit 2. |
| 13 | `uv run main eval --client stub --split banana` | An unsupported split name is refused with the valid choices named. | `Invalid value: unsupported --split 'banana': choose 'train' or 'dev'`. Exit 2. |
| 14 | `uv run main eval --client nonsense` | An unsupported client name is refused with the valid choices named. | `Invalid value: unsupported --client 'nonsense': choose 'stub' or 'anthropic'`. Exit 2. |
| 15 | `make check`, no `ANTHROPIC_API_KEY` set | The whole gate — format, lint, types, tests — passes with no key and no network. | 134 passed, 95% coverage. Exit 0. |
| 16 | `uv run main eval --client anthropic --split train --limit 2` | A real, minimal-spend run against the live model completes and scores correctly. | 8/8 tolerant, $0.0250. |

Steps 9–14 are the guard set: six distinct ways to misuse `eval --client anthropic`, every one
refused by argument validation before `AnthropicClient` (or any network call) is constructed.
