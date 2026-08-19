"""
Main typer app for ConvFinQA
"""

from pathlib import Path

import typer
from rich import print as rich_print

from src.adapters.stub_client import StubClient
from src.domain.loader import load_dataset
from src.services.eval_runner import run_eval

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
    """Ask questions about a specific record"""
    history = []
    while True:
        message = input(">>> ")

        if message.strip().lower() in {"exit", "quit"}:
            break

        # TODO: YOUR CODE HERE
        response = "RESPONSE"
        rich_print(f"[blue][bold]assistant:[/bold] {response}[/blue]")
        history.append({"user": message, "assistant": response})


@app.command()
def eval(
    client: str = typer.Option(
        "stub", "--client", help="Model client to run against: only 'stub' works today."
    ),
) -> None:
    """Run the eval loop over the dev split and print the headline accuracy.

    Zero-cost pipeline smoke test: `--client stub` is the only supported value in this slice,
    since the real Anthropic client does not exist yet.
    """
    if client != "stub":
        raise typer.BadParameter(
            f"unsupported --client {client!r}: only 'stub' is implemented so far"
        )

    dataset = load_dataset(DATA_PATH)
    summary = run_eval(dataset["dev"], StubClient())

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
