"""
Main typer app for ConvFinQA
"""

from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich import print as rich_print

from src.adapters.anthropic_client import AnthropicClient, MissingApiKeyError
from src.adapters.ports import ModelClient
from src.adapters.stub_client import StubClient
from src.domain.executor import ProgramExecutionError
from src.domain.loader import load_dataset
from src.domain.models import ConvFinQARecord
from src.services.eval_runner import run_eval
from src.services.turn_state import TurnState

# Loaded once, early, before any command builds a real client -- `AnthropicClient.from_env()`
# reads `ANTHROPIC_API_KEY` from `os.environ`, and nothing else in this CLI's import graph
# loads `.env` (`src/logger.py` does, but nothing here imports it). A no-op when `.env` is
# absent or the key is already exported in the shell.
load_dotenv()

app = typer.Typer(
    name="main",
    help="Boilerplate app for ConvFinQA",
    add_completion=True,
    no_args_is_help=True,
)

DATA_PATH = Path(__file__).parent.parent / "data" / "convfinqa_dataset.json"


@app.command()
def chat(
    record_id: str = typer.Argument(..., help="ID of the record to chat about"),
) -> None:
    """Walk one record's own questions, in order, against the real Anthropic client.

    Not free-text chat: `AnthropicClient.answer()` is keyed to a record's own
    `conv_questions[turn_index]`, not arbitrary text, so this command asks each turn's
    scripted question in order and prints the model's real answer -- press enter to see the
    next turn, or type `exit`/`quit` to stop early. Each turn's (question, model's own
    answer) is appended to a session `TurnState`, so a later turn's client sees prior history
    exactly like `run_eval` does.

    Fails clean, never a traceback: a missing `ANTHROPIC_API_KEY` (no ambient export, no
    `.env`) or a turn the model cannot answer even after one repair attempt both print one
    plain message and exit/continue rather than dumping a stack trace -- this is a reviewer's
    first interaction with the submission and their README documents exactly this command.
    """
    dataset = load_dataset(DATA_PATH)
    record = _find_record(dataset, record_id)
    try:
        client = AnthropicClient.from_env()
    except MissingApiKeyError:
        raise typer.Exit(code=1) from None
    turn_state = TurnState()
    for turn_index, question in enumerate(record.dialogue.conv_questions):
        rich_print(f"[bold]turn {turn_index}:[/bold] {question}")
        command = input(">>> (enter to continue, 'exit' to stop) ")
        if command.strip().lower() in {"exit", "quit"}:
            return
        try:
            answer = client.answer(record, turn_index, turn_state)
        except ProgramExecutionError:
            rich_print(
                "[yellow]could not get a parseable answer for this turn -- "
                "skipping, not added to conversation history[/yellow]"
            )
            continue
        rich_print(f"[blue][bold]assistant:[/bold] {answer}[/blue]")
        turn_state.add(question, answer)


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
) -> None:
    """Run the eval loop over a split and print the headline accuracy.

    `--client stub` is a zero-cost pipeline smoke test (an always-wrong predictor).
    `--client anthropic` runs the real Anthropic API end to end and bills real money --
    requires an explicit `--limit`, and `--split dev` additionally requires
    `--confirm-dev-run`, since dev is measured once, at the end of the engagement, and
    that cannot be undone once spent.
    """
    dataset = load_dataset(DATA_PATH)
    records = _resolve_records(dataset, client, split, limit, confirm_dev_run)
    model_client = _build_client(client)
    summary = run_eval(records, model_client)

    rich_print(f"total turns: {summary.total_turns}")
    rich_print(
        "strict accuracy: "
        f"{summary.strict_accuracy} ({summary.strict_correct}/{summary.total_turns})"
    )
    rich_print(
        "tolerant accuracy: "
        f"{summary.tolerant_accuracy} ({summary.tolerant_correct}/{summary.total_turns})"
    )


@app.command()
def myfunc() -> None:
    """My hello world function"""
    # TODO: YOUR CODE HERE
    rich_print("Hello World")


if __name__ == "__main__":
    app()
