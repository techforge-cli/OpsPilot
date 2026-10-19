# OpsPilot Demo

A self-contained demo of OpsPilot that runs entirely in Docker — no Ollama, no internet, no setup.

## Quick Start

```bash
chmod +x scripts/demo.sh
./scripts/demo.sh
```

Then open http://localhost:8443 and login with **admin** / **demo**.

## What You'll See

The dashboard loads with 3 pre-seeded hosts (web-01, db-01, cache-01) and a "Demo Controls" panel with three buttons.

### Tier 1: Auto-Run (Disk Space)

Click **Tier 1** → the disk space incident is detected, the AI proposes a playbook, and it runs automatically (no confirmation needed). The progress bar animates through: Analysis → Guard → Execute → Verify → Resolved.

### Tier 2: Confirm (Docker Service)

Click **Tier 2** → the docker service incident is detected, the AI proposes a playbook, and it waits for your confirmation. Click **Confirm Execution** → the safety guard evaluates, the playbook runs, the verifier confirms, and the incident is resolved.

### Tier 3: Blocked (Memory Pressure)

Click **Tier 3** → the memory pressure incident is detected, the AI proposes a dangerous playbook (`curl | bash`), and the safety guard **blocks** it. The progress bar shows the guard stage in red.

## How It Works

- **Demo mode** uses the real SafetyGuard, PlaybookExecutor, and AuditJournal — only the "AI analysis" is simulated.
- The demo creates a `DemoSession` on startup that seeds 3 fake hosts into SQLite.
- Each button click triggers a backend endpoint (`/demo/trigger/{tier}`) that runs the real workflow.
- The progress bar and log panel update via HTMX polling.

## Stopping the Demo

```bash
docker compose -f docker-compose.demo.yml down
```

## Real Usage

To use OpsPilot with a real Ollama model:

```bash
docker compose up
```

Set `OPSPILOT_OLLAMA_BASE_URL` to your Ollama endpoint and `OPSPILOT_ADMIN_PASSWORD` to a strong password.
