"""Unit tests for `src.adapters.anthropic_client.AnthropicClient`.

No real network call: the `anthropic.Anthropic` SDK boundary is stubbed by a fake object whose
`.messages.create` returns hand-built (real) `anthropic.types.Message` objects queued in advance
— the SDK's own response types, so `isinstance` checks and `.model_dump()` inside the adapter
behave exactly as they would against a real response. `ProgramExecutionError` (divide-by-zero,
iteration cap, unparseable answer) is asserted the same way `src/domain/executor.py`'s own tests
assert it: by actually driving the code down that path, never by mocking the error type itself.
"""

from pathlib import Path
from typing import Any

import anthropic
import httpx
import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

import src.adapters.anthropic_client as anthropic_client_module
from src.adapters.anthropic_client import (
    CACHE_READ_TOKEN_RATE_USD,
    INPUT_TOKEN_RATE_USD,
    MAX_RETRIES,
    OUTPUT_TOKEN_RATE_USD,
    AnthropicClient,
    MissingApiKeyError,
    estimate_cost_usd,
)
from src.adapters.ports import ProviderError
from src.adapters.response_cache import ResponseCache
from src.domain.executor import ProgramExecutionError
from src.domain.models import ConvFinQARecord, Dialogue, Document, Features
from src.services.turn_state import TurnState

_USAGE = Usage(input_tokens=1, output_tokens=1)


def _rate_limit_error() -> anthropic.RateLimitError:
    """A real `RateLimitError` (429), shaped exactly as the SDK would raise it."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(429, request=request)
    return anthropic.RateLimitError("rate limited", response=response, body=None)


def _internal_server_error() -> anthropic.InternalServerError:
    """A real `InternalServerError` (500), shaped exactly as the SDK would raise it."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(500, request=request)
    return anthropic.InternalServerError("server error", response=response, body=None)


def _bad_request_error() -> anthropic.BadRequestError:
    """A real, non-retryable `BadRequestError` (400)."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(400, request=request)
    return anthropic.BadRequestError("bad request", response=response, body=None)


def _make_record(question: str = "what is the value?") -> ConvFinQARecord:
    """Build a minimal one-turn record with a table, for prompt-building purposes."""
    return ConvFinQARecord(
        id="Single_TEST/2020/page_1.pdf-1",
        doc=Document(pre_text="pre", post_text="post", table={"row": {"col": 1.0}}),
        dialogue=Dialogue(
            conv_questions=[question],
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


def _text_message(text: str, usage: Usage = _USAGE) -> Message:
    """A final `end_turn` message carrying one text block."""
    return Message(
        id="msg",
        content=[TextBlock(text=text, type="text")],
        model="claude-haiku-4-5-20251001",
        role="assistant",
        stop_reason="end_turn",
        stop_sequence=None,
        type="message",
        usage=usage,
    )


def _tool_use_message(
    tool_use_id: str,
    operation: str,
    first: float,
    second: float,
    usage: Usage = _USAGE,
) -> Message:
    """A `tool_use` message calling `calculate` once."""
    return Message(
        id="msg",
        content=[
            ToolUseBlock(
                id=tool_use_id,
                input={"operation": operation, "first": first, "second": second},
                name="calculate",
                type="tool_use",
            )
        ],
        model="claude-haiku-4-5-20251001",
        role="assistant",
        stop_reason="tool_use",
        stop_sequence=None,
        type="message",
        usage=usage,
    )


class _FakeMessages:
    """Stand-in for `anthropic.Anthropic().messages`, returning queued responses in order.

    A queued item may be an `Exception` instance instead of a `Message` — `create` raises it
    rather than returning it, so retry behaviour can be driven the same way a real transient
    failure would.
    """

    def __init__(self, responses: list[Message | Exception]) -> None:
        """Queue `responses`, returned (or raised) one per `create` call, in order."""
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Message:
        """Record a snapshot of the call and return (or raise) the next queued item.

        `kwargs["messages"]` is the caller's own mutable list, appended to further after this
        call returns — a shallow copy is recorded so a later assertion sees the call as it was
        made, not as the list looks once the whole tool loop has finished mutating it.
        """
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        if not self._responses:
            raise AssertionError("no more fake responses queued")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeAnthropic:
    """Stand-in for `anthropic.Anthropic`, exposing only the `.messages.create` boundary used."""

    def __init__(self, responses: list[Message | Exception]) -> None:
        """Wrap a `_FakeMessages` queue behind the same `.messages` attribute path."""
        self.messages = _FakeMessages(responses)


def _client_with(
    responses: list[Message | Exception], cache_dir: Path
) -> AnthropicClient:
    """Build an `AnthropicClient` over a fake SDK client and a `tmp_path`-backed cache."""
    fake = _FakeAnthropic(responses)
    return AnthropicClient(fake, ResponseCache(cache_dir=cache_dir))  # type: ignore[arg-type]


def test_from_env_raises_missing_api_key_error_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`from_env` raises `MissingApiKeyError`, not a `KeyError`, when the env var is unset."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(MissingApiKeyError):
        AnthropicClient.from_env()


def test_from_env_writes_the_variable_name_to_stderr_when_unset(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The stderr line names `ANTHROPIC_API_KEY` explicitly, for a stranger's first run."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(MissingApiKeyError):
        AnthropicClient.from_env()

    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_answer_returns_parsed_float_from_final_text(tmp_path: Path) -> None:
    """A final `ANSWER: <value>` text response parses to the matching float."""
    client = _client_with(
        [_text_message("the value is 9362.2\nANSWER: 9362.2")], tmp_path
    )

    assert client.answer(_make_record(), 0, TurnState()) == 9362.2


def test_answer_returns_parsed_yes_no_string(tmp_path: Path) -> None:
    """A final `ANSWER: yes` text response parses to the string `"yes"`, not a float."""
    client = _client_with([_text_message("ANSWER: yes")], tmp_path)

    assert client.answer(_make_record(), 0, TurnState()) == "yes"


def test_answer_executes_calculator_tool_call_via_the_domain_executor(
    tmp_path: Path,
) -> None:
    """A `calculate` tool call is routed through `execute_program`, matching its arithmetic."""
    client = _client_with(
        [
            _tool_use_message("tu1", "add", 2, 3),
            _text_message("ANSWER: 5.0"),
        ],
        tmp_path,
    )

    result = client.answer(_make_record(), 0, TurnState())

    assert result == 5.0


def test_answer_returns_executor_error_as_tool_result_text_not_a_crash(
    tmp_path: Path,
) -> None:
    """A tool call that would divide by zero returns the executor's error as tool result text."""
    client = _client_with(
        [
            _tool_use_message("tu1", "divide", 1, 0),
            _text_message("ANSWER: 0.0"),
        ],
        tmp_path,
    )

    result = client.answer(_make_record(), 0, TurnState())

    assert result == 0.0
    second_call_messages = client._client.messages.calls[1]["messages"]  # type: ignore[attr-defined]
    tool_result_content = second_call_messages[-1]["content"][0]
    assert tool_result_content["is_error"] is True


