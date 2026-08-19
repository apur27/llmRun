"""Shared-contract test across all three `ModelClient` implementations.

The `ModelClient` Protocol only declares `answer(record, turn_index, turn_state) -> float | str`
-- it says nothing about *how* a client signals it cannot answer a turn. This asserts what each
implementation actually does on its own "cannot answer" case, rather than assuming they agree:
if they don't share one exception type, that divergence matters to `run_eval`, which only catches
`ProgramExecutionError`. A shared test is the assertion; a mismatch found here is the finding.
"""

from pathlib import Path

import pytest
from anthropic.types import Message, TextBlock, Usage

from src.adapters.anthropic_client import AnthropicClient
from src.adapters.fixture_client import FixtureClient, FixtureMissError
from src.adapters.response_cache import ResponseCache
from src.adapters.stub_client import STUB_SENTINEL, StubClient
from src.domain.executor import ProgramExecutionError
from src.domain.models import ConvFinQARecord, Dialogue, Document, Features
from src.services.turn_state import TurnState

_USAGE = Usage(input_tokens=1, output_tokens=1)


def _make_record() -> ConvFinQARecord:
    """One minimal, generic turn -- shared across all three clients' success-case check."""
    return ConvFinQARecord(
        id="Single_TEST/2020/page_1.pdf-1",
        doc=Document(pre_text="pre", post_text="post", table={"row": {"col": 1.0}}),
        dialogue=Dialogue(
            conv_questions=["what is the value?"],
            conv_answers=["1.0"],
            turn_program=["1.0"],
            executed_answers=[1.0],
            qa_split=[False],
        ),
        features=Features(
            num_dialogue_turns=1,
            has_type2_question=False,
            has_duplicate_columns=False,
            has_non_numeric_values=False,
        ),
    )


class _FakeAnthropicMessages:
    """Two unparseable replies in a row, so `AnthropicClient.answer` exhausts its one repair."""

    def __init__(self) -> None:
        self._texts = iter(["I think it's 5", "still no idea"])

    def create(self, **_kwargs: object) -> Message:
        return Message(
            id="msg",
            content=[TextBlock(text=next(self._texts), type="text")],
            model="claude-haiku-4-5-20251001",
            role="assistant",
            stop_reason="end_turn",
            stop_sequence=None,
            type="message",
            usage=_USAGE,
        )


class _FakeAnthropicSDK:
    def __init__(self) -> None:
        self.messages = _FakeAnthropicMessages()


def _anthropic_client_that_cannot_answer(tmp_path: Path) -> AnthropicClient:
    return AnthropicClient(_FakeAnthropicSDK(), ResponseCache(cache_dir=tmp_path))  # type: ignore[arg-type]


def _fixture_client_with_no_matching_entry(tmp_path: Path) -> FixtureClient:
    fixtures_path = tmp_path / "fixtures.json"
    fixtures_path.write_text(
        "{}"
    )  # deliberately empty: guarantees a miss on any lookup
    return FixtureClient(fixtures_path)


def test_stub_client_never_raises_on_any_turn() -> None:
    """`StubClient` has no failure mode by design -- always answers, always wrong."""
    result = StubClient().answer(_make_record(), 0, TurnState())

    assert result == STUB_SENTINEL


def test_fixture_client_raises_fixture_miss_error_on_an_unrecorded_turn(
    tmp_path: Path,
) -> None:
    """`FixtureClient` fails loud on a data-authoring gap -- `FixtureMissError`, not silent."""
    client = _fixture_client_with_no_matching_entry(tmp_path)

    with pytest.raises(FixtureMissError):
        client.answer(_make_record(), 0, TurnState())


def test_anthropic_client_raises_program_execution_error_when_it_cannot_answer(
    tmp_path: Path,
) -> None:
    """`AnthropicClient` fails via `ProgramExecutionError` -- the type `run_eval` catches."""
    client = _anthropic_client_that_cannot_answer(tmp_path)

    with pytest.raises(ProgramExecutionError):
        client.answer(_make_record(), 0, TurnState())


def test_the_three_clients_do_not_share_one_failure_exception_type(
    tmp_path: Path,
) -> None:
    """Documents the actual divergence, rather than leaving it discoverable only by reading.

    `run_eval` (`src/services/eval_runner.py`) catches only `ProgramExecutionError`. Today
    this is safe because `FixtureClient` -- whose own failure type, `FixtureMissError`, is
    NOT a `ProgramExecutionError` and would propagate uncaught out of `run_eval` -- is not
    wired into `main.py`'s `_build_client`, so `run_eval` never actually receives one in a
    real invocation. `StubClient` has no failure mode at all (always "succeeds," always
    wrong). If `FixtureClient` is ever wired into a real `run_eval` call, a single fixture
    miss partway through a run would crash the whole run uncaught, losing every already-
    scored turn -- `FixtureMissError`'s own docstring says this is deliberate ("intended to
    propagate ... until whoever authors the fixture file adds the missing entry"), which is
    defensible for an offline-replay tool authored against a known fixture set, but it is a
    real, asserted difference from how `AnthropicClient`'s failures are handled -- not an
    oversight to silently assume away.
    """
    with pytest.raises(FixtureMissError):
        _fixture_client_with_no_matching_entry(tmp_path).answer(
            _make_record(), 0, TurnState()
        )
    assert not issubclass(FixtureMissError, ProgramExecutionError)

    with pytest.raises(ProgramExecutionError):
        _anthropic_client_that_cannot_answer(tmp_path).answer(
            _make_record(), 0, TurnState()
        )
