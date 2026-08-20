"""Recompute every dev-results figure this report states, straight from the committed artifact.

Reads `results/dev_results.jsonl` (one line per scored turn, written as the dev run progressed
and committed unchanged) and re-derives every headline and stratified number by importing the
actual scorer and executor rather than reimplementing them, so this script cannot silently
drift from the production code paths it is checking. `type1`/`type2` needs one field
(`has_type2_question`) that isn't in the artifact, so it's joined from `data/convfinqa_dataset.json`
by `record_id`. Keyless, offline: no network, no model client, no SDK.

Five figures are asserted against the numbers this report states, because a real value already
exists to check them against; a mismatch is a real regression, not a rounding question, and this
script exits non-zero rather than print a quiet discrepancy. Everything else (by turn index, by
step count, literal vs. computation, type1 vs. type2) is printed only -- there is no committed
number to assert it against yet.
"""

import json
from collections import defaultdict
from pathlib import Path

from rich import print as rich_print

from src.domain.executor import _tokenize
from src.domain.loader import load_dataset
from src.domain.scorer import score_turn

RESULTS_PATH = Path("results/dev_results.jsonl")
DATASET_PATH = Path("data/convfinqa_dataset.json")

EXPECTED_TOLERANT = (1130, 1490)
EXPECTED_STRICT = (855, 1490)
EXPECTED_REASONS = {"ok": 1130, "wrong_value": 335, "parse_error": 25}
EXPECTED_SCALE_FLIP = 10
EXPECTED_CONVERSATION_EXACT = (271, 421)


def load_results() -> list[dict]:
    """Read the committed per-turn artifact, one JSON object per line."""
    lines = RESULTS_PATH.read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def score(predicted, gold):
    """Strict/tolerant/scale_flip for one turn; a `None` prediction is incorrect, not scored."""
    if predicted is None:
        return False, False, False
    result = score_turn(predicted, gold)
    return result.strict_correct, result.tolerant_correct, result.scale_flip


def pct(numerator: int, denominator: int) -> str:
    """Format a count as `n/d = pp.pp%`."""
    return f"{numerator}/{denominator} = {numerator / denominator * 100:.2f}%"


def check(label: str, actual, expected, failures: list[str]) -> None:
    """Print one figure's actual vs. expected value, recording a mismatch onto `failures`."""
    mark = "OK" if actual == expected else "MISMATCH"
    rich_print(f"[{mark}] {label}: actual={actual} expected={expected}")
    if actual != expected:
        failures.append(f"{label}: actual={actual} expected={expected}")


def main() -> int:
    """Recompute and print every dev-results figure, returning 1 if any checked one disagrees."""
    rows = load_results()
    n = len(rows)
    failures: list[str] = []

    scored = []
    for r in rows:
        strict_ok, tolerant_ok, scale_flip = score(r["predicted"], r["gold"])
        scored.append(
            {
                "record_id": r["record_id"],
                "turn_index": r["turn_index"],
                "turn_program": r["turn_program"],
                "reason": r["reason"],
                "strict_ok": strict_ok,
                "tolerant_ok": tolerant_ok,
                "scale_flip": scale_flip,
            }
        )

    rich_print(f"turns: {n}\n")

    tolerant_total = sum(s["tolerant_ok"] for s in scored)
    strict_total = sum(s["strict_ok"] for s in scored)
    scale_flip_total = sum(s["scale_flip"] for s in scored)
    reason_counts: dict[str, int] = defaultdict(int)
    for s in scored:
        reason_counts[s["reason"]] += 1

    rich_print("== headline ==")
    rich_print(f"tolerant accuracy: {pct(tolerant_total, n)}")
    rich_print(f"strict accuracy:   {pct(strict_total, n)}")
    rich_print(f"reason breakdown:  {dict(sorted(reason_counts.items()))}")
    rich_print(f"scale_flip count:  {scale_flip_total}")
    rich_print()

    check("tolerant accuracy", (tolerant_total, n), EXPECTED_TOLERANT, failures)
    check("strict accuracy", (strict_total, n), EXPECTED_STRICT, failures)
    check("reason breakdown", dict(reason_counts), EXPECTED_REASONS, failures)
    check("scale_flip count", scale_flip_total, EXPECTED_SCALE_FLIP, failures)
    rich_print()

    rich_print("== by turn index (tolerant) ==")
    by_turn: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for s in scored:
        by_turn[s["turn_index"]][1] += 1
        by_turn[s["turn_index"]][0] += int(s["tolerant_ok"])
    for idx in sorted(by_turn):
        c, t = by_turn[idx]
        rich_print(f"  turn {idx}: {pct(c, t)}")
    rich_print()

    rich_print(
        "== literal vs. computation (tolerant), and step count within computation =="
    )
    literal = [0, 0]
    computation = [0, 0]
    step_counts: dict[object, list[int]] = defaultdict(lambda: [0, 0])
    for s in scored:
        program = s["turn_program"]
        bucket = literal if "(" not in program else computation
        bucket[1] += 1
        bucket[0] += int(s["tolerant_ok"])
        if "(" in program:
            steps = len(_tokenize(program))
            key = steps if steps < 3 else "3+"
            step_counts[key][1] += 1
            step_counts[key][0] += int(s["tolerant_ok"])
    rich_print(f"  literal:     {pct(literal[0], literal[1])}")
    rich_print(f"  computation: {pct(computation[0], computation[1])}")
    for key in sorted(step_counts, key=lambda k: (k == "3+", k)):
        c, t = step_counts[key]
        rich_print(f"    step count {key}: {pct(c, t)}")
    rich_print()

    rich_print(
        "== type1 vs. type2 (tolerant; has_type2_question joined from the dataset) =="
    )
    dataset = load_dataset(DATASET_PATH)
    has_type2 = {rec.id: rec.features.has_type2_question for rec in dataset["dev"]}
    type1 = [0, 0]
    type2 = [0, 0]
    for s in scored:
        bucket = type2 if has_type2.get(s["record_id"]) else type1
        bucket[1] += 1
        bucket[0] += int(s["tolerant_ok"])
    rich_print(f"  type1: {pct(type1[0], type1[1])}")
    rich_print(f"  type2: {pct(type2[0], type2[1])}")
    rich_print()

    rich_print("== conversation-level exact match (every turn tolerant-correct) ==")
    by_record: dict[str, list[bool]] = defaultdict(list)
    for s in scored:
        by_record[s["record_id"]].append(s["tolerant_ok"])
    conv_correct = sum(1 for turns in by_record.values() if all(turns))
    conv_total = len(by_record)
    rich_print(f"  {pct(conv_correct, conv_total)}")
    check(
        "conversation-level exact match",
        (conv_correct, conv_total),
        EXPECTED_CONVERSATION_EXACT,
        failures,
    )
    rich_print()

    if failures:
        rich_print(
            f"FAILED: {len(failures)} figure(s) disagree with the committed report:"
        )
        for f in failures:
            rich_print(f"  - {f}")
        return 1
    rich_print("All checked figures match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
