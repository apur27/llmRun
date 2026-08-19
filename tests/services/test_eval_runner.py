"""Unit tests for `src.services.eval_runner.run_eval`.

Uses small hand-built fake clients (never a mock of `src.domain.scorer`, which is the real thing
under test transitively) to control exactly which turns are answered correctly, so the summary's
counts and accuracies can be checked against a hand-computed expectation.
"""

import pytest

from src.domain.executor import ProgramExecutionError
from src.domain.models import ConvFinQARecord, Dialogue, Document, Features
from src.domain.results import TurnResult
from src.services.eval_runner import TurnCountMismatchError, run_eval
from src.services.turn_state import TurnState

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

    def answer(
        self, record: ConvFinQARecord, turn_index: int, turn_state: TurnState
    ) -> float | str:
        """Return the gold answer for `turn_index`, always scoring correct."""
        return record.dialogue.executed_answers[turn_index]


class _AlwaysWrongClient:
    """Fake client returning a fixed wrong value for every turn."""

    def answer(
        self, record: ConvFinQARecord, turn_index: int, turn_state: TurnState
    ) -> float | str:
        """Ignore the record and always return a value that cannot match any gold."""
        return _WRONG_ANSWER


class _FirstTurnCorrectClient:
    """Fake client correct only on the first turn of each record."""

    def answer(
        self, record: ConvFinQARecord, turn_index: int, turn_state: TurnState
    ) -> float | str:
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


def test_run_eval_populates_turn_results_matching_expected_per_turn_records() -> None:
    """`run_eval`'s summary carries one `TurnResult` per turn, matching hand-computed fields."""
    records = [_make_record(["1.0", "greater(1, 0)"], [1.0, "yes"])]

    summary = run_eval(records, _FirstTurnCorrectClient())

    assert summary.turn_results == [
        TurnResult(
            record_id="Single_TEST/2020/page_1.pdf-1",
            turn_index=0,
            turn_program="1.0",
            gold=1.0,
            predicted=1.0,
            outcome="correct",
            reason="ok",
            scale_flip=False,
        ),
        TurnResult(
            record_id="Single_TEST/2020/page_1.pdf-1",
            turn_index=1,
            turn_program="greater(1, 0)",
            gold="yes",
            predicted=_WRONG_ANSWER,
            outcome="incorrect",
            reason="wrong_value",
            scale_flip=False,
        ),
    ]


class _RaisesOnSecondTurnClient:
    """Fake client correct on turn 0, raises `ProgramExecutionError` on turn 1, correct after."""

    def answer(
        self, record: ConvFinQARecord, turn_index: int, turn_state: TurnState
    ) -> float | str:
        """Raise on turn 1, otherwise return the gold answer for `turn_index`."""
        if turn_index == 1:
            raise ProgramExecutionError("could not parse a final answer")
        return record.dialogue.executed_answers[turn_index]


def test_run_eval_catches_program_execution_error_as_parse_error() -> None:
    """A turn whose client raises `ProgramExecutionError` scores `parse_error`, not a crash.

    The rest of the batch still completes: turns 0 and 2 are answered correctly by the same fake
    client, proving the catch does not abort the loop for later turns or later records.
    """
    record = _make_record(["1.0", "2.0", "3.0"], [1.0, 2.0, 3.0])

    summary = run_eval([record], _RaisesOnSecondTurnClient())

    assert summary.total_turns == 3
    assert summary.tolerant_correct == 2
    failed_turn = summary.turn_results[1]
    assert failed_turn.outcome == "incorrect"
    assert failed_turn.reason == "parse_error"
    assert failed_turn.predicted is None


class _UsageTrackingClient:
    """Fake client exposing cumulative usage attributes, matching `AnthropicClient`'s shape."""

    def __init__(self) -> None:
        """Set fixed, non-zero cumulative usage as if calls had already been made."""
        self.cumulative_input_tokens = 300
        self.cumulative_output_tokens = 40
        self.cumulative_cache_creation_tokens = 500
        self.cumulative_cache_read_tokens = 1000

    def answer(
        self, record: ConvFinQARecord, turn_index: int, turn_state: TurnState
    ) -> float | str:
        """Return the gold answer for `turn_index`, always scoring correct."""
        return record.dialogue.executed_answers[turn_index]


