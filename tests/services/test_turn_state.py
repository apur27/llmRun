"""Unit tests for `src.services.turn_state.TurnState`.

Pure state accumulation, no I/O, no SDK — every assertion is about order and content of the
turns held after a sequence of `add` calls.
"""

import pytest

from src.services.turn_state import Turn, TurnState


def test_new_turn_state_has_no_turns() -> None:
    """A freshly built `TurnState` starts with an empty turn list."""
    state = TurnState()

    assert state.turns == []


def test_add_appends_one_turn_with_question_and_answer() -> None:
    """`add` records the given question and answer as one `Turn`."""
    state = TurnState()

    state.add("what is x?", 9362.2)

    assert state.turns == [Turn(question="what is x?", answer=9362.2)]


def test_add_preserves_insertion_order_across_multiple_turns() -> None:
    """Turns accumulate in the order `add` was called, not sorted or reversed."""
    state = TurnState()

    state.add("first question?", 1.0)
    state.add("second question?", "yes")
    state.add("third question?", 3.5)

    assert state.turns == [
        Turn(question="first question?", answer=1.0),
        Turn(question="second question?", answer="yes"),
        Turn(question="third question?", answer=3.5),
    ]


def test_turn_state_holds_a_string_answer_unchanged() -> None:
    """A yes/no prior answer is stored as the exact string, not coerced."""
    state = TurnState()

    state.add("is x greater than y?", "no")

    assert state.turns[0].answer == "no"


def test_add_raises_value_error_on_a_malformed_answer() -> None:
    """An answer that is neither a float nor 'yes'/'no' cannot enter `TurnState`."""
    state = TurnState()

    with pytest.raises(ValueError, match="answer must be a float"):
        state.add("what is x?", "not a number")

    assert state.turns == []
