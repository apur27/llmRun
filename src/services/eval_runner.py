"""Runs the eval loop: every turn of every record, scored against a `ModelClient`.

Depends on the `ModelClient` port from `src/adapters/ports.py`, never a concrete client class —
`src/services` must be able to run against a stub, a fixture, or a real API client
interchangeably. Returns an aggregate summary (total/strict/tolerant counts and accuracies) plus
the minimal per-turn `TurnResult` list; the full stratified error-analysis artifact reads off
those records at read-time in a later session, not here.
"""

from dataclasses import dataclass, field

from src.adapters.ports import ModelClient
from src.domain.executor import ProgramExecutionError
from src.domain.models import ConvFinQARecord
from src.domain.results import Outcome, Reason, TurnResult
from src.domain.scorer import ScoreResult, score_turn


@dataclass(frozen=True)
class EvalSummary:
    """Aggregate counts and accuracies from running the eval loop over a set of records."""

    total_turns: int
    strict_correct: int
    tolerant_correct: int
    strict_accuracy: float
    tolerant_accuracy: float
    turn_results: list[TurnResult] = field(default_factory=list)


class TurnCountMismatchError(Exception):
    """Raised when the number of turns scored does not match the number of turns supplied.

    PROPAGATES: no handler exists in this slice. A mismatch means a record's `turn_program` and
    `executed_answers` disagree in length, silently truncating the turns scored — a malformed
    record, not a runtime state to recover from — so this is intended to terminate the process
    rather than shrink the denominator, per this run's rule that a record failing to process
    exits non-zero.
    """


def run_eval(records: list[ConvFinQARecord], client: ModelClient) -> EvalSummary:
    """Score `client`'s prediction for every turn of every record in `records`.

    Iterates each record's turns in order, calling `client.answer(record, turn_index)` and
    scoring the prediction against the paired `executed_answers` entry via `score_turn`. Raises
    `TurnCountMismatchError` if the number of turns scored does not equal the sum of
    `len(dialogue.turn_program)` across `records` — the denominator is asserted, never inferred.
    """
    expected_total = sum(len(record.dialogue.turn_program) for record in records)

    strict_correct = 0
    tolerant_correct = 0
    scored_total = 0
    turn_results: list[TurnResult] = []
    for record in records:
        turns = zip(record.dialogue.turn_program, record.dialogue.executed_answers)
        for turn_index, (turn_program, gold) in enumerate(turns):
            scored_total += 1
            try:
                predicted = client.answer(record, turn_index)
            except ProgramExecutionError:
                turn_results.append(
                    _build_parse_error_result(record.id, turn_index, turn_program, gold)
                )
                continue
            result = score_turn(predicted, gold)
            if result.strict_correct:
                strict_correct += 1
            if result.tolerant_correct:
                tolerant_correct += 1
            turn_results.append(
                _build_turn_result(
                    record.id, turn_index, turn_program, gold, predicted, result
                )
            )

    if scored_total != expected_total:
        raise TurnCountMismatchError(
            f"scored {scored_total} turns but records supplied {expected_total} "
            "(turn_program/executed_answers length mismatch)"
        )

    return EvalSummary(
        total_turns=scored_total,
        strict_correct=strict_correct,
        tolerant_correct=tolerant_correct,
        strict_accuracy=strict_correct / scored_total if scored_total else 0.0,
        tolerant_accuracy=tolerant_correct / scored_total if scored_total else 0.0,
        turn_results=turn_results,
    )


def _build_parse_error_result(
    record_id: str, turn_index: int, turn_program: str, gold: float | str
) -> TurnResult:
    """Build the `TurnResult` for a turn whose client raised `ProgramExecutionError`.

    No prediction was produced, so `predicted=None` and `reason="parse_error"` — distinct from
    `"wrong_value"`, which always carries an actual (incorrect) predicted value.
    """
    return TurnResult(
        record_id=record_id,
        turn_index=turn_index,
        turn_program=turn_program,
        gold=gold,
        predicted=None,
        outcome="incorrect",
        reason="parse_error",
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
