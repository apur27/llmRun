.PHONY: check check-clean eval-falsify recompute-dev

# Full gate: format, lint (no auto-fix), types, tests, entry point.
# Their pyproject sets [tool.ruff] fix = true, so a bare `ruff check` would rewrite
# files as a side effect of "checking" them. --no-fix keeps this a check, not a fix.
check:
	uv run ruff format --check .
	uv run ruff check --no-fix .
	uv run mypy
	uv run pytest --cov=src --cov-fail-under=0 || test $$? -eq 5
	uv run main --help

# Same steps, intended to be run from a hermetic environment (fresh clone, env -i,
# temp HOME, uv sync). This target does not build that wrapper itself — it is an
# alias for now; the hermetic invocation is exercised manually, outside this file.
check-clean: check

# Falsification check: proves the eval pipeline can drive the headline accuracy to zero
# through the same load_dataset -> run_eval path the real eval will use, via a stub client
# that is wrong by construction on every turn.
eval-falsify:
	uv run python -m src.services.eval_falsify_check

# Recomputes every dev-results figure this report states, straight from the committed artifact
# (results/dev_results.jsonl), importing the real scorer rather than reimplementing it. Keyless,
# offline. Not part of `check`: it verifies one frozen, already-scored measurement, not general
# code health, same reasoning as eval-falsify above -- a separate, deliberate target.
recompute-dev:
	uv run python scripts/recompute_dev.py

harness-check:
	uv run python test/harness_check.py
