"""Real Anthropic API adapter implementing the `ModelClient` port.

The one module in this package allowed to import the `anthropic` SDK — every provider-shaped
type (message params, tool schemas, content blocks) stays inside this module, per the
vendor-isolation boundary in `_core.md`/`python.md`. Answers one turn at a time: the current
turn's question, the record's document, and the conversation's prior turns from `TurnState`,
rendered as real prior `user`/`assistant` messages so the model can resolve a reference to an
earlier turn's subject or answer ("that", "it") the same way slice 12's real-data probe
validated (see `notes/risky-unknown.md`) — not gold, only what the model itself answered before
(see the module docstring in `src/domain/executor.py` for the same within-turn/cross-turn
distinction). Arithmetic never happens in-token: a `calculate` tool is exposed to the model, and
every tool call is executed by the same `execute_program` the gold-replay and scorer already
trust, so the tool's arithmetic can never drift from the executor's semantics.
"""

import json
import os
import re
import sys
import time
from typing import Any

import anthropic
from anthropic.types import (
    Message,
    MessageParam,
    TextBlock,
    TextBlockParam,
    ToolParam,
    ToolUseBlock,
    Usage,
)
from rich import print as rich_print

from src.adapters.ports import ProviderError
from src.adapters.response_cache import ResponseCache
from src.domain.executor import ProgramExecutionError, execute_program
from src.domain.models import ConvFinQARecord
from src.services.turn_state import TurnState

# Kept for session 2: arithmetic is fully externalised to the `calculate` tool, so the model's
# job is extraction/routing + turn-state recall, not multi-step derivation. Slice 12 validated
# routing+recall at 3/3 real conversations on this model; the two misses were a scale-form
# convention issue and one refusal, not an arithmetic-capability gap.
MODEL = "claude-haiku-4-5-20251001"
TEMPERATURE = 0.0
MAX_TOKENS = 1024
MAX_TOOL_ITERATIONS = 5
ANSWER_PREFIX = "ANSWER:"

# Bounded retry for transient provider failures only -- see `_create_with_retry`. A
# non-transient error (bad request, bad key) is never retried: it fails fast on the first
# attempt since retrying it would just burn the budget on a call that can never succeed.
MAX_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 1.0

_RETRYABLE_ERRORS = (
    anthropic.RateLimitError,  # 429
    anthropic.InternalServerError,  # generic 5xx
    anthropic.OverloadedError,  # 529, Anthropic-specific "overloaded" -- also effectively 5xx
    anthropic.APIConnectionError,  # connection failures; APITimeoutError subclasses this
)

_USD_PER_MILLION_TOKENS = 1_000_000

# Rate assumption, not measured — Anthropic's published per-token price for
# claude-haiku-4-5-20251001 as of Aug 2026: $1.00 / MTok input, $5.00 / MTok output.
# Not fetched live this slice; flagged for a source check against the current pricing page
# before being treated as billing-accurate.
INPUT_TOKEN_RATE_USD = 1.00 / _USD_PER_MILLION_TOKENS
OUTPUT_TOKEN_RATE_USD = 5.00 / _USD_PER_MILLION_TOKENS
# Rate assumption, not measured — Anthropic's standard prompt-caching discount, consistent
# across models: a cache read is billed at 10% of the base input rate, a cache write
# (creation) at 1.25x the base input rate for the default 5-minute TTL. Same source-check
# caveat as above; folding a cache-read token into plain input tokens would overstate cost.
CACHE_READ_TOKEN_RATE_USD = INPUT_TOKEN_RATE_USD * 0.1
CACHE_CREATION_TOKEN_RATE_USD = INPUT_TOKEN_RATE_USD * 1.25

_API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"
_YES_NO_VALUES = {"yes", "no"}
_ANSWER_PATTERN = re.compile(rf"{re.escape(ANSWER_PREFIX)}\s*(.+)", re.IGNORECASE)

_SYSTEM_INSTRUCTIONS = (
    "You are answering a question about a financial document. Use the calculate tool for any "
    "arithmetic instead of computing it yourself. Finish your reply with exactly one line of "
    f"the form '{ANSWER_PREFIX} <value>', where <value> is a number or yes/no. When a computed "
    "answer is a ratio produced by division, always report it as the raw decimal ratio -- never "
    "multiply it by 100 to express it as a percentage, no matter how the question is phrased."
)
_REPAIR_INSTRUCTIONS = (
    f"Your last reply did not end with a line of the exact form '{ANSWER_PREFIX} <value>'. "
    "Reply again, ending with exactly that line and nothing after it."
)

