"""
Main typer app for ConvFinQA
"""

import contextlib
import dataclasses
import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Optional, TextIO

import typer
from dotenv import load_dotenv
from rich import print as rich_print

from src.adapters.anthropic_client import (
    AnthropicClient,
    MissingApiKeyError,
    estimate_cost_usd,
)
from src.adapters.fixture_client import FixtureClient, FixtureMissError
from src.adapters.ports import ModelClient
from src.adapters.stub_client import StubClient
from src.domain.executor import ProgramExecutionError
from src.domain.loader import load_dataset
from src.domain.models import ConvFinQARecord
from src.domain.results import TurnResult
from src.services.eval_runner import run_eval
from src.services.turn_state import TurnState

# How often (in scored turns) `eval`'s progress callback also prints elapsed/projected-remaining
# wall-clock, on top of the per-turn progress+cost line it always prints.
_PROGRESS_INTERVAL_TURNS = 100

# Loaded once, early, before any command builds a real client -- `AnthropicClient.from_env()`
# reads `ANTHROPIC_API_KEY` from `os.environ`, and nothing else in this CLI's import graph
# loads `.env` (`src/logger.py` does, but nothing here imports it). A no-op when `.env` is
# absent or the key is already exported in the shell.
load_dotenv()

app = typer.Typer(
    name="main",
    help="Conversational agent for ConvFinQA: chat through a document's questions, or run the eval loop for accuracy.",
    add_completion=True,
    no_args_is_help=True,
)

DATA_PATH = Path(__file__).parent.parent / "data" / "convfinqa_dataset.json"
FIXTURES_DEMO_PATH = (
    Path(__file__).parent.parent / "data" / "reviewer_demo_fixtures.json"
)


@app.command()
def chat(
    record_id: str = typer.Argument(..., help="ID of the record to chat about"),
    client: str = typer.Option(
        "anthropic",
        "--client",
        help="Model client to run against: 'anthropic' (default, needs a real key) or "
        "'fixture' (no key, no network -- replays real recorded answers offline).",
    ),
) -> None:
    """Walk one record's own questions, in order, against the chosen client.

    Not free-text chat: the client's `answer()` is keyed to a record's own
    `conv_questions[turn_index]`, not arbitrary text, so this command asks each turn's
    scripted question in order and prints the answer -- press enter to see the next turn,
    or type `exit`/`quit` to stop early. Each turn's (question, answer) is appended to a
    session `TurnState`, so a later turn's client sees prior history exactly like
    `run_eval` does.

    `--client anthropic` (default) builds a real `AnthropicClient` from `ANTHROPIC_API_KEY`
    and fails clean -- one line, no traceback -- if the key is missing. `--client fixture`
    builds a `FixtureClient` over a committed file of real, previously recorded Anthropic
    responses (`data/reviewer_demo_fixtures.json`) -- no key and no network touched at all,
    so a reviewer with no credential can still see the real interface and real recorded
    output. A `record_id` with no entry in the fixture file prints one clean message naming
    the record ids that *are* available, rather than a traceback.
    """
    dataset = load_dataset(DATA_PATH)
    record = _find_record(dataset, record_id)
    model_client = _build_chat_client(client)
    turn_state = TurnState()
    for turn_index, question in enumerate(record.dialogue.conv_questions):
        rich_print(f"[bold]turn {turn_index}:[/bold] {question}")
        command = input(">>> (enter to continue, 'exit' to stop) ")
        if command.strip().lower() in {"exit", "quit"}:
            return
        try:
            answer = model_client.answer(record, turn_index, turn_state)
        except ProgramExecutionError:
            rich_print(
                "[yellow]could not get a parseable answer for this turn -- "
                "skipping, not added to conversation history[/yellow]"
            )
            continue
        except FixtureMissError:
            _print_fixture_miss_message()
            raise typer.Exit(code=1) from None
        rich_print(f"[blue][bold]assistant:[/bold] {answer}[/blue]")
        turn_state.add(question, answer)


def _build_chat_client(client: str) -> ModelClient:
    """Construct the `ModelClient` `chat` should use, or fail with a clear `BadParameter`.

    Distinct from `_build_client` (used by `eval`): `chat` additionally offers a keyless
    `fixture` path, and never offers `stub` (an always-wrong predictor has nothing useful
    to show a reviewer talking to `chat`). A missing `ANTHROPIC_API_KEY` exits clean
    (`from_env` already printed the one-line stderr message naming the variable) rather than
    propagating a traceback.
    """
    if client == "anthropic":
        try:
            return AnthropicClient.from_env()
        except MissingApiKeyError:
            raise typer.Exit(code=1) from None
    if client == "fixture":
        return FixtureClient(FIXTURES_DEMO_PATH)
    raise typer.BadParameter(
        f"unsupported --client {client!r}: choose 'anthropic' or 'fixture'"
    )


