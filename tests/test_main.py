"""End-to-end tests for the `main` CLI, the documented entry point (`uv run main ...`)."""

import importlib
import io
import json
import time
from pathlib import Path

import dotenv
import pytest
from typer.testing import CliRunner

import src.main as main_module
from src.adapters.anthropic_client import MissingApiKeyError
from src.domain.executor import ProgramExecutionError
from src.domain.models import ConvFinQARecord
from src.domain.results import TurnResult
from src.main import _build_on_turn, app
from src.services.turn_state import TurnState

runner = CliRunner()

EXPECTED_TOTAL_TURN_COUNT = 1490
REAL_RECORD_ID = "Single_MRO/2007/page_134.pdf-1"
REAL_RECORD_TURN_COUNT = 5


def test_eval_stub_runs_end_to_end_over_the_real_dev_split() -> None:
    """`eval --client stub --split dev` loads the real dev split, prints zero-accuracy.

    `--split dev` is explicit here -- the command's default split is `train` (see the
    dev-guard tests below), so reaching dev at all, even with the free stub client, now
    requires saying so.
    """
    result = runner.invoke(app, ["eval", "--client", "stub", "--split", "dev"])

    assert result.exit_code == 0
    assert str(EXPECTED_TOTAL_TURN_COUNT) in result.stdout
    assert "0/1490" in result.stdout


def test_eval_default_invocation_uses_train_not_dev() -> None:
    """`eval --client stub` with no `--split` runs against train, never dev, by default.

    Checks the denominator (`total turns: 1490` / `.../1490)`), not a bare `"1490"`
    substring: slice 32's per-turn progress line prints the running numerator
    (`scored_total`) for every turn, and train has well over 1490 turns, so the digits
    `1490` pass through as a numerator partway through a full train run regardless of
    split -- that is not evidence dev was touched. The denominator is.
    """
    result = runner.invoke(app, ["eval", "--client", "stub"])

    assert result.exit_code == 0
    assert f"total turns: {EXPECTED_TOTAL_TURN_COUNT}" not in result.stdout
    assert f"/{EXPECTED_TOTAL_TURN_COUNT})" not in result.stdout
    assert "0/1490" not in result.stdout


def test_eval_stub_client_prints_summary_but_no_per_turn_progress() -> None:
    """`--client stub` (a zero-cost, always-wrong smoke test) suppresses per-turn progress.

    The documented keyless reviewer command (`uv run main eval --client stub`) must stay
    readable: the final summary lines are still present, but the per-turn progress line
    (which exists to pace a long, billed `--client anthropic` run) has no purpose here and
    must not print.
    """
    result = runner.invoke(app, ["eval", "--client", "stub", "--limit", "1"])

    assert result.exit_code == 0
    assert "total turns:" in result.stdout
    assert "strict accuracy:" in result.stdout
    assert "-- cost so far:" not in result.stdout
    assert "elapsed" not in result.stdout


def test_eval_rejects_an_unsupported_client() -> None:
    """`eval --client bogus` fails clearly instead of silently pretending to run it."""
    result = runner.invoke(app, ["eval", "--client", "bogus"])

    assert result.exit_code != 0


def test_eval_default_invocation_cannot_reach_dev_with_the_real_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`eval --client anthropic` with no other flags is rejected before touching dev or spend.

    Protects the one thing in the design that cannot be restored once lost: dev is
    measured once, at the end of the engagement. A reviewer or an accidental re-run
    invoking the documented `--client anthropic` flag alone -- no `--split`, no `--limit`,
    no `--confirm-dev-run` -- must be refused, never silently default to a real, full,
    billed run against the protected split. `AnthropicClient.from_env` is monkeypatched to
    fail the test loudly if it is ever reached -- this must be rejected before any client
    is built at all.
    """
    monkeypatch.setattr(
        main_module.AnthropicClient,
        "from_env",
        classmethod(
            lambda _cls: pytest.fail("AnthropicClient.from_env must not be reached")
        ),
    )

    result = runner.invoke(app, ["eval", "--client", "anthropic"])

    assert result.exit_code != 0
    assert "--limit" in result.stdout


def test_eval_client_anthropic_split_dev_without_confirm_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--client anthropic --split dev --limit N` alone is still rejected without confirmation.

    `--limit` bounds spend but is not, by itself, permission to touch the protected split --
    `--confirm-dev-run` is the second, separate opt-in this guards on.
    """
    monkeypatch.setattr(
        main_module.AnthropicClient,
        "from_env",
        classmethod(
            lambda _cls: pytest.fail("AnthropicClient.from_env must not be reached")
        ),
    )

    result = runner.invoke(
        app, ["eval", "--client", "anthropic", "--split", "dev", "--limit", "1"]
    )

    assert result.exit_code != 0
    assert "--confirm-dev-run" in result.stdout


