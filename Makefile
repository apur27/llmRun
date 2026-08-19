.PHONY: check check-clean

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
