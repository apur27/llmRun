"""
Main typer app for ConvFinQA
"""

from pathlib import Path

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


@app.command()
def eval(
    client: str = typer.Option(
        "stub", "--client", help="Model client to run against: 'stub' or 'anthropic'."
    ),
) -> None:
    """Run the eval loop over the dev split and print the headline accuracy.

    `--client stub` is a zero-cost pipeline smoke test (an always-wrong predictor).
    `--client anthropic` runs the real Anthropic API end to end and bills real money --
    intended for a small, deliberately sized sample, not routinely against the full dev
    split.
    """
    model_client = _build_client(client)
    dataset = load_dataset(DATA_PATH)
    summary = run_eval(dataset["dev"], model_client)

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