@pytest.mark.parametrize("bad_limit", ["-1", "0", "-100"])
def test_eval_rejects_a_non_positive_limit(
    monkeypatch: pytest.MonkeyPatch, bad_limit: str
) -> None:
    """A zero or negative `--limit` is rejected before any client is built.

    Regression test for a real incident: `records[:limit]` with a negative `limit` is
    Python's from-the-end slice, not "no records" -- `--limit -1` against the 3037-record
    train split silently selected 3036 of them, sailing past the `--limit`-required check
    while never triggering the dev-guard (it wasn't `--split dev`). Caught by review,
    reproduced live, killed mid-run after 46 real API calls before this fix landed.
    """
    monkeypatch.setattr(
        main_module.AnthropicClient,
        "from_env",
        classmethod(
            lambda _cls: pytest.fail("AnthropicClient.from_env must not be reached")
        ),
    )

    result = runner.invoke(app, ["eval", "--client", "anthropic", "--limit", bad_limit])

    assert result.exit_code != 0
    assert "--limit" in result.stdout


def test_eval_out_truncates_at_start_across_two_invocations(tmp_path: Path) -> None:
    """`--out` opens in write/truncate mode once, so a second run overwrites, never appends.

    First invocation: `--limit 2` (8 turns, per the real train split's first 2 records).
    Second invocation, same `--out` path: `--limit 3` (12 turns). The final file must have
    exactly the *second* run's 12 turn-lines, not 8+12=20 -- proving truncate-at-start, not
    append-across-a-resume. Uses `--client stub` (deterministic, always wrong) since the CLI
    has no fake-injection seam; this proves the file-writing mechanism's truncate semantics,
    not the cache-replay guarantee (that is `test_anthropic_client.py`'s
    `test_resume_replays_already_cached_turns_with_zero_new_sdk_calls`).
    """
    out_path = tmp_path / "results.jsonl"

    first = runner.invoke(
        app,
        [
            "eval",
            "--client",
            "stub",
            "--split",
            "train",
            "--limit",
            "2",
            "--out",
            str(out_path),
        ],
    )
    assert first.exit_code == 0
    first_lines = out_path.read_text().splitlines()
    assert len(first_lines) == 8

    second = runner.invoke(
        app,
        [
            "eval",
            "--client",
            "stub",
            "--split",
            "train",
            "--limit",
            "3",
            "--out",
            str(out_path),
        ],
    )
    assert second.exit_code == 0
    final_lines = out_path.read_text().splitlines()

    assert len(final_lines) == 12  # the second run's own turn count, not 8 + 12
    for line in final_lines:
        parsed = json.loads(line)
        assert set(parsed) == {
            "record_id",
            "turn_index",
            "turn_program",
            "gold",
            "predicted",
            "outcome",
            "reason",
            "scale_flip",
        }


class _UsageStandInClient:
    """A `ModelClient` stand-in exposing mutable cumulative usage attributes for `on_turn` tests."""

    def __init__(self) -> None:
        """Start at zero usage -- tests mutate the attributes directly between `on_turn` calls."""
        self.cumulative_input_tokens = 0
        self.cumulative_output_tokens = 0
        self.cumulative_cache_creation_tokens = 0
        self.cumulative_cache_read_tokens = 0

    def answer(
        self, record: ConvFinQARecord, turn_index: int, turn_state: TurnState
    ) -> float | str:
        """Never called -- these tests drive `on_turn` directly, not through `run_eval`."""
        raise NotImplementedError


def _turn_result(turn_index: int) -> TurnResult:
    """A minimal always-correct `TurnResult`, for `on_turn` unit tests that ignore its content."""
    return TurnResult(
        record_id="Single_TEST/2020/page_1.pdf-1",
        turn_index=turn_index,
        turn_program="1.0",
        gold=1.0,
        predicted=1.0,
        outcome="correct",
        reason="ok",
        scale_flip=False,
    )


