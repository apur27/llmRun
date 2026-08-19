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
Lorem ipsum dolor sit amet consectetur adipiscing elit
## Error Analysis
Lorem ipsum dolor sit amet consectetur adipiscing elit
## Future Work 
Lorem ipsum dolor sit amet consectetur adipiscing elit
## [may not apply] If & how you've used coding assistants or gen AI tools to help with this assignment 
Please be honest.

Lorem ipsum dolor sit amet consectetur adipiscing elit
