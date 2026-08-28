"""Unit tests for `src.adapters.stub_client.StubClient`."""

from src.adapters.stub_client import STUB_SENTINEL, StubClient
from src.domain.models import ConvFinQARecord, Dialogue, Document, Features
from src.domain.scorer import SCALE_FLIP_FACTOR
from src.services.turn_state import TurnState


def _make_record() -> ConvFinQARecord:
    """Build a minimal hand-built record with one numeric turn and one yes/no turn."""
    return ConvFinQARecord(
        id="Single_TEST/2020/page_1.pdf-1",
        doc=Document(pre_text="", post_text="", table={}),
        dialogue=Dialogue(
            conv_questions=["what is x?", "is x greater than y?"],
            conv_answers=["1.0", "yes"],
            turn_program=["1.0", "greater(1, 0)"],
            executed_answers=[1.0, "yes"],
            qa_split=[False, False],
        ),
        features=Features(
            num_dialogue_turns=2,
            has_type2_question=False,
            has_duplicate_columns=False,
            has_non_numeric_values=False,
        ),
    )


def test_stub_client_returns_sentinel_for_numeric_turn(
    empty_turn_state: TurnState,
) -> None:
    """The stub always returns the sentinel string for a turn with a numeric gold."""
    client = StubClient()
    record = _make_record()

    assert client.answer(record, 0, empty_turn_state) == STUB_SENTINEL


def test_stub_client_returns_sentinel_for_yes_no_turn(
    empty_turn_state: TurnState,
) -> None:
    """The stub always returns the sentinel string for a turn with a yes/no gold."""
    client = StubClient()
    record = _make_record()

    assert client.answer(record, 1, empty_turn_state) == STUB_SENTINEL


def test_stub_client_sentinel_is_a_float_far_outside_any_gold_magnitude() -> None:
    """The sentinel is a float (so `TurnState` accepts it) but never matches a real gold value.

    It is far enough outside any ConvFinQA magnitude, including after a scale-flip by
    `SCALE_FLIP_FACTOR`, that it can never spuriously score correct.
    """
    assert isinstance(STUB_SENTINEL, float)
    assert abs(STUB_SENTINEL) > 1e6 * SCALE_FLIP_FACTOR