CALCULATE_TOOL: ToolParam = {
    "name": "calculate",
    "description": "Perform one arithmetic operation on two numbers and return the result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["add", "subtract", "multiply", "divide"],
            },
            "first": {"type": "number"},
            "second": {"type": "number"},
        },
        "required": ["operation", "first", "second"],
    },
}


class MissingApiKeyError(Exception):
    """Raised when `ANTHROPIC_API_KEY` is unset at client construction time.

    CAUGHT at the CLI boundary: `src/main.py`'s `chat` and `_build_client` (used by `eval`)
    both catch this and exit clean (`typer.Exit(code=1)`) on the one stderr line `from_env`
    already wrote naming the variable, rather than letting it propagate as a traceback --
    this is the one command a reviewer with no API key actually runs first. Nothing in
    `src/adapters` itself handles it; this adapter only ever raises it.
    """


class AnthropicClient:
    """A `ModelClient` backed by the real Anthropic API, with prompt caching and a calculator tool."""

    def __init__(
        self,
        client: anthropic.Anthropic,
        cache: ResponseCache,
        system_instructions: str = _SYSTEM_INSTRUCTIONS,
    ) -> None:
        """Wrap an already-constructed SDK client and response cache — both injected, not built here.

        `system_instructions` selects which system-prompt variant this instance sends and hashes
        into its cache keys, defaulting to the module's own `_SYSTEM_INSTRUCTIONS`. Callers running
        an A/B comparison (e.g. the percentage-convention experiment) build one `AnthropicClient`
        per variant string, so the two variants' answers for the same record/question are never
        conflated under one cache entry.
        """
        self._client = client
        self._cache = cache
        self._system_instructions = system_instructions
        self._input_tokens = 0
        self._output_tokens = 0
        self._cache_creation_tokens = 0
        self._cache_read_tokens = 0

    @property
    def cumulative_input_tokens(self) -> int:
        """Total input tokens billed across every real `messages.create` call this instance made."""
        return self._input_tokens

    @property
    def cumulative_output_tokens(self) -> int:
        """Total output tokens billed across every real `messages.create` call this instance made."""
        return self._output_tokens

    @property
    def cumulative_cache_creation_tokens(self) -> int:
        """Total prompt-cache-write tokens billed across every real call this instance made."""
        return self._cache_creation_tokens

    @property
    def cumulative_cache_read_tokens(self) -> int:
        """Total prompt-cache-read tokens billed across every real call this instance made."""
        return self._cache_read_tokens

    @classmethod
    def from_env(
        cls,
        cache: ResponseCache | None = None,
        system_instructions: str = _SYSTEM_INSTRUCTIONS,
    ) -> "AnthropicClient":
        """Build a client from `ANTHROPIC_API_KEY`, failing clean if it is unset.

        Checks the environment variable explicitly *before* constructing the SDK client. If
        unset: writes one line naming the variable to stderr and raises `MissingApiKeyError` —
        never a bare `KeyError` or SDK traceback, and never a silent fall back to a fixture
        client.
        """
        api_key = os.environ.get(_API_KEY_ENV_VAR)
        if api_key is None:
            rich_print(f"{_API_KEY_ENV_VAR} is not set", file=sys.stderr)
            raise MissingApiKeyError(
                f"{_API_KEY_ENV_VAR} environment variable is not set"
            )
        return cls(
            anthropic.Anthropic(api_key=api_key),
            cache if cache is not None else ResponseCache(),
            system_instructions=system_instructions,
        )

    def answer(
        self, record: ConvFinQARecord, turn_index: int, turn_state: TurnState
    ) -> float | str:
        """Answer turn `turn_index` of `record`'s dialogue via the Anthropic API.

        Sends the current turn's question, `record`'s document, and `turn_state`'s prior turns
        rendered as real conversation history, so the model can resolve a reference to an
        earlier turn's subject or answer. Checks the response cache first, keyed by the exact
        prompt text (document, question, *and* prior-turn history), so a repeated eval run never
        re-bills an already-answered turn, and two different histories for the same question
        never collide on one cache entry.
        """
        question = record.dialogue.conv_questions[turn_index]
        prompt = _prompt_text(record, question, self._system_instructions, turn_state)
        cached = self._cache.get(prompt)
        if cached is not None:
            return _parse_final_answer(cached)

        system = _system_blocks(record, self._system_instructions)
        messages: list[MessageParam] = _history_messages(turn_state)
        messages.append({"role": "user", "content": question})
        final_text = self._run_tool_loop(system, messages)
        final_text = self._ensure_parseable(system, messages, final_text)

        self._cache.set(prompt, final_text)
        return _parse_final_answer(final_text)

    def _ensure_parseable(
        self, system: list[TextBlockParam], messages: list[MessageParam], text: str
    ) -> str:
        """Return `text` unchanged if it parses, else attempt one repair round-trip."""
        if _try_parse_final_answer(text) is not None:
            return text
        messages.append({"role": "user", "content": _REPAIR_INSTRUCTIONS})
        repaired = self._run_tool_loop(system, messages)
        if _try_parse_final_answer(repaired) is None:
            raise ProgramExecutionError(
                f"could not parse a final answer after one repair attempt: {repaired!r}"
            )
        return repaired

    def _run_tool_loop(
        self, system: list[TextBlockParam], messages: list[MessageParam]
    ) -> str:
        """Drive the tool-use loop until the model stops calling tools, or raise past the cap."""
        for _ in range(MAX_TOOL_ITERATIONS):
            response = self._create_with_retry(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                system=system,
                tools=[CALCULATE_TOOL],
                messages=messages,
            )
            self._accumulate_usage(response.usage)
            messages.append(
                {"role": "assistant", "content": response.model_dump()["content"]}
            )
            if response.stop_reason != "tool_use":
                return _extract_text(response.content)
            messages.append(
                {"role": "user", "content": _tool_results(response.content)}
            )
        raise ProgramExecutionError(
            f"tool-call iteration cap ({MAX_TOOL_ITERATIONS}) reached without a final answer"
        )

    def _create_with_retry(self, **kwargs: Any) -> Message:
        """Call `self._client.messages.create` with bounded retry+backoff on transient failures.

        Only `_RETRYABLE_ERRORS` (rate limit, 5xx, overloaded, connection failure) are caught
        and retried, up to `MAX_RETRIES` total attempts, with exponential backoff between
        attempts (`RETRY_BASE_DELAY_SECONDS * 2 ** attempt`). Anything else (e.g.
        `BadRequestError`, `AuthenticationError`) propagates immediately, unretried, since it
        means something structurally wrong that a retry cannot fix. If every attempt raises a
        retryable error, raises `ProviderError` chained from the last one.
        """
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                response: Message = self._client.messages.create(**kwargs)
                return response
            except _RETRYABLE_ERRORS as exc:
                last_exc = exc
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BASE_DELAY_SECONDS * (2**attempt))
        raise ProviderError(
            f"exhausted {MAX_RETRIES} attempts against the Anthropic API: {last_exc!r}"
        ) from last_exc

    def _accumulate_usage(self, usage: Usage) -> None:
        """Add one API call's `response.usage` onto this instance's running totals.

        `cache_creation_input_tokens`/`cache_read_input_tokens` are `None` on the SDK's `Usage`
        type when prompt caching did not apply to that call, so each is coalesced to 0 rather
        than accumulated as `None`.
        """
        self._input_tokens += usage.input_tokens
        self._output_tokens += usage.output_tokens
        self._cache_creation_tokens += usage.cache_creation_input_tokens or 0
        self._cache_read_tokens += usage.cache_read_input_tokens or 0


