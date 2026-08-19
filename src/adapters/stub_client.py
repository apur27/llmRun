"""Deterministic stub model client, guaranteed wrong on every turn.

Exists to falsify the eval pipeline before any real model is wired in: since `score_turn` never
coerces a string prediction into matching a float gold, this client's sentinel answer is incorrect
by construction for every turn in the dataset, numeric or yes/no. Ignores its input entirely.

The sentinel is a `float`, not an arbitrary string, because `TurnState.add` (`src/services/
turn_state.py`) validates every recorded answer as either a `float` or exactly `"yes"`/`"no"` --
a string sentinel would now be rejected when the eval loop records this client's own answer for
a later turn. `-999_999_999.0` is used because it is wildly outside any magnitude a ConvFinQA gold
value takes, even after the scorer's scale-flip check (`gold * 100` / `gold / 100`, see
`SCALE_FLIP_FACTOR` in `src/domain/scorer.py`) -- no real financial figure in this dataset, scaled
either way, comes anywhere near this value, so it can never spuriously match gold.
"""

from src.domain.models import ConvFinQARecord
from src.services.turn_state import TurnState

STUB_SENTINEL = -999_999_999.0


class StubClient:
    """A `ModelClient` that always returns a fixed sentinel, never a real numeric or yes/no value."""

    def answer(
        self, record: ConvFinQARecord, turn_index: int, turn_state: TurnState
    ) -> float | str:
        """Ignore `record`, `turn_index`, and `turn_state`; always return the sentinel float."""
        return STUB_SENTINEL
