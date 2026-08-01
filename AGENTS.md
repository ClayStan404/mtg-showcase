# Repository Guidelines

## Project Structure & Module Organization

The public site is a vanilla HTML/CSS/JavaScript application. `index.html` is the
storefront, `assets/` contains browser code, and `admin/` contains the
Supabase-backed management UI. Python utilities in `scripts/` export data,
enrich card metadata, create snapshots, and manage backups. Tests live in
`tests/` and `tests-js/`. Supabase config, migrations, and the Edge Function are
under `supabase/`; workflows are in `.github/workflows/`.

Generated or local-only directories such as `data/`, `inventory/`, `wants/`,
`.cache/`, and `site/` are ignored; do not commit their contents.

## Build, Test, and Development Commands

Install development dependencies in an isolated environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
npm ci
```

- `python3 -m http.server 8000` serves the repository for local browser testing.
- `python3 scripts/build_data.py --validate-only` validates local inventory input
  without calling card APIs.
- `python3 scripts/build_data.py` and `python3 scripts/build_wants.py` generate
  enriched snapshots; they require local inputs and network access.
- `ruff check scripts/ tests/` runs the CI lint rules.
- `python3 -m pytest tests/ -q` runs the complete test suite.
- `npm run test:js` tests the shared browser import parser.
- `npm run check:edge` bundles the Edge Function as a compatibility check.

## Coding Style & Naming Conventions

Use four spaces and `snake_case` for Python functions, modules, and variables;
use `PascalCase` for classes. Ruff targets Python 3.10, sorts imports, and checks
`E`, `F`, `W`, `I`, and `UP`; its configured line length is 100. Follow existing
frontend style: two-space indentation, double-quoted JavaScript strings,
semicolons, and kebab-case CSS classes. Keep comments focused on non-obvious
data or deployment behavior.

## Testing Guidelines

Pytest discovers `tests/test_*.py`; Node discovers `tests-js/*.test.js`.
Name Python test functions `test_<behavior>`.
Add focused regression tests when changing parsers, exports, cache behavior, or
snapshot formats. Use `tmp_path` and `monkeypatch` to isolate files and network
clients. No coverage threshold is configured; exercise changed branches and
failures.

## Commit & Pull Request Guidelines

Recent history primarily uses Conventional Commit subjects such as `fix: ...`,
`feat: ...`, `docs: ...`, and scoped forms like `fix(admin): ...`. Keep subjects
imperative and narrowly focused. Pull requests should explain the user-visible
effect, list verification commands, link relevant issues, and include before/after
screenshots for UI changes. Call out workflow, schema, or snapshot-format changes.

## Security & Configuration

Never commit `SUPABASE_SERVICE_ROLE_KEY`, backups, caches, or exported user data.
Treat `site_config.json` as public browser configuration. Test write-capable
import and restore scripts in their default dry-run mode before using `--apply`.
