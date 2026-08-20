"""Port interface for model clients that answer ConvFinQA turns.

Defines the seam between `src/services` (which drives the eval loop) and any concrete client
adapter (stub, fixture, real Anthropic) that computes a prediction. `src/services` depends only
on this `Protocol`, never a concrete implementation — that is what lets a stub, a fixture, and a
real API client stand in for each other without the eval runner importing any of them by name.
"""

from typing import Protocol

from src.domain.models import ConvFinQARecord
from src.services.turn_state import TurnState


class ProviderError(Exception):
    """Raised when a model client's underlying API call fails and cannot be recovered.

    Distinct from `ProgramExecutionError` (a parseable-but-wrong response): this is the
    provider itself failing (rate limit, server error, timeout) after a client's own bounded
    retry is exhausted. Lives here, not in a concrete adapter module, so `src/services` can
    catch it without importing `src.adapters.anthropic_client` or the `anthropic` SDK --
    same layering rule `ModelClient` itself follows.
    """


class ModelClient(Protocol):
    """Anything that can answer one turn of a ConvFinQA conversation."""

    def answer(
        self, record: ConvFinQARecord, turn_index: int, turn_state: TurnState
    ) -> float | str:
        """Return a prediction for turn `turn_index` of `record`'s dialogue.

        `turn_state` carries the conversation's prior turns (question, model's own predicted
        answer) in order -- never gold -- so an implementation that resolves cross-turn
        references (e.g. `AnthropicClient`) has what it needs. A client with no use for history
        (`StubClient`, `FixtureClient`) accepts and ignores it.
        """
        ...
