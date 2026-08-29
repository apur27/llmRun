"""MCP server exposing this repo's deterministic domain layer over stdio.

Three tools: execute a ConvFinQA program, score a prediction against gold, and look up a dev
turn's gold record. All three call the *production* modules in `src/domain/` -- there is no second
implementation here that could drift from the one the reported numbers came from.

Deliberately constrained, because a project-scoped `.mcp.json` runs on the machine of whoever
approves it:

* stdio transport only. No network listener, no outbound calls.
* No credentials read, none required. Nothing here touches `ANTHROPIC_API_KEY`.
* Read-only. Nothing writes to disk.
* The dataset it reads is the one already committed in this repo.

Run it directly to check it starts:

    uv run python mcp_server/scorer_server.py --selftest

Requires the `mcp` package, which is an optional extra rather than a core dependency:

    uv add --optional mcp mcp
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.domain.executor import ProgramExecutionError, execute_program  # noqa: E402
from src.domain.scorer import score_turn  # noqa: E402

DATASET = REPO_ROOT / "data" / "convfinqa_dataset.json"

_GOLD_INDEX: dict[str, list[dict[str, Any]]] | None = None


def _gold_index() -> dict[str, list[dict[str, Any]]]:
    """Build a record_id -> per-turn gold index from the committed dev split, once."""
    global _GOLD_INDEX
    if _GOLD_INDEX is None:
        raw = json.loads(DATASET.read_text())
        index: dict[str, list[dict[str, Any]]] = {}
        for record in raw["dev"]:
            dialogue = record["dialogue"]
            index[record["id"]] = [
                {
                    "turn_index": i,
                    "question": q,
                    "turn_program": p,
                    "gold": g,
                }
                for i, (q, p, g) in enumerate(
                    zip(
                        dialogue["conv_questions"],
                        dialogue["turn_program"],
                        dialogue["executed_answers"],
                        strict=True,
                    )
                )
            ]
        _GOLD_INDEX = index
    return _GOLD_INDEX


def tool_execute_program(program: str) -> dict[str, Any]:
    """Execute a ConvFinQA DSL program with the same executor the live calculate tool uses."""
    try:
        return {"ok": True, "result": execute_program(program)}
    except ProgramExecutionError as exc:
        return {"ok": False, "error": type(exc).__name__, "message": str(exc)}


def tool_score(predicted: float | str, gold: float | str) -> dict[str, Any]:
    """Score a prediction against gold using the production scorer and its frozen tolerance.

    Returns `ScoreResult`'s own fields -- `strict_correct`, `tolerant_correct`, `scale_flip` --
    via `asdict`, so this tool tracks the dataclass rather than a hand-copied field list. If the
    domain adds a field it appears here; if it renames one, `--selftest` fails loudly.

    `outcome` and `reason` are deliberately absent. They are derived in `src/services/eval_runner`
    from this result, and reimplementing that mapping here would put a second copy of a
    service-layer rule in an adapter -- exactly the drift `scripts/recompute_dev.py` avoids by
    importing `score_turn` instead of reimplementing the scoring rules.
    """
    return asdict(score_turn(predicted=predicted, gold=gold))


def tool_gold_turn(record_id: str, turn_index: int) -> dict[str, Any]:
    """Look up one dev turn's question, gold program and gold answer."""
    turns = _gold_index().get(record_id)
    if turns is None:
        sample = sorted(_gold_index())[:3]
        return {
            "ok": False,
            "error": f"no dev record with id {record_id!r}",
            "example_ids": sample,
        }
    if not 0 <= turn_index < len(turns):
        return {
            "ok": False,
            "error": f"turn {turn_index} out of range; record has {len(turns)} turns",
        }
    return {"ok": True, **turns[turn_index]}


def selftest() -> int:
    """Exercise all three tools without starting a server. Used by make harness-check."""
    checks: list[tuple[str, bool, str]] = []

    got = tool_execute_program("subtract(60.94, 25.14)")
    checks.append(("execute_program", got.get("ok") is True, repr(got)))

    bad = tool_execute_program("nonsense(")
    checks.append(("execute_program rejects malformed", bad.get("ok") is False, repr(bad)))

    # Assert on ScoreResult's real fields. An earlier version of this tool used
    # getattr(result, "outcome", None), which returned None for a field that does not exist
    # instead of raising -- a defensive default turning a hard error soft. asdict cannot.
    exact = tool_score(predicted=35.8, gold=35.8)
    checks.append(
        (
            "score_turn exact",
            exact == {"strict_correct": True, "tolerant_correct": True, "scale_flip": False},
            repr(exact),
        )
    )

    # Inside the 1e-3 tolerance but outside 1e-9: tolerant yes, strict no. This is the whole
    # reason both are reported.
    near = tool_score(predicted=35.8005, gold=35.8)
    checks.append(
        (
            "score_turn tolerant but not strict",
            near["tolerant_correct"] is True and near["strict_correct"] is False,
            repr(near),
        )
    )

    # The ratio-vs-percentage case: flagged, never elevated to correct.
    flip = tool_score(predicted=50.0, gold=0.5)
    checks.append(
        (
            "scale_flip flagged, still incorrect",
            flip["scale_flip"] is True and flip["tolerant_correct"] is False,
            repr(flip),
        )
    )

    # A yes/no gold is compared as a string, never coerced.
    yes = tool_score(predicted="yes", gold="yes")
    checks.append(("yes/no scored as string", yes["tolerant_correct"] is True, repr(yes)))

    index = _gold_index()
    checks.append(("gold index built", len(index) == 421, f"{len(index)} records"))
    total_turns = sum(len(v) for v in index.values())
    checks.append(("gold turns", total_turns == 1490, f"{total_turns} turns"))

    missing = tool_gold_turn("does-not-exist", 0)
    checks.append(("unknown record is clean", missing.get("ok") is False, repr(missing)))

    failed = 0
    for name, ok, detail in checks:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}: {detail}")
        failed += 0 if ok else 1
    print(f"\n{len(checks) - failed} passed, {failed} failed")
    return 1 if failed else 0


def _load_server_class() -> tuple[type, str]:
    """Return the MCP server class and which SDK generation it came from.

    2.x renamed `FastMCP` to `MCPServer` and moved it to `mcp.server.mcpserver`. Both are tried
    so this runs on either without pinning; the shape is the same -- `tool()` is a decorator
    factory, `run()` defaults to stdio.
    """
    try:
        from mcp.server.mcpserver import MCPServer

        return MCPServer, "2.x"
    except ModuleNotFoundError:
        from mcp.server.fastmcp import FastMCP  # mcp<2

        return FastMCP, "1.x"


def main() -> int:
    """Start the stdio server, run the selftest, or check that the SDK imports."""
    if "--selftest" in sys.argv:
        return selftest()

    try:
        server_class, generation = _load_server_class()
    except ImportError as exc:
        # Report the actual exception. An earlier version printed "the mcp package is not
        # installed" for any ImportError, which was wrong and actively misleading the day the
        # SDK renamed a class -- the package was installed, the message said otherwise.
        print(f"cannot load the MCP server class: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(
            "\nif the package is genuinely absent, it is an optional extra:\n"
            "    uv add --optional mcp mcp",
            file=sys.stderr,
        )
        return 3

    if "--check-imports" in sys.argv:
        print(f"ok    MCP SDK {generation}: {server_class.__module__}.{server_class.__name__}")
        return 0

    server = server_class("convfinqa-domain")
    server.tool()(tool_execute_program)
    server.tool()(tool_score)
    server.tool()(tool_gold_turn)
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