def test_build_on_turn_prints_elapsed_projected_only_on_the_100th_turn(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The elapsed/projected-remaining line prints exactly at scored turn 100 and 200, nowhere else."""
    on_turn = _build_on_turn(
        _UsageStandInClient(), start=time.monotonic(), out_handle=None, cost_cap=None
    )

    for scored in range(1, 201):
        on_turn(_turn_result(scored - 1), scored, 500)

    output = capsys.readouterr().out
    assert output.count("elapsed") == 2
    assert "[100/500] elapsed" in output
    assert "[200/500] elapsed" in output


def test_build_on_turn_warns_cost_cap_exactly_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Crossing `--cost-cap` prints one warning, even though later turns stay above the cap too."""
    client = _UsageStandInClient()
    on_turn = _build_on_turn(
        client, start=time.monotonic(), out_handle=None, cost_cap=0.001
    )

    client.cumulative_input_tokens = (
        10_000  # cost = 10000 * $1/1e6 = $0.01 >= $0.001 cap
    )
    on_turn(_turn_result(0), 1, 5)
    on_turn(_turn_result(1), 2, 5)
    client.cumulative_input_tokens = 20_000  # cost climbs further, still above the cap
    on_turn(_turn_result(2), 3, 5)

    output = capsys.readouterr().out
    assert output.count("COST CAP CROSSED") == 1


def test_build_on_turn_never_warns_when_cost_cap_is_none(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Omitting `--cost-cap` (the default) never prints the warning, no matter the cost."""
    client = _UsageStandInClient()
    client.cumulative_input_tokens = 1_000_000
    on_turn = _build_on_turn(
        client, start=time.monotonic(), out_handle=None, cost_cap=None
    )

    on_turn(_turn_result(0), 1, 5)

    assert "COST CAP CROSSED" not in capsys.readouterr().out


def test_build_on_turn_show_progress_false_suppresses_progress_and_elapsed_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`show_progress=False` prints nothing per-turn, but `--out`/`--cost-cap` still fire.

    Proves the `show_progress` gate wraps only the per-turn progress and elapsed/projected
    lines, leaving `--out` file writes and the `--cost-cap` warning -- both unconditional --
    completely untouched.
    """
    client = _UsageStandInClient()
    client.cumulative_input_tokens = 10_000  # cost $0.01 >= $0.001 cap
    out_handle = io.StringIO()
    on_turn = _build_on_turn(
        client,
        start=time.monotonic(),
        out_handle=out_handle,
        cost_cap=0.001,
        show_progress=False,
    )

    for scored in range(1, 101):  # crosses the 100th-turn elapsed/projected boundary
        on_turn(_turn_result(scored - 1), scored, 500)

    output = capsys.readouterr().out
    assert "cost so far" not in output
    assert "elapsed" not in output
    assert output.count("COST CAP CROSSED") == 1
    assert len(out_handle.getvalue().splitlines()) == 100


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


FIXTURE_RECORD_ID = "Single_SLG/2013/page_133.pdf-4"
FIXTURE_RECORD_TURN_COUNT = 4


def test_chat_client_fixture_walks_all_turns_with_real_recorded_answers() -> None:
    """`chat --client fixture` replays real recorded answers with no key or network.

    Deliberately does not monkeypatch `AnthropicClient.from_env` -- if `--client fixture`
    is wired correctly, that path is never touched.
    """
    result = runner.invoke(
        app,
        ["chat", FIXTURE_RECORD_ID, "--client", "fixture"],
        input="\n" * FIXTURE_RECORD_TURN_COUNT,
    )

    assert result.exit_code == 0
    for expected_value in ("4.5", "4.1", "8.6", "12.0"):
        assert expected_value in result.stdout


def test_chat_client_fixture_unknown_record_names_available_fixtures() -> None:
    """A real record id absent from the fixture file exits clean, naming what is available.

    `REAL_RECORD_ID` exists in the dataset (so `_find_record` succeeds) but has no entry
    in `data/reviewer_demo_fixtures.json` -- this exercises `FixtureMissError`, not the
    unknown-record-id path (already covered by `test_chat_exits_cleanly_for_an_unknown_record_id`).
    """
    result = runner.invoke(
        app,
        ["chat", REAL_RECORD_ID, "--client", "fixture"],
        input="\n",
    )

    assert result.exit_code != 0
    assert "Traceback" not in result.stdout
    assert FIXTURE_RECORD_ID in result.stdout


def test_chat_rejects_an_unsupported_client() -> None:
    """`chat --client bogus` fails clearly instead of silently pretending to run it."""
    result = runner.invoke(app, ["chat", FIXTURE_RECORD_ID, "--client", "bogus"])

    assert result.exit_code != 0


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
    """`--client anthropic --limit N` (train, the default split) builds a real `AnthropicClient`.

    `--limit` is required for `--client anthropic` (see the dev-guard tests above) -- this is
    the smallest invocation that legitimately reaches client construction.
    """
    built: dict[str, bool] = {}

    def _fake_from_env() -> _FakeAnthropicEvalClient:
        built["called"] = True
        return _FakeAnthropicEvalClient()

    monkeypatch.setattr(
        main_module.AnthropicClient,
        "from_env",
        classmethod(lambda _cls: _fake_from_env()),
    )

    result = runner.invoke(app, ["eval", "--client", "anthropic", "--limit", "1"])

    assert result.exit_code == 0
    assert built.get("called") is True


def test_eval_client_anthropic_still_prints_per_turn_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--client anthropic` keeps the per-turn progress line -- only `stub` suppresses it.

    A real, billed run still needs pacing on the terminal; the suppression added for the
    keyless `stub` reviewer command must not silently remove it here too.
    """
    monkeypatch.setattr(
        main_module.AnthropicClient,
        "from_env",
        classmethod(lambda _cls: _FakeAnthropicEvalClient()),
    )

    result = runner.invoke(app, ["eval", "--client", "anthropic", "--limit", "1"])

    assert result.exit_code == 0
    assert "-- cost so far:" in result.stdout


def test_eval_client_anthropic_exits_cleanly_with_no_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`eval --client anthropic --limit N` with no key prints one message, never a traceback.

    `--limit` is included so this test actually reaches `from_env` (and exercises the
    missing-key path it's named for) rather than failing earlier on the dev-guard check.
    """

    def _raise() -> None:
        raise MissingApiKeyError("ANTHROPIC_API_KEY environment variable is not set")

    monkeypatch.setattr(
        main_module.AnthropicClient, "from_env", classmethod(lambda _cls: _raise())
    )

    result = runner.invoke(app, ["eval", "--client", "anthropic", "--limit", "1"])

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