def _print_fixture_miss_message() -> None:
    """Print a clean, no-traceback message naming which record ids the fixture file covers."""
    raw: dict[str, float | str] = json.loads(FIXTURES_DEMO_PATH.read_text())
    available_record_ids = sorted({key.rsplit(":", 1)[0] for key in raw})
    rich_print(
        "[red]no recorded fixture answer for this record/turn -- available fixture "
        f"record ids: {', '.join(available_record_ids)}[/red]"
    )


def _find_record(
    dataset: dict[str, list[ConvFinQARecord]], record_id: str
) -> ConvFinQARecord:
    """Find `record_id` in either dataset split, or exit cleanly (no traceback) if absent."""
    for split_records in dataset.values():
        for record in split_records:
            if record.id == record_id:
                return record
    rich_print(f"[red]no record found with id {record_id!r}[/red]")
    raise typer.Exit(code=1)


def _build_client(client: str) -> ModelClient:
    """Construct the `ModelClient` named by `--client`, or fail with a clear `BadParameter`.

    A missing `ANTHROPIC_API_KEY` exits clean (`from_env` already printed the one-line
    stderr message naming the variable) rather than propagating a traceback.
    """
    if client == "stub":
        return StubClient()
    if client == "anthropic":
        try:
            return AnthropicClient.from_env()
        except MissingApiKeyError:
            raise typer.Exit(code=1) from None
    raise typer.BadParameter(
        f"unsupported --client {client!r}: choose 'stub' or 'anthropic'"
    )


_VALID_SPLITS = {"train", "dev"}


def _resolve_records(
    dataset: dict[str, list[ConvFinQARecord]],
    client: str,
    split: str,
    limit: int | None,
    confirm_dev_run: bool,
) -> list[ConvFinQARecord]:
    """Validate `--split`/`--limit`/`--confirm-dev-run` and return the records to evaluate.

    `dev` is measured once, at the end of the engagement (`plan.md`'s frozen METRIC
    section) -- this is the one thing in the design that cannot be restored once spent, so
    reaching it with the real client requires two things a default invocation, a reviewer,
    or an accidental re-run would never happen to supply together: an explicit `--limit`
    (real spend is never sized implicitly) and an explicit `--confirm-dev-run` (dev
    specifically, not train, needs a second, separate opt-in). `--split` itself defaults to
    `train` regardless of client, so the *default* invocation of this command can never
    touch `dev` at all, real client or not.
    """
    if split not in _VALID_SPLITS:
        raise typer.BadParameter(
            f"unsupported --split {split!r}: choose 'train' or 'dev'"
        )
    if limit is not None and limit <= 0:
        raise typer.BadParameter(
            f"--limit must be a positive integer, got {limit} -- a zero or negative "
            "value is not 'no records', it slices from the end (Python list slicing), "
            "which can silently select nearly the entire split."
        )
    if client == "anthropic":
        if limit is None:
            raise typer.BadParameter(
                "--client anthropic requires --limit -- this bills real money, so a "
                "sample size must be chosen explicitly, never implied by the full split."
            )
        if split == "dev" and not confirm_dev_run:
            raise typer.BadParameter(
                "--client anthropic --split dev also requires --confirm-dev-run -- dev "
                "is measured once, at the end of the engagement; this flag exists so "
                "that can never happen by accident or by a reviewer's default invocation."
            )
    records = dataset[split]
    return records[:limit] if limit is not None else records


@contextlib.contextmanager
def _open_out(out: Optional[Path]) -> Iterator[Optional[TextIO]]:  # noqa: UP045 -- see --limit's own note above
    """Open `out` in write/truncate mode for the eval run's duration, or yield `None`.

    Truncate-at-start (`"w"`, not `"a"`) is deliberate: a resumed run (same `--out` path,
    same records, same cache dir) overwrites a prior partial file cleanly rather than
    appending duplicate lines for turns already recorded before a crash.
    """
    if out is None:
        yield None
        return
    handle = out.open("w")
    try:
        yield handle
    finally:
        handle.close()


