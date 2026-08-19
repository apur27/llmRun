"""Port interface for model clients that answer ConvFinQA turns.

Defines the seam between `src/services` (which drives the eval loop) and any concrete client
adapter (stub, fixture, real Anthropic) that computes a prediction. `src/services` depends only
on this `Protocol`, never a concrete implementation — that is what lets a stub, a fixture, and a
real API client stand in for each other without the eval runner importing any of them by name.
"""

from typing import Protocol

from src.domain.models import ConvFinQARecord


class ModelClient(Protocol):
    """Anything that can answer one turn of a ConvFinQA conversation."""

    def answer(self, record: ConvFinQARecord, turn_index: int) -> float | str:
        """Return a prediction for turn `turn_index` of `record`'s dialogue."""
        ...
