"""Calibrate the eval tolerance and size the scale-flip ambiguity from dev gold alone.

Before any model call or any src/domain executor exists, this test derives two numbers the
eval metric depends on, purely from the dev split's gold `turn_program` / `executed_answers`
pairs: the relative-error tolerance a correctness check must use (0.1%, since exact float
equality against gold agrees on only 945/1486 numeric turns, while a 0.1% relative tolerance
gets full agreement), and the size of the "scale flip" ambiguity a metric must decide how to
handle (28% of numeric dev turns land in each of the (0, 1] and (1, 100] magnitude buckets,
i.e. answers commonly expressed interchangeably as a ratio or a percentage). Freezing these
here, against gold data only, means the metric is locked before session 1 ends, and a reviewer
can re-run this file to reproduce the derivation rather than trust a number in a report.
"""

import json
import re
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).parent.parent / "data" / "convfinqa_dataset.json"

RELATIVE_ERROR_TOLERANCE = 1e-3
EXPECTED_EXACT_MATCH_COUNT = 945
EXPECTED_NUMERIC_TURN_COUNT = 1486
EXPECTED_HIGH_PRECISION_GOLD_COUNT = 354
EXPECTED_SMALL_BUCKET_COUNT = 411
EXPECTED_MID_BUCKET_COUNT = 464
HIGH_PRECISION_DECIMAL_PLACES = 5
SMALL_BUCKET_UPPER_BOUND = 1
MID_BUCKET_UPPER_BOUND = 100


def _tokenize(prog: str) -> list[tuple[str, list[str]]]:
    """Split a DSL program string into (op, args) steps, or a single literal step."""
    if "(" not in prog:
        return [("literal", [prog.strip()])]
    steps = []
    for part in prog.split("), "):
        part = part.strip()
        if not part.endswith(")"):
            part += ")"
        match = re.match(r"(\w+)\((.*)\)$", part)
        assert match is not None, f"malformed program step: {part!r}"
        op, args = match.group(1), match.group(2)
        steps.append((op, [a.strip() for a in args.split(",")]))
    return steps


def _resolve(arg: str, results: list[float | str | None]) -> float | None:
    """Resolve one DSL argument to a float: a back-reference, a const_, or a literal number."""
    if arg.startswith("#"):
        referenced = results[int(arg[1:])]
        return referenced if isinstance(referenced, float) else None
    if arg.startswith("const_"):
        rest = arg[len("const_") :]
        sign = -1.0 if rest.startswith("m") else 1.0
        return sign * float(rest.lstrip("m"))
    is_pct = arg.endswith("%")
    try:
        value = float(arg.replace(",", "").rstrip("%"))
    except ValueError:
        return None
    return value / 100.0 if is_pct else value


def _execute(prog: str) -> float | str | None:
    """Execute a DSL program string and return its final numeric or yes/no result."""
    results: list[float | str | None] = []
    for op, args in _tokenize(prog):
        if op == "literal":
            results.append(_resolve(args[0], results))
            continue
        values = [_resolve(a, results) for a in args]
        if None in values:
            return None
        first, second = values[0], values[1]
        assert first is not None and second is not None
        if op == "add":
            results.append(first + second)
        elif op == "subtract":
            results.append(first - second)
        elif op == "multiply":
            results.append(first * second)
        elif op == "divide":
            results.append(first / second if second else None)
        elif op == "greater":
            results.append("yes" if first > second else "no")
        else:
            return None
    return results[-1] if results else None


def _dev_records() -> list[dict[str, Any]]:
    """Load the dev split of the ConvFinQA dataset."""
    data: dict[str, Any] = json.loads(DATA_PATH.read_text())
    dev_records: list[dict[str, Any]] = data["dev"]
    return dev_records


def _dev_turns() -> list[tuple[str, float | str]]:
    """Flatten every dev record's (program, gold answer) turn pairs."""
    turns = []
    for record in _dev_records():
        dialogue = record["dialogue"]
        turns.extend(zip(dialogue["turn_program"], dialogue["executed_answers"]))
    return turns


def test_dev_gold_replay_agrees_within_0_1_percent() -> None:
    """Executing every numeric dev turn agrees with gold within 0.1% relative error.

    Also documents how far off exact float equality is (945/1486), which is why a tolerance
    is required at all rather than an exact-match check.
    """
    exact_matches = 0
    numeric_turn_count = 0
    for prog, gold in _dev_turns():
        if isinstance(gold, str):
            continue
        numeric_turn_count += 1
        got = _execute(prog)
        assert isinstance(got, float), (
            f"non-numeric execution result for numeric gold: {prog!r}"
        )
        if got == gold:
            exact_matches += 1
        error = abs(got - gold) if gold == 0 else abs(got - gold) / abs(gold)
        assert error <= RELATIVE_ERROR_TOLERANCE, (
            f"{prog!r} executed to {got}, gold {gold}, relative error {error}"
        )

    assert numeric_turn_count == EXPECTED_NUMERIC_TURN_COUNT
    assert exact_matches == EXPECTED_EXACT_MATCH_COUNT


def test_yes_no_turns_are_never_coerced() -> None:
    """String-typed gold turns (`greater(...)` -> yes/no) execute to a matching string.

    The comparison is string equality throughout: gold is never coerced to or compared as a
    float for these turns.
    """
    string_turn_count = 0
    for prog, gold in _dev_turns():
        if not isinstance(gold, str):
            continue
        string_turn_count += 1
        got = _execute(prog)
        assert isinstance(got, str)
        assert got == gold

    assert string_turn_count == 4


def test_dev_gold_is_not_uniformly_rounded() -> None:
    """Gold values needing 5+ decimal places to represent exactly are common enough to require
    a relative-error tolerance rather than a fixed decimal-place rounding rule."""
    high_precision_count = 0
    for _, gold in _dev_turns():
        if isinstance(gold, str):
            continue
        text = repr(gold)
        if "." not in text or "e" in text:
            continue
        decimal_places = len(text.split(".")[1])
        if decimal_places >= HIGH_PRECISION_DECIMAL_PLACES:
            high_precision_count += 1

    assert high_precision_count == EXPECTED_HIGH_PRECISION_GOLD_COUNT


def test_scale_flip_bucket_size() -> None:
    """Size the scale-flip ambiguity: how many numeric dev gold values fall in (0, 1] versus
    (1, 100], the two magnitude bands where a ratio and a percentage are easily confused."""
    small_bucket_count = 0
    mid_bucket_count = 0
    for _, gold in _dev_turns():
        if isinstance(gold, str):
            continue
        magnitude = abs(gold)
        if 0 < magnitude <= SMALL_BUCKET_UPPER_BOUND:
            small_bucket_count += 1
        if SMALL_BUCKET_UPPER_BOUND < magnitude <= MID_BUCKET_UPPER_BOUND:
            mid_bucket_count += 1

    assert small_bucket_count == EXPECTED_SMALL_BUCKET_COUNT
    assert mid_bucket_count == EXPECTED_MID_BUCKET_COUNT
