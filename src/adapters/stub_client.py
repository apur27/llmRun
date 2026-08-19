"""Deterministic stub model client, guaranteed wrong on every turn.

Exists to falsify the eval pipeline before any real model is wired in: since `score_turn` never
coerces a string prediction into matching a float gold, and the sentinel string can never equal
a `"yes"`/`"no"` gold either, this client's sentinel answer is incorrect by construction for
every turn in the dataset, numeric or yes/no. Ignores its input entirely.
"""

from src.domain.models import ConvFinQARecord
from src.services.turn_state import TurnState

STUB_SENTINEL = "__STUB_NEVER_CORRECT__"


class StubClient:
    """A `ModelClient` that always returns a fixed sentinel, never a numeric or yes/no value."""

    def answer(
        self, record: ConvFinQARecord, turn_index: int, turn_state: TurnState
    ) -> float | str:
        """Ignore `record`, `turn_index`, and `turn_state`; always return the sentinel string."""
        return STUB_SENTINEL
