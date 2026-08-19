"""Unit tests for `src.services.eval_runner.run_eval`.

Uses small hand-built fake clients (never a mock of `src.domain.scorer`, which is the real thing
under test transitively) to control exactly which turns are answered correctly, so the summary's
counts and accuracies can be checked against a hand-computed expectation.
"""

import pytest

from src.domain.models import ConvFinQARecord, Dialogue, Document, Features
from src.services.eval_runner import TurnCountMismatchError, run_eval

_WRONG_ANSWER = "__WRONG__"


def _make_record(
    turn_program: list[str], executed_answers: list[float | str]
) -> ConvFinQARecord:
    """Build a minimal record whose turns are only distinguished by program/gold length."""
    num_turns = len(turn_program)
    return ConvFinQARecord(
        id="Single_TEST/2020/page_1.pdf-1",
        doc=Document(pre_text="", post_text="", table={}),
        dialogue=Dialogue(
            conv_questions=["q"] * num_turns,
            conv_answers=[str(a) for a in executed_answers],
            turn_program=turn_program,
            executed_answers=executed_answers,
            qa_split=[False] * num_turns,
        ),
        features=Features(
            num_dialogue_turns=num_turns,
            has_type2_question=False,
            has_duplicate_columns=False,
            has_non_numeric_values=False,
        ),
    )


class _AlwaysCorrectClient:
    """Fake client returning the gold value for every turn."""

    def answer(self, record: ConvFinQARecord, turn_index: int) -> float | str:
        """Return the gold answer for `turn_index`, always scoring correct."""
        return record.dialogue.executed_answers[turn_index]


class _AlwaysWrongClient:
    """Fake client returning a fixed wrong value for every turn."""

    def answer(self, record: ConvFinQARecord, turn_index: int) -> float | str:
        """Ignore the record and always return a value that cannot match any gold."""
        return _WRONG_ANSWER


class _FirstTurnCorrectClient:
    """Fake client correct only on the first turn of each record."""

    def answer(self, record: ConvFinQARecord, turn_index: int) -> float | str:
        """Return the gold on turn 0, and a wrong value on every later turn."""
        if turn_index == 0:
            return record.dialogue.executed_answers[turn_index]
        return _WRONG_ANSWER


def test_run_eval_with_always_correct_client_is_fully_accurate() -> None:
    """When every prediction matches gold, both accuracies are 1.0 and all turns are counted."""
    records = [
        _make_record(["1.0", "greater(1, 0)"], [1.0, "yes"]),
        _make_record(["2.0"], [2.0]),
    ]

    summary = run_eval(records, _AlwaysCorrectClient())

    assert summary.total_turns == 3
    assert summary.strict_correct == 3
    assert summary.tolerant_correct == 3
    assert summary.strict_accuracy == 1.0
    assert summary.tolerant_accuracy == 1.0


def test_run_eval_with_always_wrong_client_is_zero_accuracy() -> None:
    """When no prediction ever matches gold, both accuracies are 0.0."""
    records = [
        _make_record(["1.0", "greater(1, 0)"], [1.0, "yes"]),
        _make_record(["2.0"], [2.0]),
    ]

    summary = run_eval(records, _AlwaysWrongClient())

    assert summary.total_turns == 3
    assert summary.strict_correct == 0
    assert summary.tolerant_correct == 0
    assert summary.strict_accuracy == 0.0
    assert summary.tolerant_accuracy == 0.0


def test_run_eval_with_mixed_client_counts_partial_correctness() -> None:
    """A client correct on some turns and wrong on others produces a matching partial accuracy."""
    records = [
        _make_record(["1.0", "greater(1, 0)"], [1.0, "yes"]),
        _make_record(["2.0", "3.0"], [2.0, 3.0]),
    ]

    summary = run_eval(records, _FirstTurnCorrectClient())

    assert summary.total_turns == 4
    assert summary.strict_correct == 2
    assert summary.tolerant_correct == 2
    assert summary.strict_accuracy == 0.5
    assert summary.tolerant_accuracy == 0.5


def test_run_eval_raises_on_turn_count_mismatch() -> None:
    """A record whose `executed_answers` is shorter than its `turn_program` raises, not shrinks.

    `turn_program` has 3 entries but `executed_answers` has only 2 — a malformed record that
    should never come from `load_dataset`, but is a real failure mode the assertion exists to
    catch rather than silently truncate the denominator to whatever `executed_answers` supplies.
    """
    record = _make_record(["1.0", "2.0", "3.0"], [1.0, 2.0])

    with pytest.raises(TurnCountMismatchError):
        run_eval([record], _AlwaysWrongClient())
