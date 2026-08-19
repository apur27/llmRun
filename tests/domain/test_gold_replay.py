"""The self-validating harness: replay every dev `turn_program` through the real executor.

Executes all 1490 dev-split turns via `src.domain.executor.execute_program` (the production
executor, not the calibration-only copy in `tests/test_metric_calibration.py`) and asserts each
result agrees with `executed_answers`. This proves the executor and the loader are correct
against the real dataset, independent of any model call — 1490 gold points, zero API spend.

Correctness is judged by `src.domain.scorer.score_turn` — the same production entrypoint the
eval runner will call on real predictions — not a second, hand-rolled comparison. Two
implementations that happen to agree today would drift silently tomorrow; this replay is only
evidence about the scorer if it calls the scorer. `tolerant_correct` is required for all 1490
turns (the frozen 1e-3 relative tolerance; gold is rounded-precision storage, so exact equality
alone only agrees on 945/1486 numeric turns).

A separate exact-equality (`==`) count is also tracked, deliberately outside `score_turn`: it is
not a correctness judgment (the scorer's own `strict_correct` already covers that, at a 1e-9
floor that legitimately forgives pure floating-point representation noise) but a canary on the
executor's raw output. It must stay at exactly 945/1486 numeric turns — tighter than
`strict_correct`'s 1115/1486 — so that any change to `execute_program` that quietly shifts a
computed value, even by less than the 1e-9 floor, is caught here even though both the tolerant
*and* the strict checks would keep passing.
"""

from pathlib import Path

from src.domain.executor import execute_program
from src.domain.loader import load_dataset
from src.domain.scorer import score_turn

DATA_PATH = Path(__file__).parent.parent.parent / "data" / "convfinqa_dataset.json"

EXPECTED_TOTAL_TURN_COUNT = 1490
EXPECTED_NUMERIC_TURN_COUNT = 1486
EXPECTED_STRING_TURN_COUNT = 4
EXPECTED_EXACT_MATCH_COUNT = 945
MAX_EXAMPLE_FAILURES_SHOWN = 5


def test_dev_gold_replay_agrees_with_executed_answers_within_tolerance() -> None:
    """Every one of the 1490 dev turn_programs, executed for real, scores tolerant-correct.

    Numeric and yes/no turns alike are judged by `score_turn(computed, gold)` — the same
    function real predictions will go through later. All 1490 turns are checked before
    asserting, so a real failure reports how many of 1490 failed and lists examples, rather
    than stopping at the first. The exact-match count is a canary (see module docstring): it
    is asserted separately, at the frozen value of 945/1486, so a silent executor drift is
    caught even though the tolerant (and strict) checks alone would keep passing.
    """
    dataset = load_dataset(DATA_PATH)
    dev_records = dataset["dev"]

    numeric_turn_count = 0
    string_turn_count = 0
    numeric_exact_match_count = 0
    failures: list[str] = []

    for record in dev_records:
        dialogue = record.dialogue
        for turn_index, (program, gold) in enumerate(
            zip(dialogue.turn_program, dialogue.executed_answers)
        ):
            computed = execute_program(program)
            if isinstance(gold, str):
                string_turn_count += 1
            else:
                numeric_turn_count += 1
                if computed == gold:
                    numeric_exact_match_count += 1

            result = score_turn(computed, gold)
            if not result.tolerant_correct:
                failures.append(
                    f"record={record.id!r} turn={turn_index} program={program!r} "
                    f"computed={computed!r} gold={gold!r}"
                )

    total_turn_count = numeric_turn_count + string_turn_count

    if failures:
        examples = "\n".join(failures[:MAX_EXAMPLE_FAILURES_SHOWN])
        message = (
            f"{len(failures)} of {total_turn_count} dev turns failed the gold replay "
            f"(score_turn.tolerant_correct is False):\n{examples}"
        )
        raise AssertionError(message)

    assert total_turn_count == EXPECTED_TOTAL_TURN_COUNT
    assert numeric_turn_count == EXPECTED_NUMERIC_TURN_COUNT
    assert string_turn_count == EXPECTED_STRING_TURN_COUNT
    assert numeric_exact_match_count == EXPECTED_EXACT_MATCH_COUNT
