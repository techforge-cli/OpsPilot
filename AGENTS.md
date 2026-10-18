# AGENTS.md

Quick orientation for AI agents working in this repo. Read this first, then the README.

## Project

OpsPilot: a Linux server administration assistant. Collects native metrics, sends snapshots to a local Ollama model (OpenAI-compatible API), and runs governed remediation playbooks with a safety guard, verifier, and append-only audit trail. FastAPI + HTMX dashboard, SQLite storage.

Single-process architecture: scheduler, collector, analyzer, playbook registry, safety guard, executor, incidents, audit, and dashboard share one SQLite DB and one audit journal.

## Commands

```bash
# Install (editable + dev tools)
pip install -e '.[dev]'

# Lint
ruff check .

# Test
PYTHONPATH=src pytest -q
pytest tests/test_analyzer.py::test_something   # single test

# Run
opspilot --config-check          # validate env, create data dir, exit
opspilot                         # start on 127.0.0.1:8443
opspilot --host 0.0.0.0 --port 8080
```

CI (Python 3.14, ubuntu-latest) runs `ruff check .` then `PYTHONPATH=src pytest -q`. No ruff config file exists — it uses defaults.

## Environment Variables

All env vars use the `OPSPILOT_` prefix (case-insensitive, via pydantic-settings).

| Variable | Default | Purpose |
|---|---|---|
| `OPSPILOT_ADMIN_PASSWORD` | empty | Empty = read-only web mode (confirm/dismiss returns 403, scheduler still runs) |
| `OPSPILOT_DATA_DIR` | `/var/lib/opspilot` | SQLite + audit journal location |
| `OPSPILOT_BIND_HOST` / `OPSPILOT_BIND_PORT` | `127.0.0.1` / `8443` | Bind address |
| `OPSPILOT_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama endpoint |
| `OPSPILOT_OLLAMA_MODEL` | `qwen2.5:7b` | Model name |
| `OPSPILOT_GLOBAL_AUTO_MODE` | `false` | Enable auto-tier playbook execution |

## Layout

- `src/opspilot/` — package root (installed via `package-dir = {"" = "src"}`)
- `tests/` — pytest suite (16 modules, `asyncio_mode = "auto"`)
- `opspilot/playbooks/builtin/` — git-tracked source for builtin playbooks; copied into `src/opspilot/playbooks/builtin/` at install time via `data-files`
- `docs/`, `handover/`, `marketing-pages/`, `mockups/` — gitignored scratch dirs
- `site/` — GitHub Pages deploy artifact (source in `docs/`, built to `site/`)

## Key Conventions

- Python ≥ 3.11; CI uses 3.14.
- `pythonpath = ["src"]` in pytest config — tests import `opspilot.*` directly.
- Entry point: `opspilot = "opspilot.__main__:main"`.
- Builtin playbooks are read-only; custom playbook authoring is not yet supported.
- Confirmations are single-flight: first POST transitions to `executing`, concurrent/repeated calls get 409.

## Pages Deploy

`.github/workflows/pages.yml` builds `docs/` → `site/` and deploys to GitHub Pages on push to `main`.
