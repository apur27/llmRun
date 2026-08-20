"""Runs the eval loop: every turn of every record, scored against a `ModelClient`.

Depends on the `ModelClient` port from `src/adapters/ports.py`, never a concrete client class —
`src/services` must be able to run against a stub, a fixture, or a real API client
interchangeably. Returns an aggregate summary (total/strict/tolerant counts and accuracies) plus
the minimal per-turn `TurnResult` list; the full stratified error-analysis artifact reads off
those records at read-time in a later session, not here.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from src.adapters.ports import ModelClient, ProviderError
from src.domain.executor import ProgramExecutionError
from src.domain.models import ConvFinQARecord
from src.domain.results import Outcome, Reason, TurnResult
from src.domain.scorer import ScoreResult, score_turn
from src.services.turn_state import TurnState


@dataclass(frozen=True)
class EvalSummary:
    """Aggregate counts and accuracies from running the eval loop over a set of records.

    Carries raw cumulative token counts only, never a dollar estimate — converting tokens to
    cost needs the calling client's pinned per-token rates, which are adapter-specific (vendor
    pricing), so that conversion is the caller's job (e.g. `estimate_cost_usd` in
    `src/adapters/anthropic_client.py`), not this module's. Keeps `src/services` depending on
    the `ModelClient` port only, never a concrete adapter symbol.
    """

    total_turns: int
    strict_correct: int
    tolerant_correct: int
    strict_accuracy: float
    tolerant_accuracy: float
    turn_results: list[TurnResult] = field(default_factory=list)
    cumulative_input_tokens: int = 0
    cumulative_output_tokens: int = 0
    cumulative_cache_creation_tokens: int = 0
    cumulative_cache_read_tokens: int = 0


class TurnCountMismatchError(Exception):
    """Raised when the number of turns scored does not match the number of turns supplied.

    PROPAGATES: no handler exists in this slice. A mismatch means a record's `turn_program` and
    `executed_answers` disagree in length, silently truncating the turns scored — a malformed
    record, not a runtime state to recover from — so this is intended to terminate the process
    rather than shrink the denominator, per this run's rule that a record failing to process
    exits non-zero.
    """


def run_eval(
    records: list[ConvFinQARecord],
    client: ModelClient,
    on_turn: Callable[[TurnResult, int, int], None] | None = None,
) -> EvalSummary:
    """Score `client`'s prediction for every turn of every record in `records`.

    Iterates each record's turns in order, calling `client.answer(record, turn_index,
    turn_state)` and scoring the prediction against the paired `executed_answers` entry via
    `score_turn`. Builds one fresh `TurnState` per record — never shared or carried over between
    records, since one record is one conversation — and appends each turn's (question,
    *predicted* answer) onto it before moving to the next turn, so a later turn's client sees
    what the model itself said, not gold, exactly as a real deployment would. A turn whose
    client raises `ProgramExecutionError` or `ProviderError` contributes nothing to `TurnState`:
    no prediction text was produced, so there is nothing truthful to hand a later turn as "what
    the model said" — inventing a placeholder would risk a later turn treating a refusal or a
    provider failure as a real recorded value. A `ProviderError` (the provider's own bounded
    retry exhausted) is scored `reason="provider_error"`, `outcome="incorrect"` — the frozen
    metric rule that a provider failure counts against the denominator rather than shrinking it.
    Raises `TurnCountMismatchError` if the number of turns scored does not equal the sum of
    `len(dialogue.turn_program)` across `records` — the denominator is asserted, never inferred.

    `on_turn`, when given, is called immediately after each `TurnResult` is appended to the
    running list — on every path (correct, incorrect, `parse_error`, `provider_error`) — as
    `on_turn(turn_result, scored_total, expected_total)`, so a caller (e.g. the CLI) can report
    progress or flush results to disk as the run proceeds rather than only once it returns. This
    module stays clock-free by design (no `time`/`datetime` import): wall-clock tracking is the
    caller's job, done inside its own `on_turn` callback.
    """
    expected_total = sum(len(record.dialogue.turn_program) for record in records)

    strict_correct = 0
    tolerant_correct = 0
    scored_total = 0
    turn_results: list[TurnResult] = []
    for record in records:
        turn_state = TurnState()
        questions = record.dialogue.conv_questions
        turns = zip(record.dialogue.turn_program, record.dialogue.executed_answers)
        for turn_index, (turn_program, gold) in enumerate(turns):
            scored_total += 1
            try:
                predicted = client.answer(record, turn_index, turn_state)
            except ProgramExecutionError:
                error_result = _build_error_result(
                    record.id, turn_index, turn_program, gold, "parse_error"
                )
                turn_results.append(error_result)
                if on_turn is not None:
                    on_turn(error_result, scored_total, expected_total)
                continue
            except ProviderError:
                error_result = _build_error_result(
                    record.id, turn_index, turn_program, gold, "provider_error"
                )
                turn_results.append(error_result)
                if on_turn is not None:
                    on_turn(error_result, scored_total, expected_total)
                continue
            result = score_turn(predicted, gold)
            if result.strict_correct:
                strict_correct += 1
            if result.tolerant_correct:
                tolerant_correct += 1
            turn_result = _build_turn_result(
                record.id, turn_index, turn_program, gold, predicted, result
            )
            turn_results.append(turn_result)
            if on_turn is not None:
                on_turn(turn_result, scored_total, expected_total)
            turn_state.add(questions[turn_index], predicted)

    if scored_total != expected_total:
        raise TurnCountMismatchError(
            f"scored {scored_total} turns but records supplied {expected_total} "
            "(turn_program/executed_answers length mismatch)"
        )

    input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens = (
        _read_cumulative_usage(client)
    )
    return EvalSummary(
        total_turns=scored_total,
        strict_correct=strict_correct,
        tolerant_correct=tolerant_correct,
        strict_accuracy=strict_correct / scored_total if scored_total else 0.0,
        tolerant_accuracy=tolerant_correct / scored_total if scored_total else 0.0,
        turn_results=turn_results,
        cumulative_input_tokens=input_tokens,
        cumulative_output_tokens=output_tokens,
        cumulative_cache_creation_tokens=cache_creation_tokens,
        cumulative_cache_read_tokens=cache_read_tokens,
    )


def _read_cumulative_usage(client: ModelClient) -> tuple[int, int, int, int]:
    """Read `client`'s cumulative usage attributes, defaulting to 0 when a client lacks them.

    `ModelClient` (the port) declares only `answer` — usage accounting is specific to real API
    clients, not every implementation of the port, so a stub or fixture client with no usage
    attributes reads as zero rather than requiring the Protocol itself to carry these fields.
    """
    return (
        getattr(client, "cumulative_input_tokens", 0),
        getattr(client, "cumulative_output_tokens", 0),
        getattr(client, "cumulative_cache_creation_tokens", 0),
        getattr(client, "cumulative_cache_read_tokens", 0),
    )


def _build_error_result(
    record_id: str,
    turn_index: int,
    turn_program: str,
    gold: float | str,
    reason: Reason,
) -> TurnResult:
    """Build the `TurnResult` for a turn whose client raised an error rather than a prediction.

    Shared by both error branches (`ProgramExecutionError` -> `"parse_error"`, `ProviderError`
    -> `"provider_error"`): no prediction was produced, so `predicted=None` — distinct from
    `"wrong_value"`, which always carries an actual (incorrect) predicted value.
    """
    return TurnResult(
        record_id=record_id,
        turn_index=turn_index,
        turn_program=turn_program,
        gold=gold,
        predicted=None,
        outcome="incorrect",
        reason=reason,
        scale_flip=False,
    )


def _build_turn_result(
    record_id: str,
    turn_index: int,
    turn_program: str,
    gold: float | str,
    predicted: float | str,
    result: ScoreResult,
) -> TurnResult:
    """Build one `TurnResult` from a scored turn, per the frozen `outcome`/`reason` mapping.

    `outcome` is `"correct"` exactly when `result.tolerant_correct` is `True` — the frozen
    tolerant criterion is what "correct" means for the headline. `reason` is `"ok"` for a
    correct turn and `"wrong_value"` for any incorrect one; the richer reason taxonomy needs a
    real model client and is not derivable here.
    """
    outcome: Outcome = "correct" if result.tolerant_correct else "incorrect"
    reason: Reason = "ok" if result.tolerant_correct else "wrong_value"
    return TurnResult(
        record_id=record_id,
        turn_index=turn_index,
        turn_program=turn_program,
        gold=gold,
        predicted=predicted,
        outcome=outcome,
        reason=reason,
        scale_flip=result.scale_flip,
    )
