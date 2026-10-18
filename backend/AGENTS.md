# Backend (FastAPI + deepagents)

Python 3.12, managed with `uv`. Dependencies are in `pyproject.toml` / `uv.lock`; ask before adding any.

## Layout

- `app/main.py` - FastAPI app and routes.
- `app/__init__.py` - package marker.
- `tests/` - pytest. Rule logic must be testable with no live model calls.
- `.env.example` - env var template (`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`). Never commit `.env`.

## Commands

- Run: `uv run poe backend`
- Test: `uv run poe test`
- Lint: `uv run poe lint`
- Lint + tests: `uv run poe check`
- Tasks live in `[tool.poe.tasks]` in `pyproject.toml`.

## Rules

- Rule evaluation (R1-R5) lives in plain Python with no LLM calls, and is unit-tested.
- LLM (via deepagents) is only for field extraction and the narrative outputs.
- Extraction output must carry evidence per value: `source_file`, `locator`, `excerpt_or_observation`.
- Field states: `KNOWN`, `MISSING`, `CONFLICT`, `INVALID` (see `field_specification.json`).
- Schedule vehicle count is derived in code from the CSV (nonblank rows, header excluded), not by the LLM.
- Required tests: missing info, source conflict, unequal vehicle counts, 150 vs 150.1 mile threshold.
- Enable CORS only for the frontend origin (`http://localhost:3000`).
