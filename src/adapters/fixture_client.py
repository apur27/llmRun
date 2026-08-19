"""Deterministic client backed by pre-recorded fixture responses, for offline replay.

Loads a small JSON file mapping `f"{record_id}:{turn_index}"` to a recorded `float | str`
answer. Pure and deterministic: never falls through to a network call or a default value on a
miss — a `(record, turn_index)` pair absent from the fixture file is a test-authoring gap, not a
runtime state to guess through, so it raises `FixtureMissError` immediately.
"""

import json
from pathlib import Path

from src.domain.models import ConvFinQARecord
from src.services.turn_state import TurnState

_KEY_SEPARATOR = ":"


class FixtureMissError(Exception):
    """Raised when a requested `(record, turn_index)` has no entry in the loaded fixture file.

    PROPAGATES: no handler exists in this slice. A fixture miss means the fixture data is
    incomplete, not a runtime state to fall back from — silently returning a default would defeat
    the purpose of a deterministic offline client, so this is intended to propagate to the top
    level and terminate the run until whoever authors the fixture file adds the missing entry.
    """


class FixtureClient:
    """A `ModelClient` that answers strictly from a pre-recorded fixture file."""

    def __init__(self, fixtures_path: Path) -> None:
        """Load and hold the fixture mapping from the JSON file at `fixtures_path`."""
        raw: dict[str, float | str] = json.loads(fixtures_path.read_text())
        self._responses = raw

    def answer(
        self, record: ConvFinQARecord, turn_index: int, turn_state: TurnState
    ) -> float | str:
        """Return the recorded response for `(record.id, turn_index)`, or raise on a miss.

        `turn_state` is ignored: fixture responses are pre-recorded per `(record, turn_index)`
        and never depend on conversation history.
        """
        key = f"{record.id}{_KEY_SEPARATOR}{turn_index}"
        if key not in self._responses:
            raise FixtureMissError(f"no fixture response recorded for {key!r}")
        return self._responses[key]
