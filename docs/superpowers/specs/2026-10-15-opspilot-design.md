# OpsPilot — Linux Server Administration Assistant

Status: approved design, pre-implementation spec.
Date: 2026-10-15.

## Overview

OpsPilot is a Python service for Debian-family servers. It collects server health and performance metrics using Linux native tools, normalizes them into a compact snapshot, sends the snapshot to a local Ollama model through the OpenAI-compatible `/v1/chat/completions` API, and receives a structured diagnosis. The model may identify an issue and return a `playbook_id` and `verifier_id` from a governed catalog. OpsPilot validates the selected playbook through a safety guard, runs it if safe, then runs the verifier and metric recheck. Unresolved cases are explained once more by the model as a recommendation only.

Phase 1 runs on a central admin box and administers itself plus additional hosts over SSH. A single-operator HTMX web dashboard provides status, incidents, playbook management, audit review, and confirmation controls.

## Goals and Non-goals

Goals:

- Native Linux metrics only; no remote agent required on managed hosts.
- Strict JSON model output validated with Pydantic.
- Model never returns executable text, only catalog IDs.
- Safety guard is the final pre-execution authority.
- Permanent local audit and SQLite data.
- HTMX dashboard in the same FastAPI process.
- Bundled read-only playbooks and admin-created mutable playbooks.

Non-goals in Phase 1:

- Multi-tenant user management beyond one admin password.
- HA, federation, or cloud API.
- Arbitrary ad-hoc shell execution outside the playbook catalog.
- Kernel/eBPF agents or external metric stacks.

## Architecture

Approach A: one FastAPI monolith.

Major runtime components:

1. `scheduler`: `APScheduler` collects snapshots every 30 seconds.
2. `hosts`: inventory of local and SSH-accessible targets.
3. `collector`: registry of metric collectors that run native commands and parse output.
4. `normalizer`: builds the canonical snapshot JSON.
5. `analyzer`: Ollama/OpenAI-compatible client and strict-response validation.
6. `playbooks`: YAML catalog, revisions, editor service.
7. `safety`: policy validator for commands, paths, risk, and host scope.
8. `executor`: playbook step runner and verifier runner.
9. `incidents`: lifecycle and post-run recommendation handling.
10. `storage`: SQLite tables, audit JSONL writer, retention helper.
11. `web`: FastAPI + Jinja2 + HTMX pages and fragments.

Process communication is in-process. PostgreSQL is not used; SQLite with WAL is sufficient for Phase 1 and avoids another service dependency.

## Host Management

- Hosts are stored in `hosts`.
- `execution_mode`: `local` or `ssh`.
- SSH hosts use a configured private key path and system `ssh` executable; private key material is never stored in SQLite.
- Every playbook run records the `host_id`.
- Host name, address, and key path are operator-configured; OpsPilot does not generate SSH keys.

## Metrics Collection

Collectors gather:

- CPU and load: `procps`/`/proc/loadavg`, `uptime`, per-core data from `/proc/stat`
- Memory and swap: `/proc/meminfo`
- Disk usage: `df -B1 -P`
- Disk I/O: `/proc/diskstats` deltas
- Network: `/proc/net/dev` deltas, interface status from `ip -json link` when available
- Processes: `ps -eo pid,ppid,user,%cpu,%mem,comm,args --sort=-%cpu`
- Services: `systemctl --no-pager --plain` output for configured units
- Logs: bounded `journalctl --since` error/panic lines for configured units and kernel
- Thermal and hardware when available: `/sys/class/thermal`, SMART only if configured and permitted

A snapshot has this shape:

```json
{
  "id": "uuid",
  "host_id": "host-id",
  "collected_at": "iso-8601",
  "interval_seconds": 30,
  "metrics": {"cpu": {}, "memory": {}, "disk": {}, "network": {}},
  "processes": [],
  "services": [],
  "recent_errors": []
}
```

Raw snapshots older than 7 days are rolled up into hourly aggregates and then removed. Hourly aggregates are retained for 90 days. Audit and incident data are retained permanently unless the operator exports and archives them.

## LLM Contract

OpsPilot calls only Ollama's OpenAI-compatible API with:

- configured base URL
- configured model
- no tools; plain chat completion
- `response_format` or JSON-mode prompting as supported by the configured model
- strict Pydantic response validation

Response schema:

```json
{
  "status": "ok | issue",
  "severity": "info | warning | critical",
  "explanation": "string",
  "confidence": 0.0,
  "issue_id": "string",
  "playbook_id": "string or null",
  "verifier_id": "string or null",
  "recommended": false
}
```

Rules:

- `playbook_id` and `verifier_id` must exist in the catalog.
- If `status` is `ok`, both IDs are null.
- The analyzer does not accept or parse shell output from the model.
- Invalid JSON or unknown IDs cause one retry; a second failure is logged as `analysis_failed`.
- On unresolved verifier failure, the second model call uses schema `{ status, explanation, recommended_playbook_id nullable, recommended_verifier_id nullable }` and `recommended` is true; no execution occurs.

## Playbook Format

`Playbook` and `Verifier` are YAML documents with immutable revisions stored in `playbook_revisions`.

