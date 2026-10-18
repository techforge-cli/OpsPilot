# OpsPilot

Linux server administration assistant for Debian-family servers. OpsPilot collects
native Linux metrics, sends a compact snapshot to a local Ollama model through
the OpenAI-compatible API, and can run governed remediation playbooks with a
safety guard, verifier, and permanent audit trail.

## Features

- Native metric collection via Linux tools and `/proc`
- Strict JSON analysis from a local Ollama model
- Bundled read-only playbooks plus admin-created custom playbooks
- Safety guard before every remediation or verifier execution
- Incident lifecycle with one final recommendation-only follow-up when unresolved
- FastAPI + HTMX dashboard for status, incidents, playbooks, hosts, and audit
- SQLite storage with append-only JSONL audit journal
- Optional SSH host execution

## Quick Start

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
export OPSPILOT_DATA_DIR=/var/lib/opspilot
export OPSPILOT_ADMIN_PASSWORD='change-me'
opspilot --config-check
opspilot
```

Open `http://127.0.0.1:8443/` by default.

## Configuration

Common environment variables:

| Variable | Default | Purpose |
|---|---:|---|
| `OPSPILOT_ADMIN_PASSWORD` | empty | Enables admin web mode |
| `OPSPILOT_BIND_HOST` | `127.0.0.1` | Bind address |
| `OPSPILOT_BIND_PORT` | `8443` | Bind port |
| `OPSPILOT_DATA_DIR` | `/var/lib/opspilot` | SQLite and audit data |
| `OPSPILOT_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama endpoint |
| `OPSPILOT_OLLAMA_MODEL` | `qwen2.5:7b` | Model name |
| `OPSPILOT_INTERVAL_SECONDS` | `30` | Collection interval |
| `OPSPILOT_GLOBAL_AUTO_MODE` | `false` | Enables auto execution |
| `OPSPILOT_SSH_KEY_PATH` | `/etc/opspilot/operator.key` | SSH key for managed hosts |

## Development

```bash
pip install -e '.[dev]'
PYTHONPATH=src pytest -q
ruff check .
```

## Architecture

OpsPilot is intentionally one FastAPI process: scheduler, collector, analyzer,
playbook registry, safety guard, executor, incidents, audit, and HTMX dashboard
share one SQLite database and one audit journal.

## Safety

Remediation only runs from the playbook catalog. The safety guard blocks
dangerous command patterns, enforces timeouts, and can require confirmation.
Bundled playbooks are read-only; custom playbooks create immutable revisions.

## License

MIT