def estimate_cost_usd(
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int,
    cache_read_tokens: int,
) -> float:
    """Estimate USD cost from token counts and this module's pinned per-token rate constants.

    Pure and provider-specific: lives beside the rate constants it reads rather than in
    `src/services`, per the layer rule that pricing knowledge for one vendor is adapter-shaped,
    not a domain or use-case concern.
    """
    return (
        input_tokens * INPUT_TOKEN_RATE_USD
        + output_tokens * OUTPUT_TOKEN_RATE_USD
        + cache_creation_tokens * CACHE_CREATION_TOKEN_RATE_USD
        + cache_read_tokens * CACHE_READ_TOKEN_RATE_USD
    )


def _system_blocks(
    record: ConvFinQARecord, system_instructions: str
) -> list[TextBlockParam]:
    """Build the system prompt: instructions plus the document, cached across every turn's call.

    `cache_control` on the document block is the Anthropic prompt-caching mechanism: the
    pre_text/post_text/table content repeats identically across every turn of the same
    conversation, so marking it cacheable avoids re-billing it turn after turn. Prior-turn
    history from `TurnState` lives in the `messages` list, not here, and does *not* repeat from
    turn to turn (each turn adds one more prior turn to the history) -- so this placement is
    still correct with history in play: caching the document (constant per conversation) and
    leaving the growing message history uncached is the right split, not an oversight.
    """
    return [
        {"type": "text", "text": system_instructions},
        {
            "type": "text",
            "text": _document_text(record),
            "cache_control": {"type": "ephemeral"},
        },
    ]


