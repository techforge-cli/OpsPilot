# OpsPilot

Linux server administration assistant with native metrics and local LLM workflows.

## Run

```bash
pip install -e .
opspilot --config-check
opspilot
```

Data is stored under `OPSPILOT_DATA_DIR` (default `/var/lib/opspilot`).

## Bundled playbooks

Read-only playbooks shipped in `opspilot/playbooks/builtin`. Custom playbooks live in the data directory.
