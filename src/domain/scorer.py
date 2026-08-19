"""Pure scoring primitive comparing one predicted answer to gold.

Encodes the metric decisions frozen in the plan before any model call: a 1e-3 relative tolerance
("tolerant"), reported separately from exact match ("strict"); yes/no answers scored by string
equality only, never coerced to or from a float; and a scale-flip (predicted = gold * 100 or
gold / 100) flagged for diagnostics but never elevated to correct. Pure: no I/O, no SDK, no
network, no clock, no randomness.
"""

from dataclasses import dataclass

RELATIVE_ERROR_TOLERANCE = 1e-3
STRICT_ERROR_TOLERANCE = 1e-9
SCALE_FLIP_FACTOR = 100.0


@dataclass(frozen=True)
class ScoreResult:
    """The outcome of comparing one predicted answer to gold.

    `strict_correct` and `tolerant_correct` are reported separately by design: the tolerance's
    effect on the headline number must stay visible rather than assumed. `scale_flip` is a
    diagnostic flag only — it is never allowed to make an incorrect answer correct.
    """

    strict_correct: bool
    tolerant_correct: bool
    scale_flip: bool


def score_turn(predicted: float | str, gold: float | str) -> ScoreResult:
    """Score one predicted answer against gold, per the frozen tolerance policy.

    A string gold is compared by exact string equality only, for both strict and tolerant, and
    never coerced to a float. A numeric gold is compared as a relative error (absolute error
    when gold is 0): strict requires the error below a `1e-9` floor that forgives only
    floating-point representation noise, tolerant requires it below the frozen `1e-3` relative
    epsilon. Mismatched types (a string predicted against a numeric gold, or vice versa) are
    always incorrect, never coerced either way. `scale_flip` is only ever set when the
    prediction is numeric, wrong, and within tolerance of `gold * 100` or `gold / 100`.
    """
    if isinstance(gold, str) or isinstance(predicted, str):
        return _score_non_numeric(predicted, gold)
    return _score_numeric(predicted, gold)


def _score_non_numeric(predicted: float | str, gold: float | str) -> ScoreResult:
    """Score a turn where gold and/or predicted is a string: exact string equality only."""
    is_match = (
        isinstance(predicted, str) and isinstance(gold, str) and predicted == gold
    )
    return ScoreResult(
        strict_correct=is_match, tolerant_correct=is_match, scale_flip=False
    )


def _score_numeric(predicted: float, gold: float) -> ScoreResult:
    """Score a turn where both predicted and gold are numeric, applying the tolerance policy."""
    error = _relative_error(predicted, gold)
    strict_correct = error <= STRICT_ERROR_TOLERANCE
    tolerant_correct = error <= RELATIVE_ERROR_TOLERANCE
    scale_flip = not tolerant_correct and _is_scale_flip(predicted, gold)
    return ScoreResult(
        strict_correct=strict_correct,
        tolerant_correct=tolerant_correct,
        scale_flip=scale_flip,
    )


def _is_scale_flip(predicted: float, gold: float) -> bool:
    """Whether `predicted` is within tolerance of `gold * 100` or `gold / 100`."""
    scaled_up = (
        _relative_error(predicted, gold * SCALE_FLIP_FACTOR) <= RELATIVE_ERROR_TOLERANCE
    )
    scaled_down = (
        _relative_error(predicted, gold / SCALE_FLIP_FACTOR) <= RELATIVE_ERROR_TOLERANCE
    )
    return scaled_up or scaled_down


def _relative_error(predicted: float, gold: float) -> float:
    """Relative error of `predicted` against `gold`, falling back to absolute error at gold=0."""
    return abs(predicted - gold) if gold == 0 else abs(predicted - gold) / abs(gold)