def _document_text(record: ConvFinQARecord) -> str:
    """Render `record`'s document (pre-text, table, post-text) as plain text for the prompt."""
    table_text = json.dumps(record.doc.table)
    return f"{record.doc.pre_text}\n\n{table_text}\n\n{record.doc.post_text}"


def _prompt_text(
    record: ConvFinQARecord,
    question: str,
    system_instructions: str,
    turn_state: TurnState,
) -> str:
    """The full prompt text (system, document, prior-turn history, question) used as the cache key.

    Takes `system_instructions` as the same value the caller sends to `_system_blocks`, rather
    than reading the module-level constant directly — the two variants must never converge on
    the same cache key, or an A/B comparison run through this cache would silently replay the
    first variant's cached answers for the second. Includes `turn_state`'s prior turns for the
    same reason: two different conversation histories are two different prompts, and must never
    collide on one cache entry.
    """
    return (
        f"{system_instructions}\n\n{_document_text(record)}\n\n"
        f"{_history_text(turn_state)}Question: {question}"
    )


def _history_messages(turn_state: TurnState) -> list[MessageParam]:
    """Render `turn_state`'s prior turns as real `user`/`assistant` messages, oldest first.

    Mirrors slice 12's validated probe shape (`notes/risky-unknown.md`): a real growing
    conversation where the model's own recorded prior answer is what a later turn sees, not
    gold. Each prior answer is rendered as an `ANSWER:` line so it matches the exact form the
    model was instructed to produce it in.
    """
    messages: list[MessageParam] = []
    for turn in turn_state.turns:
        messages.append({"role": "user", "content": turn.question})
        messages.append(
            {"role": "assistant", "content": f"{ANSWER_PREFIX} {turn.answer}"}
        )
    return messages


def _history_text(turn_state: TurnState) -> str:
    """Render `turn_state`'s prior turns as plain text, for inclusion in the cache key.

    Must vary whenever `_history_messages` would produce a different messages list, so two
    different conversation histories never collide on one cache entry. Empty string when there
    is no prior history (a conversation's first turn).
    """
    return "".join(
        f"Prior Q: {turn.question}\nPrior A: {turn.answer}\n"
        for turn in turn_state.turns
    )


def _tool_results(content: list[Any]) -> list[Any]:
    """Execute every `calculate` tool call in `content` via the domain executor."""
    return [
        _execute_tool_call(block)
        for block in content
        if isinstance(block, ToolUseBlock)
    ]


def _execute_tool_call(block: ToolUseBlock) -> dict[str, Any]:
    """Run one `calculate` tool call through `execute_program`, returning its result as text.

    A `ProgramExecutionError` from the executor (e.g. divide by zero) is returned as the tool
    result text with `is_error=True`, so the model sees it and can retry, rather than crashing
    the turn.
    """
    program = _build_calculator_program(block.input)
    try:
        result = execute_program(program)
    except ProgramExecutionError as exc:
        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": str(exc),
            "is_error": True,
        }
    return {"type": "tool_result", "tool_use_id": block.id, "content": str(result)}


def _build_calculator_program(tool_input: dict[str, object]) -> str:
    """Build the DSL program string for one `calculate` tool call's arguments."""
    operation = tool_input["operation"]
    first = tool_input["first"]
    second = tool_input["second"]
    return f"{operation}({first}, {second})"


def _extract_text(content: list[Any]) -> str:
    """Join every text block in `content` into the model's final reply text."""
    return "\n".join(block.text for block in content if isinstance(block, TextBlock))


def _try_parse_final_answer(text: str) -> float | str | None:
    """Parse an `ANSWER: <value>` line from `text`, or return `None` if none is found/valid."""
    match = _ANSWER_PATTERN.search(text)
    if match is None:
        return None
    raw = match.group(1).strip()
    if raw.lower() in _YES_NO_VALUES:
        return raw.lower()
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_final_answer(text: str) -> float | str:
    """Parse `text`'s final `ANSWER: <value>` line, raising `ProgramExecutionError` if absent."""
    parsed = _try_parse_final_answer(text)
    if parsed is None:
        raise ProgramExecutionError(f"could not parse a final answer from: {text!r}")
    return parsed