def test_answer_raises_program_execution_error_past_the_iteration_cap(
    tmp_path: Path,
) -> None:
    """A model that never stops calling tools raises `ProgramExecutionError`, not a hang."""
    always_tool_use = [_tool_use_message(f"tu{i}", "add", 1, 1) for i in range(10)]
    client = _client_with(always_tool_use, tmp_path)

    with pytest.raises(ProgramExecutionError):
        client.answer(_make_record(), 0, TurnState())


def test_answer_repairs_once_on_unparseable_final_text(tmp_path: Path) -> None:
    """An unparseable final reply triggers one repair round-trip, then succeeds."""
    client = _client_with(
        [_text_message("I think it's 5"), _text_message("ANSWER: 5.0")],
        tmp_path,
    )

    assert client.answer(_make_record(), 0, TurnState()) == 5.0


def test_answer_raises_program_execution_error_after_repair_also_fails(
    tmp_path: Path,
) -> None:
    """Two unparseable replies in a row raise `ProgramExecutionError`, not a third attempt."""
    client = _client_with(
        [_text_message("I think it's 5"), _text_message("still no idea")],
        tmp_path,
    )

    with pytest.raises(ProgramExecutionError):
        client.answer(_make_record(), 0, TurnState())


def test_answer_uses_the_response_cache_on_a_repeat_prompt(tmp_path: Path) -> None:
    """A prompt already in the cache never calls the SDK a second time."""
    client = _client_with([_text_message("ANSWER: 7.0")], tmp_path)
    record = _make_record()

    first = client.answer(record, 0, TurnState())
    second = client.answer(record, 0, TurnState())

    assert first == second == 7.0
    assert len(client._client.messages.calls) == 1  # type: ignore[attr-defined]


def test_new_client_has_zero_cumulative_usage(tmp_path: Path) -> None:
    """A freshly built client reports zero cumulative usage before any call is made."""
    client = _client_with([], tmp_path)

    assert client.cumulative_input_tokens == 0
    assert client.cumulative_output_tokens == 0
    assert client.cumulative_cache_creation_tokens == 0
    assert client.cumulative_cache_read_tokens == 0


