"""Runs the eval loop: every turn of every record, scored against a `ModelClient`.

Depends on the `ModelClient` port from `src/adapters/ports.py`, never a concrete client class —
`src/services` must be able to run against a stub, a fixture, or a real API client
interchangeably. Returns an aggregate summary only (total/strict/tolerant counts and
accuracies); the full per-turn results artifact with outcome/reason detail is a later slice's
job, not this one's.
"""

from dataclasses import dataclass

from src.adapters.ports import ModelClient
from src.domain.models import ConvFinQARecord
from src.domain.scorer import score_turn


@dataclass(frozen=True)
class EvalSummary:
    """Aggregate counts and accuracies from running the eval loop over a set of records."""

    total_turns: int
    strict_correct: int
    tolerant_correct: int
    strict_accuracy: float
    tolerant_accuracy: float


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
    for record in records:
        turns = zip(record.dialogue.turn_program, record.dialogue.executed_answers)
        for turn_index, (_, gold) in enumerate(turns):
            predicted = client.answer(record, turn_index)
            result = score_turn(predicted, gold)
            scored_total += 1
            if result.strict_correct:
                strict_correct += 1
            if result.tolerant_correct:
                tolerant_correct += 1

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
    )
