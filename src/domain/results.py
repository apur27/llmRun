"""Minimal per-turn results record produced by the eval loop.

Deliberately minimal: one `TurnResult` per scored turn, carrying only the fields directly
derivable from a `ScoreResult` and the turn it scored. The full stratified error-analysis
artifact (by number-selection-vs-computation, by turn index, by step count, by type1-vs-type2,
conversation-level exact match) reads off these same fields at read-time in a later session — it
is not built here. `reason` currently distinguishes `"ok"`, `"wrong_value"`, `"parse_error"` (the
eval runner's catch of `ProgramExecutionError`), and `"provider_error"` (the eval runner's catch
of `ProviderError`) — both error reasons also leave `predicted=None` since no prediction was
produced. The richer taxonomy (`wrong_operation`, `no_answer`, `timeout`) needs failure modes a
real model client does not yet exercise. Pure data: no I/O, no SDK, no network, no clock.
"""

from dataclasses import dataclass
from typing import Literal

Outcome = Literal["correct", "incorrect"]
Reason = Literal["ok", "wrong_value", "parse_error", "provider_error"]


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
    predicted: float | str | None
    outcome: Outcome
    reason: Reason
    scale_flip: bool
