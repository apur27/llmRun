"""Falsification check: proves the eval pipeline can report a non-zero-accuracy result.

Runs the full eval loop against the real dev split with `StubClient`, which is guaranteed wrong
on every turn by construction. Asserts the resulting tolerant accuracy is exactly 0.0 through
the same path (`load_dataset` -> `run_eval`) the real eval will use later, and exits non-zero
with a clear message if that assertion ever fails — the "drive the headline to zero" proof for
this slice, callable via `uv run python -m src.services.eval_falsify_check`.
"""

import sys
from pathlib import Path

from rich import print as rich_print

from src.adapters.stub_client import StubClient
from src.domain.loader import load_dataset
from src.services.eval_runner import run_eval

DATA_PATH = Path(__file__).parent.parent.parent / "data" / "convfinqa_dataset.json"
EXPECTED_TOLERANT_ACCURACY = 0.0


def main() -> int:
    """Run the eval loop against the real dev split with the stub client; check accuracy is 0.

    Returns 0 (and prints a confirmation) if the stub's tolerant accuracy is exactly 0.0, or 1
    (and prints a clear failure message) otherwise.
    """
    dataset = load_dataset(DATA_PATH)
    summary = run_eval(dataset["dev"], StubClient())

    if summary.tolerant_accuracy != EXPECTED_TOLERANT_ACCURACY:
        rich_print(
            "[red][bold]FALSIFY CHECK FAILED:[/bold] expected tolerant accuracy "
            f"{EXPECTED_TOLERANT_ACCURACY}, got {summary.tolerant_accuracy} "
            f"over {summary.total_turns} turns.[/red]"
        )
        return 1

    rich_print(
        "[green]falsify check passed: tolerant accuracy is 0.0 over "
        f"{summary.total_turns} turns.[/green]"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
