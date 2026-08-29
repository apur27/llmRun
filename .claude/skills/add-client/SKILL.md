---
name: add-client
description: Add a new ModelClient implementation — a second provider, a recording client, a deterministic fake. Use when extending the model layer, and to check that an existing client satisfies the port contract.
---

# add-client

`src/adapters/ports.py` declares the `ModelClient` protocol. Three implementations exist:
`AnthropicClient` (real), `FixtureClient` (keyless replay of recorded answers), `StubClient`
(always wrong, used by the falsification check). A fourth goes in `src/adapters/`.

## Before writing anything

Read `src/adapters/ports.py`, then `src/adapters/stub_client.py` — the smallest complete
implementation, about 30 lines. The protocol is the contract; the stub shows the minimum that
satisfies it.

## The contract test is the point

`tests/adapters/test_model_client_contract.py` runs every implementation against the same
assertions. A new client is added to that test's parameter list, not given a bespoke test file.

That test already encodes one real divergence found by writing it: `FixtureMissError` is **not** a
`ProgramExecutionError`, which is the type `run_eval` catches. So a fixture miss propagates where
a program error is handled — gate-green and production-green are not the same claim. Any new
client raising its own error type has the same question to answer: **which of your exceptions does
`run_eval` actually catch, and what happens to the ones it does not?**

## Rules

- **Services never import a concrete client.** Wire it in `src/main.py`'s client builder, and
  nowhere else. `src/services/` depends only on the protocol.
- **Declare every exception type as caught or propagating**, in the docstring, and keep that
  docstring true. One in this repo said `PROPAGATES: no handler exists` for nearly five hours
  after a handler landed.
- **Fail clean on a missing credential** — one line naming the variable, a distinct non-zero exit,
  no traceback, and never a silent fall-back to a fixture.
- **No network in tests.** `tests/conftest.py` blocks sockets suite-wide. If a new test needs to
  reach the network it is the wrong test.
- **Set the provider's own retry and timeout defaults explicitly.** `AnthropicClient` passes
  `timeout=30.0, max_retries=0` because the SDK's own layer otherwise stacks underneath the
  repo's retry, unbounded and uncounted.

## What this must not do

Adding a client does not change the reported number. The dev measurement is frozen at its commit
and describes `AnthropicClient` with a pinned model and temperature 0. A second provider is a
capability, not a re-measurement — if you want a comparison, that is a new run, a new artifact and
a new section, not an edit to the existing figures.

## Check

```bash
uv run pytest tests/adapters/test_model_client_contract.py -v
make check
```