```yaml
id: restart-docker-unhealthy
name: Restart unhealthy Docker service
description: Restarts a systemd service and verifies health.
risk: confirm
auto_run: false
applies_to:
  issue_ids:
    - docker_service_unhealthy
  hosts:
    tags:
      - docker
preconditions:
  - command: test -x /usr/bin/systemctl
steps:
  - id: restart
    command: systemctl restart docker
    timeout_seconds: 60
    idempotent: false
  - id: wait
    command: sleep 5
    timeout_seconds: 10
verifier_id: docker-service-healthy
```

Verifier documents are identical in structure, except every step must be read-only and `verifier: true`. Their exit status plus a fresh snapshot metric recheck determines resolution.

## Safety Guard

Safety guard runs before every playbook and verifier execution. It is a wall, not advice.

Policy checks:

- no empty or malformed command
- command length limit
- command timeout limit
- deny shell injection and dangerous operators where possible:
  `rm -rf /`, `rm -rf /*`, `mkfs`, `dd if=...`, fork bombs, `curl | sh`, `wget -O- | sh`, writes under `/boot`, `/etc/shadow`, `/etc/sudoers`, `/proc/sys`, and reverse-shell patterns
- path scope restrictions based on playbook type
- explicit denylist inherited by all hosts
- host allowlisting if playbook is scoped
- mandatory confirmation for `risk: confirm`, custom playbooks, verifier documents that are not read-only, and any global safety setting
- global auto-mode can disable auto execution without editing playbooks

Bundled playbooks are read-only and are loaded from the installed package. Custom playbooks can be edited in the dashboard but cannot bypass the guard. The guard logs both blocked and permitted decisions with reasons.

## Execution Lifecycle

For each issue with a valid ID pair:

1. Safety guard evaluates playbook.
2. If blocked, create `blocked` incident and notify dashboard.
3. If permitted and confirmation is not required, execute now.
4. If confirmation is required, create `pending_confirmation` incident and wait for operator click.
5. On confirmation, execute in a subprocess with timeout and environment allowlist.
6. Execute verifier.
7. Run a fresh snapshot and compare relevant thresholds to resolver expectations.
8. If resolved, mark incident `resolved`.
9. If unresolved, create one final model explanation and recommend one pair, mark `unresolved_recommended`; do not execute again.
10. All steps, output, timing, exit codes, and model output are audited.

## Storage

Tables:

- `hosts`
- `metric_snapshots`: current snapshot plus bounded legacy, with rollup tables
- `incidents`
- `incident_runs`
- `audit_events`
- `playbooks`
- `playbook_revisions`
- `settings`

Permanent logging:

- SQLite WAL for structured queryable state
- append-only JSONL audit log in `/var/lib/opspilot/audit/audit.jsonl`
- audit log rotations are copy-and-truncate only; old segment files are never deleted or overwritten
- no `VACUUM` or auto-prune of audit or incident history

## Dashboard

The web UI is server-rendered with global HTMX fragments. Pages:

- overview: current host snapshot cards, latest diagnosis, queued confirmations
- hosts: inventory and connectivity testing
- incidents: history, details, verifier output, recommendations
- playbooks: bundled/custom list, viewer, editor for custom, revisions
- audit: searchable append-only event timeline
- settings: Ollama model, bind host, collection interval, global auto-mode, retention, safety thresholds

Status cards poll via HTMX every 15 seconds. Dangerous confirmation uses an explicit modal and POST with idempotency key.

## Authentication

- Single admin password from `OPSPILOT_ADMIN_PASSWORD`.
- Login compares with `hmac.compare_digest`.
- Session cookie is `httpOnly`, `SameSite=Strict`, and `Secure` when TLS is available.
- Missing password causes web mode to run in localhost-only read-only mode.
- Bind host defaults to `127.0.0.1`.

## Configuration

- `OPSPILOT_ADMIN_PASSWORD`
- `OPSPILOT_BIND_HOST`
- `OPSPILOT_BIND_PORT`
- `OPSPILOT_DATA_DIR`
- `OPSPILOT_OLLAMA_BASE_URL`
- `OPSPILOT_OLLAMA_MODEL`
- `OPSPILOT_INTERVAL_SECONDS`
- `OPSPILOT_GLOBAL_AUTO_MODE`
- `OPSPILOT_SSH_KEY_PATH`
- `OPSPILOT_LOG_LEVEL`

All paths and tokens derived from environment or persisted settings; no secrets are committed.

## Testing

- pytest with async fixtures
- collector unit tests against fixture command output
- safety guard tests for known malicious/edge patterns
- incident lifecycle tests with mocked execution and model calls
- FastAPI endpoint tests with `httpx.AsyncClient`
- self-check `python -m opspilot.selftest` for non-trivial helpers before release

## Risks and Mitigations

- SSH host checks may hang: set strict connect option and global command timeout.
- Model JSON variability: schema validation, retry, and explicit no-action path.
- Playbook safety: denylist plus host and risk tiers; human confirmation.
- permanent logs growth: rotation without deletion; document disk capacity.
- Ollama model unavailable: dashboard warns and incidents stay pending.

## Implementation Phasing

1. Project skeleton, config, storage models, health endpoints.
2. Collectors, normalizer, local snapshot dashboard.
3. Ollama analyzer and catalog endpoints.
4. Safety guard and execution engine.
5. Incidents and audit HTMX views.
6. Playbook editor and SSH hosts.
7. Verifier lifecycle and recommendation-only handling.
8. Tests, self-check, packaging, systemd unit.