def _build_on_turn(
    model_client: ModelClient,
    start: float,
    out_handle: Optional[TextIO],  # noqa: UP045 -- see --limit's own note above
    cost_cap: Optional[float],  # noqa: UP045 -- see --limit's own note above
) -> Callable[[TurnResult, int, int], None]:
    """Build the `on_turn` callback `eval` passes to `run_eval`.

    Closes over `model_client` (read live for its own cumulative usage attributes, the same
    `getattr(..., 0)` defaulting `eval_runner._read_cumulative_usage` already uses), `start`
    (the wall-clock origin for the elapsed/projected-remaining line), `out_handle` (already
    open, or `None` when `--out` was not given), and `cost_cap` (the one-time warning
    threshold, or `None` to never warn). Never aborts the run itself -- the cost cap is a
    warning, not a limit.
    """
    cap_warned = False

    def on_turn(
        turn_result: TurnResult, scored_total: int, expected_total: int
    ) -> None:
        """Print progress+cost, occasionally elapsed/projected time, flush `--out`, warn once."""
        nonlocal cap_warned
        cost = estimate_cost_usd(
            getattr(model_client, "cumulative_input_tokens", 0),
            getattr(model_client, "cumulative_output_tokens", 0),
            getattr(model_client, "cumulative_cache_creation_tokens", 0),
            getattr(model_client, "cumulative_cache_read_tokens", 0),
        )
        rich_print(
            f"[{scored_total}/{expected_total}] {turn_result.outcome} "
            f"({turn_result.reason}) -- cost so far: ${cost:.4f}"
        )
        if scored_total % _PROGRESS_INTERVAL_TURNS == 0:
            elapsed = time.monotonic() - start
            rate = elapsed / scored_total
            projected_remaining = rate * (expected_total - scored_total)
            rich_print(
                f"[{scored_total}/{expected_total}] elapsed {elapsed:.0f}s, "
                f"projected remaining {projected_remaining:.0f}s"
            )
        if out_handle is not None:
            out_handle.write(json.dumps(dataclasses.asdict(turn_result)) + "\n")
            out_handle.flush()
        if cost_cap is not None and not cap_warned and cost >= cost_cap:
            rich_print(
                f"[bold red]COST CAP CROSSED[/bold red]: ${cost:.4f} >= "
                f"${cost_cap:.2f} cap -- continuing, not aborting"
            )
            cap_warned = True

    return on_turn


@app.command()
def eval(
    client: str = typer.Option(
        "stub", "--client", help="Model client to run against: 'stub' or 'anthropic'."
    ),
    split: str = typer.Option(
        "train",
        "--split",
        help="Dataset split to evaluate: 'train' (default) or 'dev'.",
    ),
    limit: Optional[int] = typer.Option(  # noqa: UP045 -- typer 0.12/click can't resolve `int | None`
        None,
        "--limit",
        help="Evaluate only the first N records of the split. Required with "
        "--client anthropic.",
    ),
    confirm_dev_run: bool = typer.Option(
        False,
        "--confirm-dev-run",
        help="Required in addition to --limit when using --client anthropic --split dev.",
    ),
    out: Optional[Path] = typer.Option(  # noqa: UP045 -- see --limit's own note above
        None,
        "--out",
        help="Write each turn's result as one JSON line to this path, flushed immediately, "
        "as the run progresses. Opened in write/truncate mode once at run start.",
    ),
    cost_cap: Optional[float] = typer.Option(  # noqa: UP045 -- see --limit's own note above
        None,
        "--cost-cap",
        help="Print one one-time warning (never aborts the run) the first time cumulative "
        "estimated cost crosses this USD figure.",
    ),
) -> None:
    """Run the eval loop over a split and print the headline accuracy.

    `--client stub` is a zero-cost pipeline smoke test (an always-wrong predictor).
    `--client anthropic` runs the real Anthropic API end to end and bills real money --
    requires an explicit `--limit`, and `--split dev` additionally requires
    `--confirm-dev-run`, since dev is measured once, at the end of the engagement, and
    that cannot be undone once spent.

    `--out PATH` writes each turn's result as one flushed JSON line as the run progresses,
    so a crash mid-run leaves a real (truncated, not corrupt) results file instead of
    nothing -- opened in write/truncate mode once at the start, so a resumed run (same
    path, same records, same cache dir) overwrites a prior partial file cleanly rather than
    duplicating lines already written before a crash. `--cost-cap USD` prints one one-time
    warning the first time cumulative estimated cost crosses it -- it never aborts the run.
    Progress (one line per turn, plus elapsed/projected-remaining every 100th turn) prints
    regardless of `--out`, so pace and spend are visible on the terminal as the run happens,
    not only in the final summary below.
    """
    dataset = load_dataset(DATA_PATH)
    records = _resolve_records(dataset, client, split, limit, confirm_dev_run)
    model_client = _build_client(client)

    start = time.monotonic()
    with _open_out(out) as out_handle:
        on_turn = _build_on_turn(model_client, start, out_handle, cost_cap)
        summary = run_eval(records, model_client, on_turn=on_turn)

    rich_print(f"total turns: {summary.total_turns}")
    rich_print(
        "strict accuracy: "
        f"{summary.strict_accuracy} ({summary.strict_correct}/{summary.total_turns})"
    )
    rich_print(
        "tolerant accuracy: "
        f"{summary.tolerant_accuracy} ({summary.tolerant_correct}/{summary.total_turns})"
    )
    cost = estimate_cost_usd(
        summary.cumulative_input_tokens,
        summary.cumulative_output_tokens,
        summary.cumulative_cache_creation_tokens,
        summary.cumulative_cache_read_tokens,
    )
    rich_print(
        f"tokens: {summary.cumulative_input_tokens} in / "
        f"{summary.cumulative_output_tokens} out "
        f"(cache write {summary.cumulative_cache_creation_tokens}, "
        f"cache read {summary.cumulative_cache_read_tokens})"
    )
    rich_print(
        f"estimated cost: ${cost:.4f} (rate assumption, see anthropic_client.py)"
    )


if __name__ == "__main__":
    app()
