"""End-to-end tests for the `main` CLI, the documented entry point (`uv run main ...`)."""

import importlib

import dotenv
import pytest
from typer.testing import CliRunner

import src.main as main_module
from src.adapters.anthropic_client import MissingApiKeyError
from src.domain.executor import ProgramExecutionError
from src.domain.models import ConvFinQARecord
from src.main import app
from src.services.turn_state import TurnState

runner = CliRunner()

EXPECTED_TOTAL_TURN_COUNT = 1490
REAL_RECORD_ID = "Single_MRO/2007/page_134.pdf-1"
REAL_RECORD_TURN_COUNT = 5


def test_eval_stub_runs_end_to_end_over_the_real_dev_split() -> None:
    """`eval --client stub` loads the real dev split and prints the zero-accuracy headline."""
    result = runner.invoke(app, ["eval", "--client", "stub"])

    assert result.exit_code == 0
    assert str(EXPECTED_TOTAL_TURN_COUNT) in result.stdout
    assert "0/1490" in result.stdout


def test_eval_rejects_an_unsupported_client() -> None:
    """`eval --client bogus` fails clearly instead of silently pretending to run it."""
    result = runner.invoke(app, ["eval", "--client", "bogus"])

    assert result.exit_code != 0


class _FakeChatClient:
    """A `ModelClient` returning one canned answer per turn index, for `chat`'s CLI test."""

    def __init__(self, answers: list[float | str]) -> None:
        """Queue `answers`, one per `turn_index`, in order."""
        self._answers = answers

    def answer(
        self, record: ConvFinQARecord, turn_index: int, turn_state: TurnState
    ) -> float | str:
        """Return the queued answer for `turn_index`, ignoring `record`/`turn_state`."""
        return self._answers[turn_index]


def test_chat_walks_the_records_own_questions_and_prints_real_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`chat` asks each of a record's scripted questions in order and prints the answer."""
    answers: list[float | str] = [1.0, 2.0, 3.0, 4.0, 5.0]
    fake_client = _FakeChatClient(answers)
    monkeypatch.setattr(
        main_module.AnthropicClient, "from_env", classmethod(lambda _cls: fake_client)
    )

    result = runner.invoke(
        app, ["chat", REAL_RECORD_ID], input="\n" * REAL_RECORD_TURN_COUNT
    )

    assert result.exit_code == 0
    assert "turn 0:" in result.stdout
    assert "1.0" in result.stdout
    assert "5.0" in result.stdout


def test_chat_stops_early_when_the_user_types_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typing `exit` stops the session before asking the remaining turns' questions."""
    fake_client = _FakeChatClient([1.0, 2.0, 3.0, 4.0, 5.0])
    monkeypatch.setattr(
        main_module.AnthropicClient, "from_env", classmethod(lambda _cls: fake_client)
    )

    result = runner.invoke(app, ["chat", REAL_RECORD_ID], input="exit\n")

    assert result.exit_code == 0
    assert "turn 1:" not in result.stdout


def test_chat_exits_cleanly_for_an_unknown_record_id() -> None:
    """An unknown `record_id` exits non-zero with a clear message, not a traceback."""
    result = runner.invoke(app, ["chat", "does-not-exist"], input="")

    assert result.exit_code != 0
    assert "does-not-exist" in result.stdout


def test_chat_exits_cleanly_with_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing `ANTHROPIC_API_KEY` prints one clean message, never a traceback.

    This is a reviewer's first interaction with the submission -- their README documents
    only this command, and they have no key for this project's Anthropic account.
    """

    def _raise() -> None:
        raise MissingApiKeyError("ANTHROPIC_API_KEY environment variable is not set")

    monkeypatch.setattr(
        main_module.AnthropicClient, "from_env", classmethod(lambda _cls: _raise())
    )

    result = runner.invoke(app, ["chat", REAL_RECORD_ID], input="")

    assert result.exit_code != 0
    assert "Traceback" not in result.stdout
    assert "MissingApiKeyError" not in result.stdout


class _RefusesSecondTurnClient:
    """A `ModelClient` that raises `ProgramExecutionError` on turn 1, answers otherwise."""

    def answer(
        self, record: ConvFinQARecord, turn_index: int, turn_state: TurnState
    ) -> float | str:
        """Raise on turn 1 (simulating an unparseable refusal), else return a fixed value."""
        if turn_index == 1:
            raise ProgramExecutionError("could not parse a final answer")
        return 1.0


def test_chat_continues_past_a_turn_the_model_cannot_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn raising `ProgramExecutionError` prints a clean message and the session continues.

    Demonstrated on real data in slice 16's regression check (JPM t1 refuses even after one
    repair attempt) -- this is not a hypothetical failure mode.
    """
    fake_client = _RefusesSecondTurnClient()
    monkeypatch.setattr(
        main_module.AnthropicClient, "from_env", classmethod(lambda _cls: fake_client)
    )

    result = runner.invoke(
        app, ["chat", REAL_RECORD_ID], input="\n" * REAL_RECORD_TURN_COUNT
    )

    assert result.exit_code == 0
    assert "Traceback" not in result.stdout
    assert "could not get a parseable answer" in result.stdout
    assert "turn 2:" in result.stdout  # session continued past the failed turn 1


class _FakeAnthropicEvalClient:
    """A `ModelClient` standing in for `AnthropicClient` in the `--client anthropic` wiring test."""

    def __init__(self) -> None:
        """Track nothing; always answers the same value."""

    def answer(
        self, record: ConvFinQARecord, turn_index: int, turn_state: TurnState
    ) -> float | str:
        """Return a constant prediction, never used for a real measurement."""
        return 0.0


def test_eval_client_anthropic_constructs_the_real_client_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--client anthropic` builds an `AnthropicClient`, not a silent fallback to stub."""
    built: dict[str, bool] = {}

    def _fake_from_env() -> _FakeAnthropicEvalClient:
        built["called"] = True
        return _FakeAnthropicEvalClient()

    monkeypatch.setattr(
        main_module.AnthropicClient,
        "from_env",
        classmethod(lambda _cls: _fake_from_env()),
    )

    result = runner.invoke(app, ["eval", "--client", "anthropic"])

    assert result.exit_code == 0
    assert built.get("called") is True


def test_eval_client_anthropic_exits_cleanly_with_no_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`eval --client anthropic` with no key prints one message, never a traceback."""

    def _raise() -> None:
        raise MissingApiKeyError("ANTHROPIC_API_KEY environment variable is not set")

    monkeypatch.setattr(
        main_module.AnthropicClient, "from_env", classmethod(lambda _cls: _raise())
    )

    result = runner.invoke(app, ["eval", "--client", "anthropic"])

    assert result.exit_code != 0
    assert "Traceback" not in result.stdout
    assert "MissingApiKeyError" not in result.stdout


def test_main_module_loads_dotenv_at_import_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing `src.main` calls `load_dotenv()`, so `.env` alone is enough for `from_env`."""
    calls: list[bool] = []
    monkeypatch.setattr(dotenv, "load_dotenv", lambda: calls.append(True))

    importlib.reload(main_module)

    assert calls == [True]
