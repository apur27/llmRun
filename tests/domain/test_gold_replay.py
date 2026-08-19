"""The self-validating harness: replay every dev `turn_program` through the real executor.

Executes all 1490 dev-split turns via `src.domain.executor.execute_program` (the production
executor, not the calibration-only copy in `tests/test_metric_calibration.py`) and asserts each
result agrees with `executed_answers`. This proves the executor and the loader are correct
against the real dataset, independent of any model call — 1490 gold points, zero API spend.

Comparison uses the frozen 1e-3 relative tolerance from `tests/test_metric_calibration.py`, not
exact equality: gold itself is stored at rounded, not full double, precision, so `==` only
agrees on 945/1486 numeric turns while the 1e-3 tolerance reaches full agreement (1486/1486).
The 4 `yes`/`no` turns (from `greater(...)`) compare by exact string equality and are never
coerced to float.
"""

from pathlib import Path

from src.domain.executor import execute_program
from src.domain.loader import load_dataset

DATA_PATH = Path(__file__).parent.parent.parent / "data" / "convfinqa_dataset.json"

RELATIVE_ERROR_TOLERANCE = 1e-3
EXPECTED_TOTAL_TURN_COUNT = 1490
EXPECTED_NUMERIC_TURN_COUNT = 1486
EXPECTED_STRING_TURN_COUNT = 4
MAX_EXAMPLE_FAILURES_SHOWN = 5


def _relative_error(computed: float, gold: float) -> float:
    """Relative error of `computed` against `gold`, falling back to absolute error at gold=0."""
    return abs(computed - gold) if gold == 0 else abs(computed - gold) / abs(gold)


def test_dev_gold_replay_agrees_with_executed_answers_within_tolerance() -> None:
    """Every one of the 1490 dev turn_programs, executed for real, agrees with gold.

    Numeric turns are compared within the frozen 1e-3 relative tolerance; the 4 yes/no turns
    by exact string equality. All 1490 turns are checked before asserting, so a real failure
    reports how many of 1490 failed and lists examples, rather than stopping at the first.
    """
    dataset = load_dataset(DATA_PATH)
    dev_records = dataset["dev"]

    numeric_turn_count = 0
    string_turn_count = 0
    failures: list[str] = []

    for record in dev_records:
        dialogue = record.dialogue
        for turn_index, (program, gold) in enumerate(
            zip(dialogue.turn_program, dialogue.executed_answers)
        ):
            computed = execute_program(program)
            if isinstance(gold, str):
                string_turn_count += 1
                if computed != gold:
                    failures.append(
                        f"record={record.id!r} turn={turn_index} program={program!r} "
                        f"computed={computed!r} gold={gold!r} (string mismatch)"
                    )
                continue

            numeric_turn_count += 1
            if not isinstance(computed, float):
                failures.append(
                    f"record={record.id!r} turn={turn_index} program={program!r} "
                    f"computed={computed!r} gold={gold!r} (non-numeric result for numeric gold)"
                )
                continue
            error = _relative_error(computed, gold)
            if error > RELATIVE_ERROR_TOLERANCE:
                failures.append(
                    f"record={record.id!r} turn={turn_index} program={program!r} "
                    f"computed={computed!r} gold={gold!r} (relative_error={error!r})"
                )

    total_turn_count = numeric_turn_count + string_turn_count

    if failures:
        examples = "\n".join(failures[:MAX_EXAMPLE_FAILURES_SHOWN])
        message = (
            f"{len(failures)} of {total_turn_count} dev turns failed the gold replay "
            f"(tolerance={RELATIVE_ERROR_TOLERANCE}):\n{examples}"
        )
        raise AssertionError(message)

    assert total_turn_count == EXPECTED_TOTAL_TURN_COUNT
    assert numeric_turn_count == EXPECTED_NUMERIC_TURN_COUNT
    assert string_turn_count == EXPECTED_STRING_TURN_COUNT
