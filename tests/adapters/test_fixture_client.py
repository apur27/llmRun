"""Unit tests for `src.adapters.fixture_client.FixtureClient`.

Uses the small hand-authored `tests/fixtures/anthropic_responses.json` file — plausible values
purely to prove the load/lookup/miss mechanism, never claimed as real model output.
"""

from pathlib import Path

import pytest

from src.adapters.fixture_client import FixtureClient, FixtureMissError
from src.domain.models import ConvFinQARecord, Dialogue, Document, Features
from src.services.turn_state import TurnState

FIXTURES_PATH = Path(__file__).parent.parent / "fixtures" / "anthropic_responses.json"


def _make_record(record_id: str, num_turns: int) -> ConvFinQARecord:
    """Build a minimal record with `num_turns` turns, distinguished only by `record_id`."""
    return ConvFinQARecord(
        id=record_id,
        doc=Document(pre_text="", post_text="", table={}),
        dialogue=Dialogue(
            conv_questions=["q"] * num_turns,
            conv_answers=["a"] * num_turns,
            turn_program=["1.0"] * num_turns,
            executed_answers=[1.0] * num_turns,
            qa_split=[False] * num_turns,
        ),
        features=Features(
            num_dialogue_turns=num_turns,
            has_type2_question=False,
            has_duplicate_columns=False,
            has_non_numeric_values=False,
        ),
    )


def test_fixture_client_returns_recorded_numeric_response(
    empty_turn_state: TurnState,
) -> None:
    """A `(record, turn_index)` present in the fixture file returns its recorded numeric value."""
    client = FixtureClient(FIXTURES_PATH)
    record = _make_record("Single_JKHY/2009/page_28.pdf-3", num_turns=2)

    assert client.answer(record, 0, empty_turn_state) == 9362.2
    assert client.answer(record, 1, empty_turn_state) == 9244.9


def test_fixture_client_returns_recorded_string_response(
    empty_turn_state: TurnState,
) -> None:
    """A `(record, turn_index)` recorded as a yes/no string returns that string unchanged."""
    client = FixtureClient(FIXTURES_PATH)
    record = _make_record("Single_RSG/2008/page_114.pdf-2", num_turns=1)

    assert client.answer(record, 0, empty_turn_state) == "yes"


def test_fixture_client_raises_on_a_miss_rather_than_falling_back(
    empty_turn_state: TurnState,
) -> None:
    """A `(record, turn_index)` absent from the fixture file raises, never a default or network."""
    client = FixtureClient(FIXTURES_PATH)
    record = _make_record("Single_NOT_IN_FIXTURES/2099/page_1.pdf-1", num_turns=1)

    with pytest.raises(FixtureMissError):
        client.answer(record, 0, empty_turn_state)
