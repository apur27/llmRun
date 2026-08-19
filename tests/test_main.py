"""End-to-end tests for the `main` CLI, the documented entry point (`uv run main ...`)."""

from typer.testing import CliRunner

from src.main import app

runner = CliRunner()

EXPECTED_TOTAL_TURN_COUNT = 1490


def test_eval_stub_runs_end_to_end_over_the_real_dev_split() -> None:
    """`eval --client stub` loads the real dev split and prints the zero-accuracy headline."""
    result = runner.invoke(app, ["eval", "--client", "stub"])

    assert result.exit_code == 0
    assert str(EXPECTED_TOTAL_TURN_COUNT) in result.stdout
    assert "0/1490" in result.stdout


def test_eval_rejects_an_unsupported_client() -> None:
    """`eval --client anthropic` fails clearly instead of silently pretending to run it."""
    result = runner.invoke(app, ["eval", "--client", "anthropic"])

    assert result.exit_code != 0