def test_run_eval_puts_cumulative_usage_on_summary() -> None:
    """`run_eval` reads the client's cumulative usage after the loop and puts it on the summary.

    Dollar cost is deliberately not asserted here — converting these token counts to cost is
    `estimate_cost_usd`'s job in `src/adapters/anthropic_client.py`, exercised by that module's
    own tests, not `EvalSummary`'s.
    """
    records = [_make_record(["1.0"], [1.0])]

    summary = run_eval(records, _UsageTrackingClient())

    assert summary.cumulative_input_tokens == 300
    assert summary.cumulative_output_tokens == 40
    assert summary.cumulative_cache_creation_tokens == 500
    assert summary.cumulative_cache_read_tokens == 1000


def test_run_eval_defaults_usage_to_zero_for_a_client_without_usage_attributes() -> (
    None
):
    """A client with no cumulative usage attributes (e.g. `StubClient`) scores zero usage."""
    records = [_make_record(["1.0"], [1.0])]

    summary = run_eval(records, _AlwaysCorrectClient())

    assert summary.cumulative_input_tokens == 0
    assert summary.cumulative_output_tokens == 0
    assert summary.cumulative_cache_creation_tokens == 0
    assert summary.cumulative_cache_read_tokens == 0


class _TurnStateRecordingClient:
    """Fake client that snapshots the `turn_state` it was called with, per `(record.id, turn)`."""

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.seen: dict[tuple[str, int], list[str]] = {}

    def answer(
        self, record: ConvFinQARecord, turn_index: int, turn_state: TurnState
    ) -> float | str:
        """Record the questions already in `turn_state` at call time, then answer correctly."""
        self.seen[(record.id, turn_index)] = [
            turn.question for turn in turn_state.turns
        ]
        return record.dialogue.executed_answers[turn_index]


def test_run_eval_builds_a_fresh_turn_state_per_record() -> None:
    """A second record's `TurnState` never carries turns from the first record.

    Two two-turn records, both answered correctly: by the time record B's turns are answered,
    a `TurnState` leaking across records would show B's turn 0 already containing A's turns.
    """
    record_a = _make_record(["1.0", "2.0"], [1.0, 2.0])
    record_a = record_a.model_copy(update={"id": "Single_A/2020/page_1.pdf-1"})
    record_b = _make_record(["3.0", "4.0"], [3.0, 4.0])
    record_b = record_b.model_copy(update={"id": "Single_B/2020/page_1.pdf-1"})
    client = _TurnStateRecordingClient()

    run_eval([record_a, record_b], client)

    assert client.seen[("Single_A/2020/page_1.pdf-1", 0)] == []
    assert client.seen[("Single_A/2020/page_1.pdf-1", 1)] == ["q"]
    assert client.seen[("Single_B/2020/page_1.pdf-1", 0)] == []
    assert client.seen[("Single_B/2020/page_1.pdf-1", 1)] == ["q"]


class _WrongFirstTurnRecordingClient:
    """Fake client wrong on turn 0, then records the `turn_state` it sees on turn 1."""

    def __init__(self) -> None:
        """Start with no recorded turn-1 history."""
        self.turn_one_history: list[tuple[str, float | str]] = []

    def answer(
        self, record: ConvFinQARecord, turn_index: int, turn_state: TurnState
    ) -> float | str:
        """Answer wrong on turn 0; on turn 1, snapshot `turn_state` before answering correctly."""
        if turn_index == 1:
            self.turn_one_history = [
                (turn.question, turn.answer) for turn in turn_state.turns
            ]
            return record.dialogue.executed_answers[turn_index]
        return _WRONG_ANSWER


def test_run_eval_appends_the_predicted_answer_not_gold_to_turn_state() -> None:
    """A wrong prediction on turn 0 is what turn 1's `TurnState` sees, not the gold answer.

    Mirrors real deployment: the model never sees gold, only what it itself answered.
    """
    record = _make_record(["1.0", "2.0"], [1.0, 2.0])
    client = _WrongFirstTurnRecordingClient()

    run_eval([record], client)

    assert client.turn_one_history == [("q", _WRONG_ANSWER)]


def test_run_eval_raises_on_turn_count_mismatch() -> None:
    """A record whose `executed_answers` is shorter than its `turn_program` raises, not shrinks.

    `turn_program` has 3 entries but `executed_answers` has only 2 — a malformed record that
    should never come from `load_dataset`, but is a real failure mode the assertion exists to
    catch rather than silently truncate the denominator to whatever `executed_answers` supplies.
    """
    record = _make_record(["1.0", "2.0", "3.0"], [1.0, 2.0])

    with pytest.raises(TurnCountMismatchError):
        run_eval([record], _AlwaysWrongClient())
