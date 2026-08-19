"""Minimal per-turn results record produced by the eval loop.

Deliberately minimal: one `TurnResult` per scored turn, carrying only the fields directly
derivable from a `ScoreResult` and the turn it scored. The full stratified error-analysis
artifact (by number-selection-vs-computation, by turn index, by step count, by type1-vs-type2,
conversation-level exact match) reads off these same fields at read-time in a later session — it
is not built here. `reason` currently distinguishes only `"ok"` and `"wrong_value"`: the richer
taxonomy (`wrong_operation`, `no_answer`, `parse_error`, `timeout`, `provider_error`) needs a real
model client that can actually produce those failure modes, which does not exist yet. Pure data:
no I/O, no SDK, no network, no clock.
"""

from dataclasses import dataclass
from typing import Literal

Outcome = Literal["correct", "incorrect"]
Reason = Literal["ok", "wrong_value"]


@dataclass(frozen=True)
class TurnResult:
    """One turn's prediction, gold, and scoring outcome.

    `outcome` is `"correct"` exactly when the turn's `ScoreResult.tolerant_correct` was `True` —
    the frozen tolerant criterion is what "correct" means for the headline. `scale_flip` is
    copied straight from `ScoreResult.scale_flip`, never recomputed here.
    """

    record_id: str
    turn_index: int
    turn_program: str
    gold: float | str
    predicted: float | str
    outcome: Outcome
    reason: Reason
    scale_flip: bool
