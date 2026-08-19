"""Unit tests for the minimal per-turn results record `src.domain.results.TurnResult`.

Covers construction only: a correct turn (`reason="ok"`), an incorrect turn
(`reason="wrong_value"`), and a scale-flip turn where `scale_flip` is `True` but the outcome is
still `"incorrect"` — scale-flip is a diagnostic flag, never elevated to correct.
"""

from src.domain.results import TurnResult


def test_correct_turn_has_ok_reason_and_correct_outcome() -> None:
    """A turn scored correct records `outcome="correct"` and `reason="ok"`."""
    result = TurnResult(
        record_id="Single_TEST/2020/page_1.pdf-1",
        turn_index=0,
        turn_program="add(1, 2)",
        gold=3.0,
        predicted=3.0,
        outcome="correct",
        reason="ok",
        scale_flip=False,
    )

    assert result.outcome == "correct"
    assert result.reason == "ok"
    assert result.scale_flip is False


def test_incorrect_turn_has_wrong_value_reason() -> None:
    """A turn scored incorrect records `outcome="incorrect"` and `reason="wrong_value"`."""
    result = TurnResult(
        record_id="Single_TEST/2020/page_1.pdf-1",
        turn_index=1,
        turn_program="subtract(5, 2)",
        gold=3.0,
        predicted=99.0,
        outcome="incorrect",
        reason="wrong_value",
        scale_flip=False,
    )

    assert result.outcome == "incorrect"
    assert result.reason == "wrong_value"


def test_scale_flip_turn_is_still_incorrect() -> None:
    """A scale-flip prediction carries `scale_flip=True` but is never elevated to correct."""
    result = TurnResult(
        record_id="Single_TEST/2020/page_1.pdf-1",
        turn_index=2,
        turn_program="divide(1, 4)",
        gold=0.25,
        predicted=25.0,
        outcome="incorrect",
        reason="wrong_value",
        scale_flip=True,
    )

    assert result.scale_flip is True
    assert result.outcome == "incorrect"