def test_answer_accumulates_input_and_output_tokens_from_response_usage(
    tmp_path: Path,
) -> None:
    """One real call's `response.usage` is added onto the client's cumulative totals."""
    usage = Usage(input_tokens=100, output_tokens=20)
    client = _client_with([_text_message("ANSWER: 1.0", usage=usage)], tmp_path)

    client.answer(_make_record(), 0, TurnState())

    assert client.cumulative_input_tokens == 100
    assert client.cumulative_output_tokens == 20


def test_answer_accumulates_usage_across_multiple_answer_calls(
    tmp_path: Path,
) -> None:
    """Two separate `answer()` calls (distinct prompts) sum their usage, not overwrite it."""
    client = _client_with(
        [
            _text_message("ANSWER: 1.0", usage=Usage(input_tokens=10, output_tokens=1)),
            _text_message("ANSWER: 2.0", usage=Usage(input_tokens=30, output_tokens=2)),
        ],
        tmp_path,
    )

    client.answer(_make_record("first question?"), 0, TurnState())
    client.answer(_make_record("second question?"), 0, TurnState())

    assert client.cumulative_input_tokens == 40
    assert client.cumulative_output_tokens == 3


def test_answer_accumulates_usage_across_tool_loop_iterations(tmp_path: Path) -> None:
    """A single `answer()` spanning two tool-loop iterations sums usage from both calls."""
    client = _client_with(
        [
            _tool_use_message(
                "tu1", "add", 2, 3, usage=Usage(input_tokens=50, output_tokens=5)
            ),
            _text_message("ANSWER: 5.0", usage=Usage(input_tokens=60, output_tokens=8)),
        ],
        tmp_path,
    )

    client.answer(_make_record(), 0, TurnState())

    assert client.cumulative_input_tokens == 110
    assert client.cumulative_output_tokens == 13


def test_answer_accumulates_cache_creation_and_read_tokens_when_present(
    tmp_path: Path,
) -> None:
    """`cache_creation_input_tokens`/`cache_read_input_tokens` accumulate when the SDK sets them."""
    usage = Usage(
        input_tokens=10,
        output_tokens=1,
        cache_creation_input_tokens=500,
        cache_read_input_tokens=200,
    )
    client = _client_with([_text_message("ANSWER: 1.0", usage=usage)], tmp_path)

    client.answer(_make_record(), 0, TurnState())

    assert client.cumulative_cache_creation_tokens == 500
    assert client.cumulative_cache_read_tokens == 200


def test_answer_treats_absent_cache_fields_as_zero_not_none(tmp_path: Path) -> None:
    """`Usage` with no cache fields set (plain `_USAGE`) accumulates zero, never `None`."""
    client = _client_with([_text_message("ANSWER: 1.0")], tmp_path)

    client.answer(_make_record(), 0, TurnState())

    assert client.cumulative_cache_creation_tokens == 0
    assert client.cumulative_cache_read_tokens == 0


def test_estimate_cost_usd_computes_from_pinned_rates() -> None:
    """`estimate_cost_usd` multiplies each token count by its own pinned rate and sums them."""
    cost = estimate_cost_usd(
        input_tokens=1000,
        output_tokens=100,
        cache_creation_tokens=0,
        cache_read_tokens=2000,
    )

    expected = (
        1000 * INPUT_TOKEN_RATE_USD
        + 100 * OUTPUT_TOKEN_RATE_USD
        + 2000 * CACHE_READ_TOKEN_RATE_USD
    )
    assert cost == pytest.approx(expected)


def test_estimate_cost_usd_is_zero_for_zero_tokens() -> None:
    """No tokens spent means no estimated cost."""
    assert estimate_cost_usd(0, 0, 0, 0) == 0.0


