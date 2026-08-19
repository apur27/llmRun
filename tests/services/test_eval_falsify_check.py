"""Unit tests for `src.services.eval_falsify_check.main`.

Exercises `main` with an injected `ModelClient`, never a monkeypatched module-level import, since
the fix under test is `main` accepting the client as a parameter rather than constructing a
concrete `StubClient` itself.
"""

from src.adapters.stub_client import StubClient
from src.domain.models import ConvFinQARecord
from src.services.eval_falsify_check import main
from src.services.turn_state import TurnState


class _AlwaysCorrectFirstTurnClient:
    """A `ModelClient` that answers turn 0 of every record correctly, guaranteeing non-zero accuracy."""

    def answer(
        self, record: ConvFinQARecord, turn_index: int, turn_state: TurnState
    ) -> float | str:
        """Return the gold answer for `turn_index`, always scoring correct."""
        return record.dialogue.executed_answers[turn_index]


def test_main_returns_zero_when_stub_client_scores_zero_tolerant_accuracy() -> None:
    """`main` returns 0 when the injected client's tolerant accuracy over the real dev split is 0.0.

    Uses the real `StubClient`, which is guaranteed wrong on every turn by construction — this is
    the falsify check's own happy path, run through `main`'s new injected-client signature.
    """
    exit_code = main(StubClient())

    assert exit_code == 0


def test_main_returns_one_when_client_scores_above_zero_tolerant_accuracy() -> None:
    """`main` returns 1 when the injected client's tolerant accuracy over the dev split is not 0.0.

    A client correct on every record's first turn cannot produce exactly 0.0 tolerant accuracy
    over a non-empty dev split, so this proves the falsify check can actually fail.
    """
    exit_code = main(_AlwaysCorrectFirstTurnClient())

    assert exit_code == 1
