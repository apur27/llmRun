"""Unit tests for the pure scoring primitive `src.domain.scorer.score_turn`.

Covers the four frozen metric decisions from the plan: the 1e-3 relative tolerance, strict vs
tolerant reported as two separate outcomes, yes/no answers scored by exact string equality and
never coerced to or from a float, and scale-flip flagged for diagnostics but never auto-corrected
to correct. The final test ties the scorer's scale-flip exposure to a frozen count (352) derived
directly from the real dev split, independent of the scorer implementation itself.
"""

import re
from pathlib import Path

from src.domain.loader import load_dataset
from src.domain.scorer import RELATIVE_ERROR_TOLERANCE, score_turn

DATA_PATH = Path(__file__).parent.parent.parent / "data" / "convfinqa_dataset.json"

EXPECTED_SCALE_FLIP_DIVIDE_EXPOSURE_COUNT = 352
SMALL_BUCKET_UPPER_BOUND = 1


def test_exact_match_is_both_strict_and_tolerant_correct() -> None:
    """An exactly-equal numeric prediction is correct under both strict and tolerant."""
    result = score_turn(35.8, 35.8)

    assert result.strict_correct is True
    assert result.tolerant_correct is True


def test_value_within_tolerance_but_not_exact_is_tolerant_only() -> None:
    """A prediction inside the 1e-3 relative tolerance but not exact is tolerant, not strict."""
    gold = 100.0
    predicted = gold * (1 + RELATIVE_ERROR_TOLERANCE / 2)

    result = score_turn(predicted, gold)

    assert result.strict_correct is False
    assert result.tolerant_correct is True


def test_value_outside_tolerance_is_neither_strict_nor_tolerant() -> None:
    """A prediction outside the 1e-3 relative tolerance fails both checks."""
    gold = 100.0
    predicted = gold * (1 + RELATIVE_ERROR_TOLERANCE * 10)

    result = score_turn(predicted, gold)

    assert result.strict_correct is False
    assert result.tolerant_correct is False


def test_yes_no_exact_match_is_correct() -> None:
    """A matching yes/no string prediction is correct under both strict and tolerant."""
    result = score_turn("yes", "yes")

    assert result.strict_correct is True
    assert result.tolerant_correct is True


def test_yes_no_mismatch_is_incorrect() -> None:
    """A mismatched yes/no string prediction is incorrect under both strict and tolerant."""
    result = score_turn("no", "yes")

    assert result.strict_correct is False
    assert result.tolerant_correct is False


def test_numeric_prediction_against_string_gold_is_never_coerced() -> None:
    """A float prediction against a string gold is incorrect, never string-formatted to compare."""
    result = score_turn(1.0, "yes")

    assert result.strict_correct is False
    assert result.tolerant_correct is False


def test_string_prediction_against_numeric_gold_is_never_coerced() -> None:
    """A string prediction against a numeric gold is incorrect, never float-parsed to compare."""
    result = score_turn("yes", 1.0)

    assert result.strict_correct is False
    assert result.tolerant_correct is False


def test_scale_flip_by_one_hundred_is_flagged_but_not_correct() -> None:
    """A prediction that is gold * 100 is flagged `scale_flip` but stays incorrect."""
    gold = 0.5
    predicted = gold * 100

    result = score_turn(predicted, gold)

    assert result.scale_flip is True
    assert result.tolerant_correct is False
    assert result.strict_correct is False


def test_scale_flip_by_one_over_one_hundred_is_flagged_but_not_correct() -> None:
    """A prediction that is gold / 100 is flagged `scale_flip` but stays incorrect."""
    gold = 50.0
    predicted = gold / 100

    result = score_turn(predicted, gold)

    assert result.scale_flip is True
    assert result.tolerant_correct is False
    assert result.strict_correct is False


def test_wrong_and_not_scale_flipped_prediction_is_not_flagged() -> None:
    """A prediction wrong by neither the tolerance nor a scale flip is not flagged."""
    result = score_turn(17.0, 5.0)

    assert result.scale_flip is False
    assert result.tolerant_correct is False


def _top_level_operation(program: str) -> str | None:
    """Return the DSL program's final (top-level) operation name, or `None` for a bare literal."""
    if "(" not in program:
        return None
    last_step = program.split("), ")[-1].strip()
    if not last_step.endswith(")"):
        last_step += ")"
    match = re.match(r"^(\w+)\(", last_step)
    return match.group(1) if match else None


def test_frozen_scale_flip_divide_exposure_count_on_real_dev_data() -> None:
    """The number of dev turns where scale-flip is even possible stays at the frozen count.

    Counts dev turns whose gold magnitude falls in (0, 1] and whose `turn_program`'s top-level
    operation is `divide` — the population where a ratio/percentage scale flip is plausible.
    This is a frozen exposure number from the plan, re-checked against the real data; a mismatch
    here is a discrepancy to report, not a number to adjust.
    """
    dataset = load_dataset(DATA_PATH)
    dev_records = dataset["dev"]

    exposure_count = 0
    for record in dev_records:
        dialogue = record.dialogue
        for program, gold in zip(
            dialogue.turn_program, dialogue.executed_answers, strict=True
        ):
            if isinstance(gold, str):
                continue
            if (
                0 < abs(gold) <= SMALL_BUCKET_UPPER_BOUND
                and _top_level_operation(program) == "divide"
            ):
                exposure_count += 1

    assert exposure_count == EXPECTED_SCALE_FLIP_DIVIDE_EXPOSURE_COUNT