def test_different_system_instructions_produce_different_cache_entries(
    tmp_path: Path,
) -> None:
    """Two `system_instructions` variants for the same record/question must not collide.

    Guards the bug found reading this module ahead of the percentage-convention A/B: if the
    cache key were still built from the module-level constant rather than the instance's own
    `system_instructions`, both clients below would hash to the same cache file and the second
    variant would silently replay the first variant's cached answer.
    """
    fake_a = _FakeAnthropic([_text_message("ANSWER: 1.0")])
    fake_b = _FakeAnthropic([_text_message("ANSWER: 2.0")])
    client_a = AnthropicClient(
        fake_a, ResponseCache(cache_dir=tmp_path), system_instructions="Variant A."
    )
    client_b = AnthropicClient(
        fake_b, ResponseCache(cache_dir=tmp_path), system_instructions="Variant B."
    )
    record = _make_record()

    result_a = client_a.answer(record, 0, TurnState())
    result_b = client_b.answer(record, 0, TurnState())

    assert result_a == 1.0
    assert result_b == 2.0
    assert len(fake_a.messages.calls) == 1
    assert len(fake_b.messages.calls) == 1
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_answer_sends_prior_turns_as_real_conversation_history(tmp_path: Path) -> None:
    """Prior turns from `TurnState` appear as real `user`/`assistant` messages, in order.

    Inspects the actual `messages` list handed to the fake SDK, not just that `answer` runs
    without error — the whole point of `TurnState` is that a later turn's client can see an
    earlier turn's question and the model's own recorded answer.
    """
    client = _client_with([_text_message("ANSWER: 117.3")], tmp_path)
    turn_state = TurnState()
    turn_state.add("what was the value in 2007?", 9362.2)
    turn_state.add("what was it in 2008?", 9244.9)

    client.answer(_make_record("what was that in 2009?"), 0, turn_state)

    sent_messages = client._client.messages.calls[0]["messages"]  # type: ignore[attr-defined]
    assert sent_messages == [
        {"role": "user", "content": "what was the value in 2007?"},
        {"role": "assistant", "content": "ANSWER: 9362.2"},
        {"role": "user", "content": "what was it in 2008?"},
        {"role": "assistant", "content": "ANSWER: 9244.9"},
        {"role": "user", "content": "what was that in 2009?"},
    ]


def test_answer_with_different_turn_state_history_does_not_hit_the_same_cache_entry(
    tmp_path: Path,
) -> None:
    """Two different prior-turn histories for the same question must not share a cache entry.

    If the cache key ignored `turn_state`, the second call below would replay the first call's
    cached answer instead of making its own (distinct, queued) SDK call.
    """
    client = _client_with(
        [_text_message("ANSWER: 1.0"), _text_message("ANSWER: 2.0")], tmp_path
    )
    record = _make_record("what about that?")
    history_a = TurnState()
    history_a.add("q1?", 10.0)
    history_b = TurnState()
    history_b.add("q1?", 20.0)

    result_a = client.answer(record, 0, history_a)
    result_b = client.answer(record, 0, history_b)

    assert result_a == 1.0
    assert result_b == 2.0
    assert len(client._client.messages.calls) == 2  # type: ignore[attr-defined]


def test_answer_is_identical_with_and_without_retry_wrapper_on_first_try_success(
    tmp_path: Path,
) -> None:
    """A turn that succeeds on the first call is unaffected by the retry wrapper: same result,
    exactly one SDK call, no sleep. Proves retry is invisible on the success path -- it must
    never alter an answer that would have succeeded without it."""
    client = _client_with([_text_message("ANSWER: 42.0")], tmp_path)

    result = client.answer(_make_record(), 0, TurnState())

    assert result == 42.0
    assert len(client._client.messages.calls) == 1  # type: ignore[attr-defined]


def test_answer_retries_once_after_a_retryable_error_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rate-limit error on the first call is retried, and the second call's answer wins."""
    monkeypatch.setattr(anthropic_client_module.time, "sleep", lambda s: None)
    client = _client_with([_rate_limit_error(), _text_message("ANSWER: 5.0")], tmp_path)

    result = client.answer(_make_record(), 0, TurnState())

    assert result == 5.0
    assert len(client._client.messages.calls) == 2  # type: ignore[attr-defined]


def test_answer_raises_provider_error_after_retries_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retryable errors on every attempt up to `MAX_RETRIES` raise `ProviderError`, not hang."""
    monkeypatch.setattr(anthropic_client_module.time, "sleep", lambda s: None)
    client = _client_with(
        [_internal_server_error() for _ in range(MAX_RETRIES)], tmp_path
    )

    with pytest.raises(ProviderError):
        client.answer(_make_record(), 0, TurnState())

    assert len(client._client.messages.calls) == MAX_RETRIES  # type: ignore[attr-defined]


def test_answer_propagates_non_retryable_error_without_retrying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-retryable error (e.g. `BadRequestError`) propagates as itself, on the first attempt."""

    def _sleep_should_not_be_called(seconds: float) -> None:
        raise AssertionError(
            "time.sleep should never be called for a non-retryable error"
        )

    monkeypatch.setattr(
        anthropic_client_module.time, "sleep", _sleep_should_not_be_called
    )
    client = _client_with([_bad_request_error()], tmp_path)

    with pytest.raises(anthropic.BadRequestError):
        client.answer(_make_record(), 0, TurnState())

    assert len(client._client.messages.calls) == 1  # type: ignore[attr-defined]
