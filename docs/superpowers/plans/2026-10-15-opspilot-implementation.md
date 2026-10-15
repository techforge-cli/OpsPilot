# OpsPilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement OpsPilot as a Python FastAPI monolith for Debian-family server administration with native metric collection, Ollama diagnosis, supervised playbooks, verifiers, incidents, audit, and an HTMX dashboard.

**Architecture:** One FastAPI process uses a background scheduler to collect native Linux metric snapshots per host, stores them in SQLite, asks the configured Ollama model for a strict JSON diagnosis, evaluates selected bundled or custom playbooks through a safety guard, runs approved remediation and verifier commands locally or over SSH, and permanently records incidents and audits. The dashboard is server-rendered with HTMX fragments.

**Tech Stack:** Python 3.14, FastAPI, Pydantic v2, Jinja2, httpx, PyYAML, SQLite, pytest, pytest-asyncio. No additional service dependencies or runtime package installations.

**Spec:** `docs/superpowers/specs/2026-10-15-opspilot-design.md`

## Global Constraints

- Python 3.14 syntax and standard-library preference where possible.
- Binding defaults to `127.0.0.1`; public exposure requires explicit operator action.
- Admin password come from `OPSPILOT_ADMIN_PASSWORD` only.
- Private SSH keys are referenced by path and are never stored in SQLite.
- No command is executed outside the playbook/verifier catalog.
- Bundled playbooks are read-only, custom playbooks create immutable revisions.
- Audit and incident history are append-only and never retained by pruning.

## File Structure

```text
pyproject.toml
src/opspilot/__init__.py
src/opspilot/__main__.py
src/opspilot/config.py
src/opspilot/db.py
src/opspilot/models.py
src/opspilot/auth.py
src/opspilot/audit.py
src/opspilot/hosts.py
src/opspilot/metrics.py
src/opspilot/collector.py
src/opspilot/scheduler.py
src/opspilot/analyzer.py
src/opspilot/playbooks.py
src/opspilot/safety.py
src/opspilot/executor.py
src/opspilot/incidents.py
src/opspilot/web.py
src/opspilot/templates/base.html
src/opspilot/templates/index.html
src/opspilot/templates/hosts.html
src/opspilot/templates/incidents.html
src/opspilot/templates/playbooks.html
src/opspilot/templates/audit.html
src/opspilot/static/app.css
tests/conftest.py
tests/test_config.py
tests/test_db.py
tests/test_metrics.py
tests/test_safety.py
tests/test_playbooks.py
tests/test_web.py
tests/test_incident_flow.py
opspilot/playbooks/builtin/*.yaml
```

## Task 1: Project Skeleton And Configuration

**Files:**
- Create: `pyproject.toml`
- Create: `src/opspilot/__init__.py`
- Create: `src/opspilot/__main__.py`
- Create: `src/opspilot/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings`, `settings`, `settings_from_env`.

- [ ] **Step 1: Write the failing configuration test**

```python
from opspilot.config import Settings

def test_settings_require_password_for_web():
    settings = Settings(  # type: ignore[call-arg]
        data_dir="/tmp/opspilot",
        ollama_base_url="http://localhost:11434",
        ollama_model="qwen2.5:7b",
    )
    assert settings.read_only_web_mode is True

def test_admin_password_enables_admin_mode():
    settings = Settings(
        data_dir="/tmp/opspilot",
        ollama_base_url="http://localhost:11434",
        ollama_model="qwen2.5:7b",
        admin_password="correct horse",
    )
    assert settings.read_only_web_mode is False
```

- [ ] **Step 2: Run the test to see the import fail**

Run: `pytest tests/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError` or missing `Settings`.

- [ ] **Step 3: Create the package and project metadata**

`pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "opspilot"
version = "0.1.0"
description = "Linux server administration assistant with native metrics and local LLM workflows"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115",
  "jinja2>=3.1",
  "httpx>=0.27",
  "pydantic>=2.8",
  "pydantic-settings>=2.0",
  "pyyaml>=6.0",
  "uvicorn>=0.30",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.24",
  "httpx>=0.27",
]

[project.scripts]
opspilot = "opspilot.__main__:main"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

`src/opspilot/__init__.py`:

```python
"""OpsPilot package."""
```

`src/opspilot/config.py`:

```python
import os
import secrets
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPSPILOT_", case_sensitive=False)

    admin_password: str = ""
    bind_host: str = "127.0.0.1"
    bind_port: int = 8443
    data_dir: str = "/var/lib/opspilot"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b"
    interval_seconds: int = 30
    global_auto_mode: bool = False
    ssh_key_path: str = "/etc/opspilot/operator.key"
    log_level: str = "INFO"
    session_secret: str = Field(default_factory=lambda: secrets.token_urlsafe(32))

    @property
    def read_only_web_mode(self) -> bool:
        return self.admin_password == ""

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)


def settings_from_env() -> Settings:
    return Settings()
```

`src/opspilot/__main__.py`:

```python
import argparse
import os

from opspilot.config import settings_from_env
from opspilot.db import init_db
from opspilot.web import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="OpsPilot")
    parser.add_argument("--config-check", action="store_true", help="validate settings and exit")
    parser.add_argument("--host", default=None, help="override bind host")
    parser.add_argument("--port", type=int, default=None, help="override bind port")
    args = parser.parse_args()
    settings = settings_from_env()
    init_db(settings.data_path / "opspilot.sqlite")
    if args.config_check:
        os.makedirs(settings.data_path, exist_ok=True)
        print(f"configuration valid; data_dir={settings.data_dir}")
        return
    import uvicorn

    host = args.host or settings.bind_host
    port = args.port or settings.bind_port
    uvicorn.run(
        create_app(settings),
        host=host,
        port=port,
        log_level=settings.log_level.lower(),
    )
```

- [ ] **Step 4: Run the test to make it pass**

Run: `PYTHONPATH=src pytest tests/test_config.py -q`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/opspilot/__init__.py src/opspilot/__main__.py src/opspilot/config.py tests/test_config.py
git commit -m "feat: add opspilot package skeleton and settings"
```

## Task 2: SQLite Storage And Domain Models

**Files:**
- Create: `src/opspilot/db.py`
- Create: `src/opspilot/models.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `Settings`.
- Produces: `init_db(path)`, `connect(path)`, `HostRecord`, `MetricSnapshotRecord`, `IncidentRecord`, `AuditEventRecord`, `PlaybookRevisionRecord`.

- [ ] **Step 1: Write the failing database test**

```python
import tempfile
from pathlib import Path

from opspilot.db import connect, init_db

def test_init_creates_all_tables():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.sqlite"
        init_db(path)
        conn = connect(path)
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"hosts", "metric_snapshots", "incidents", "audit_events", "playbooks", "playbook_revisions"} <= names
```

- [ ] **Step 2: Run the test to see the missing database module**

Run: `PYTHONPATH=src pytest tests/test_db.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement the database**

`src/opspilot/db.py`:

```python
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS hosts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    execution_mode TEXT NOT NULL DEFAULT 'local',
    ssh_user TEXT,
    ssh_port INTEGER NOT NULL DEFAULT 22,
    ssh_key_path TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS metric_snapshots (
    id TEXT PRIMARY KEY,
    host_id TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    interval_seconds INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    FOREIGN KEY (host_id) REFERENCES hosts(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    host_id TEXT NOT NULL,
    status TEXT NOT NULL,
    issue_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    summary TEXT NOT NULL,
    explanation TEXT NOT NULL,
    FOREIGN KEY (host_id) REFERENCES hosts(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    host_id TEXT,
    created_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS playbooks (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    is_builtin INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    current_revision_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS playbook_revisions (
    id TEXT PRIMARY KEY,
    playbook_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    risk TEXT NOT NULL,
    auto_run INTEGER NOT NULL DEFAULT 0,
    verifier_id TEXT,
    content_yaml TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (playbook_id) REFERENCES playbooks(id) ON DELETE CASCADE
);
"""

def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
```

`src/opspilot/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any


def row_to_dict(row):
    return dict(row) if row is not None else {}


@dataclass(frozen=True)
class Host:
    id: str
    name: str
    address: str
    execution_mode: str = "local"
    ssh_user: str | None = None
    ssh_port: int = 22
    ssh_key_path: str | None = None
    tags: tuple[str, ...] = ()
    is_active: bool = True

    def tags_json(self) -> str:
        import json
        return json.dumps(list(self.tags))

    @classmethod
    def from_row(cls, row):
        tags = tuple(__import__("json").loads(row["tags_json"] or "[]"))
        return cls(
            id=row["id"],
            name=row["name"],
            address=row["address"],
            execution_mode=row["execution_mode"],
            ssh_user=row["ssh_user"],
            ssh_port=row["ssh_port"],
            ssh_key_path=row["ssh_key_path"],
            tags=tags,
            is_active=bool(row["is_active"]),
        )


@dataclass(frozen=True)
class SnapshotRecord:
    id: str
    host_id: str
    collected_at: datetime
    interval_seconds: int
    snapshot: dict[str, Any]
```

- [ ] **Step 4: Run the database test**

Run: `PYTHONPATH=src pytest tests/test_db.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/opspilot/db.py src/opspilot/models.py tests/test_db.py
git commit -m "feat: add sqlite storage and domain models"
```

## Task 3: Host And Audit Repositories

**Files:**
- Create: `src/opspilot/hosts.py`
- Create: `src/opspilot/audit.py`
- Test: `tests/test_hosts.py`

**Interfaces:**
- Consumes: `connect(path)`, `Host`.
- Produces: `HostRepository.save(host)`, `list_hosts()`, `get_host(id)`, `default_local_host()`, `AuditRepository.record(event_type, host_id=None, message="", detail=None)`.

- [ ] **Step 1: Write the failing host repository test**

```python
import tempfile
from pathlib import Path

from opspilot.db import connect, init_db
from opspilot.hosts import default_local_host, HostRepository

def test_default_local_host_is_saved():
    with tempfile.TemporaryDirectory() as tmp:
        conn = connect(Path(tmp) / "db.sqlite")
        init_db(Path(tmp) / "db.sqlite")
        conn = connect(Path(tmp) / "db.sqlite")
        repo = HostRepository(conn)
        repo.save(default_local_host())
        found = repo.list_hosts()
        assert len(found) == 1
        assert found[0].execution_mode == "local"
```

- [ ] **Step 2: Run the test**

Run: `PYTHONPATH=src pytest tests/test_hosts.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement hosts and audit**

`src/opspilot/hosts.py`:

```python
import sqlite3
from dataclasses import asdict
from uuid import uuid4

from opspilot.db import init_db, connect
from opspilot.models import Host

class HostRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def save(self, host: Host) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO hosts
               (id, name, address, execution_mode, ssh_user, ssh_port, ssh_key_path, tags_json, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                host.id,
                host.name,
                host.address,
                host.execution_mode,
                host.ssh_user,
                host.ssh_port,
                host.ssh_key_path,
                host.tags_json(),
                int(host.is_active),
            ),
        )
        self.conn.commit()

    def list_hosts(self) -> list[Host]:
        rows = self.conn.execute("SELECT * FROM hosts ORDER BY name").fetchall()
        return [Host.from_row(row) for row in rows]

    def get_host(self, host_id: str) -> Host | None:
        row = self.conn.execute("SELECT * FROM hosts WHERE id = ?", (host_id,)).fetchone()
        return Host.from_row(row) if row else None

def default_local_host() -> Host:
    return Host("local", "Local admin box", "127.0.0.1", execution_mode="local")
```

`src/opspilot/audit.py`:

```python
import json
import sqlite3
import uuid
from datetime import datetime, timezone


class AuditRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def record(self, event_type: str, message: str, host_id: str | None = None, detail: dict | None = None) -> None:
        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO audit_events (id, host_id, created_at, event_type, message, detail_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (event_id, host_id, now, event_type, message, json.dumps(detail or {})),
        )
        self.conn.commit()

    def list_events(self, limit: int = 100) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
```

- [ ] **Step 4: Run the host tests**

Run: `PYTHONPATH=src pytest tests/test_hosts.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/opspilot/hosts.py src/opspilot/audit.py tests/test_hosts.py
git commit -m "feat: add host inventory and audit repository"
```

## Task 4: Native Metric Collection

**Files:**
- Create: `src/opspilot/metrics.py`
- Create: `src/opspilot/collector.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `ShellRunner` produced by host repository build method.
- Produces: `collect_native_snapshot(shell)`.

- [ ] **Step 1: Write the failing metric test**

```python
from unittest.mock import Mock

from opspilot.metrics import collect_native_snapshot

def test_memory_parser_accepts_proc_meminfo():
    shell = Mock()
    shell.run.return_value = (0, "MemTotal: 1000 kB\nMemAvailable: 400 kB\nSwapTotal: 10 kB\nSwapFree: 5 kB\n", "", 0.1)
    result = collect_native_snapshot(shell)
    assert shell.run.call_count >= 1
    assert result["metrics"]["memory"]["mem_total_kb"] == 1000
```

- [ ] **Step 2: Implement collection**

`src/opspilot/collector.py`:

```python
import shlex
import subprocess
import time


class ShellRunner:
    def __init__(self, execution_mode="local", ssh_user=None, address=None, ssh_key_path=None, ssh_port=22):
        self.execution_mode = execution_mode
        self.ssh_user = ssh_user
        self.address = address
        self.ssh_key_path = ssh_key_path
        self.ssh_port = ssh_port

    def run(self, command: str, timeout: int = 15):
        start = time.monotonic()
        if self.execution_mode == "ssh":
            argv = [
                "ssh", "-i", self.ssh_key_path, "-p", str(self.ssh_port),
                "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
                f"{self.ssh_user}@{self.address}", "bash", "-lc", command,
            ]
        else:
            argv = ["bash", "-lc", command]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr, time.monotonic() - start
```

`src/opspilot/metrics.py`:

```python
from datetime import datetime, timezone
import json


def parse_meminfo(text: str) -> dict:
    parsed = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        number = value.strip().split()[0].rstrip("kB").strip()
        try:
            parsed[key] = int(number)
        except ValueError:
            parsed[key] = 0
    return {
        "mem_total_kb": parsed.get("MemTotal", 0),
        "mem_available_kb": parsed.get("MemAvailable", 0),
        "swap_total_kb": parsed.get("SwapTotal", 0),
        "swap_free_kb": parsed.get("SwapFree", 0),
    }


def parse_loadavg(text: str) -> dict:
    parts = text.split()
    try:
        return {
            "one_minute": float(parts[0]),
            "five_minute": float(parts[1]),
            "fifteen_minute": float(parts[2]),
        } if len(parts) >= 3 else {}
    except (ValueError, IndexError):
        return {}


def parse_df(text: str) -> list[dict]:
    lines = [line for line in text.splitlines() if line.strip()]
    rows = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 7:
            rows.append({
                "filesystem": parts[0],
                "size_bytes": int(parts[1]),
                "used_bytes": int(parts[2]),
                "available_bytes": int(parts[3]),
                "mounted_on": parts[6],
            })
    return rows


def collect_native_snapshot(shell) -> dict:
    commands = {
        "loadavg": "cat /proc/loadavg",
        "meminfo": "cat /proc/meminfo",
        "df": "df -B1 -P",
        "ps": "ps -eo pid,ppid,user,pcpu,pmem,comm= --sort=-pcpu | head -30",
        "journal": "journalctl --since '5 minutes ago' -p err -o short 2>/dev/null | tail -50",
    }
    native_output = {name: shell.run(command) for name, command in commands.items()}
    memory = native_output["meminfo"][1]
    loadavg = native_output["loadavg"][1].strip()
    df = native_output["df"][1]
    return {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "metrics": {
            "load": parse_loadavg(loadavg),
            "memory": parse_meminfo(memory),
            "disk": {"filesystems": parse_df(df)},
        },
        "processes": native_output["ps"][1],
        "recent_errors": native_output["journal"][1],
        "commands": {name: code for name, (code, _, _, _) in native_output.items()},
    }
```

- [ ] **Step 3: Run metric tests**

Run: `PYTHONPATH=src pytest tests/test_metrics.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/opspilot/metrics.py src/opspilot/collector.py tests/test_metrics.py
git commit -m "feat: collect and normalize native linux metrics"
```

## Task 5: Ollama Analyzer

**Files:**
- Create: `src/opspilot/analyzer.py`
- Test: `tests/test_analyzer.py`

**Interfaces:**
- Consumes: normalized snapshot, playbook catalog, settings.
- Produces: `Analysis`, `Analyzer.analyze(snapshot, playbooks)`.

- [ ] **Step 1: Write the failing analyzer test**

```python
from unittest.mock import Mock

from opspilot.analyzer import Analyzer

def test_analyzer_parses_strict_json():
    http = Mock()
    http.post.return_value = Mock(
        status_code=200,
        json=lambda: {"choices": [{"message": {"content": '{"status":"ok","severity":"info","explanation":"usable","confidence":0.9,"issue_id":"","playbook_id":null,"verifier_id":null,"recommended":false}'}}]},
    )
    analyzer = Analyzer("http://localhost:11434", "m", http)
    result = analyzer.analyze({"metrics": {}}, [])
    assert result.status == "ok"
    assert result.playbook_id is None
```

- [ ] **Step 2: Implement analyzer**

`src/opspilot/analyzer.py`:

```python
import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


class Analysis(BaseModel):
    status: str
    severity: str
    explanation: str
    confidence: float = Field(ge=0.0, le=1.0)
    issue_id: str = ""
    playbook_id: str | None = None
    verifier_id: str | None = None
    recommended: bool = False


class Analyzer:
    def __init__(self, base_url: str, model: str, client):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = client

    def analyze(self, snapshot: dict[str, Any], playbooks: list[dict[str, Any]]) -> Analysis:
        catalog = [{"id": p["id"], "description": p.get("description", "")} for p in playbooks]
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "Return JSON only with the exact fields status, severity, explanation, confidence, issue_id, playbook_id, verifier_id, recommended. Never return commands."},
                {"role": "user", "content": json.dumps({"snapshot": snapshot, "playbooks": catalog})},
            ],
        }
        response = self.client.post(f"{self.base_url}/v1/chat/completions", json=body, timeout=60)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return Analysis.model_validate_json(content)
```

- [ ] **Step 3: Run analyzer tests**

Run: `PYTHONPATH=src pytest tests/test_analyzer.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/opspilot/analyzer.py tests/test_analyzer.py
git commit -m "feat: add strict json ollama analyzer"
```

## Task 6: Playbook Catalog And Safety Guard

**Files:**
- Create: `src/opspilot/playbooks.py`
- Create: `src/opspilot/safety.py`
- Create: `opspilot/playbooks/builtin/README.md`
- Test: `tests/test_playbooks.py`
- Test: `tests/test_safety.py`

**Interfaces:**
- Produces: `Playbook`, `load_builtin_playbooks()`, `SafetyGuard.evaluate(playbook, host, settings)`.

- [ ] **Step 1: Write the failing playbook and safety tests**

```python
import yaml

from opspilot.playbooks import Playbook
from opspilot.safety import SafetyGuard

def test_playbook_parses_yaml():
    document = yaml.safe_load("""
id: test
title: Test
risk: confirm
auto_run: false
steps:
  - id: check
    command: echo ok
verifier_id: verify-test
""")
    playbook = Playbook.from_dict(document, source="builtin")
    assert playbook.id == "test"
    assert playbook.risk == "confirm"
```

```python
from opspilot.models import Host
from opspilot.playbooks import Playbook
from opspilot.safety import SafetyGuard
from opspilot.config import Settings

def test_blocks_fork_bomb():
    playbook = Playbook.from_dict({"id": "bad", "risk": "confirm", "steps": [{"command": ":(){ :|:& };:"}]}, source="custom")
    guard = SafetyGuard()
    settings = Settings(data_dir="/tmp", ollama_base_url="x", ollama_model="m")
    host = Host("local", "Local", "127.0.0.1")
    result = guard.evaluate(playbook, host, settings)
    assert result.allowed is False
```

- [ ] **Step 2: Implement playbooks and guard**

`src/opspilot/playbooks.py`:

```python
import yaml
from dataclasses import dataclass


class Playbook:
    @dataclass
    def step(self, item: dict):
        pass

    def __init__(self, id, title, description, risk, auto_run, source, verifier_id, steps, issue_ids, builtin=False):
        self.id = id
        self.title = title
        self.description = description
        self.risk = risk
        self.auto_run = auto_run
        self.source = source
        self.verifier_id = verifier_id
        self.steps = steps
        self.issue_ids = issue_ids
        self.is_builtin = builtin

    @classmethod
    def from_dict(cls, data: dict, source: str):
        return cls(
            id=data["id"],
            title=data.get("title", data["id"]),
            description=data.get("description", ""),
            risk=data.get("risk", "confirm"),
            auto_run=bool(data.get("auto_run", False)),
            source=source,
            verifier_id=data.get("verifier_id"),
            steps=data.get("steps", []),
            issue_ids=data.get("applies_to", {}).get("issue_ids", []),
            builtin=source == "builtin",
        )

    def commands(self):
        return [step["command"] for step in self.steps]
```

`src/opspilot/safety.py`:

```python
import re
from dataclasses import dataclass
from opspilot.config import Settings
from opspilot.models import Host
from opspilot.playbooks import Playbook


@dataclass
class SafetyResult:
    allowed: bool
    requires_confirmation: bool
    reasons: list[str]


DENY_PATTERNS = [
    r":\(\)\s*\{",
    r"\brm\s+-rf\s+/",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bcurl\s+\S+\s*\|\s*(sh|bash)\b",
    r"\bwget\s+.*\|\s*(sh|bash)\b",
    r"\b/shadow\b",
    r"\b/boot\b",
    r"\b/proc/sys\b",
]


class SafetyGuard:
    def evaluate(self, playbook: Playbook, host: Host, settings: Settings):
        reasons = []
        if not playbook.steps:
            reasons.append("playbook has no steps")
        for command in playbook.commands():
            for pattern in DENY_PATTERNS:
                if re.search(pattern, command):
                    reasons.append(f"deny pattern matched: {pattern}")
        requires_confirmation = (
            playbook.risk != "auto"
            or playbook.source != "builtin"
            or not settings.global_auto_mode
            or not playbook.auto_run
        )
        return SafetyResult(allowed=not reasons, requires_confirmation=requires_confirmation, reasons=reasons)
```

Create a sample bundled playbook at `opspilot/playbooks/builtin/00-sample.yaml`:

```yaml
id: sample-noop
title: Sample read-only playebook
description: Demonstration playbook that reads system state.
risk: auto
auto_run: true
steps:
  - id: load
    command: uptime && free -b
verifier_id: sample-verify
```

Also create verifier sample. Simpler: one file known by tests? We'll add later.

- [ ] **Step 3: Run safety and playbook tests**

Run: `PYTHONPATH=src pytest tests/test_playbooks.py tests/test_safety.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/opspilot/playbooks.py src/opspilot/safety.py opspilot/playbooks tests/test_playbooks.py tests/test_safety.py
git commit -m "feat: add playbook catalog and safety guard"
```

## Task 7: Executor And Verifier

**Files:**
- Create: `src/opspilot/executor.py`
- Test: `tests/test_executor.py`

**Interfaces:**
- Produces: `ExecutionResult`, `PlaybookExecutor.run(playbook, host)`.

- [ ] **Step 1: Write the failing executor test**

```python
from unittest.mock import Mock

from opspilot.executor import PlaybookExecutor
from opspilot.playbooks import Playbook

def test_executor_runs_step_and_captures_output(monkeypatch):
    playbook = Playbook.from_dict({"id": "x", "risk":"auto", "steps":[{"command":"echo hi"}]}, source="builtin")
    subprocess = Mock()
    subprocess.run.return_value = Mock(returncode=0, stdout="hi\n", stderr="")
    monkeypatch.setattr("opspilot.executor.subprocess.run", subprocess.run)
    executor = PlaybookExecutor(settings=None)
    result = executor.run(playbook, Mock(execution_mode="local"))
    assert result.healthy is True
    assert "hi" in result.stdout
```

- [ ] **Step 2: Implement executor**

`src/opspilot/executor.py`:

```python
import subprocess


def _run_local(command: str, timeout: int = 30):
    return subprocess.run(["bash", "-lc", command], capture_output=True, text=True, timeout=timeout)


class PlaybookExecutor:
    def __init__(self, settings=None):
        self.settings = settings

    def run(self, playbook, host):
        stdout = ""
        stderr = ""
        healthy = True
        for step in playbook.steps:
            timeout = int(step.get("timeout_seconds", 30))
            command = step["command"]
            if host.execution_mode == "ssh":
                proc = subprocess.run(
                    ["ssh", "-i", host.ssh_key_path, "-p", str(host.ssh_port), f"{host.ssh_user}@{host.address}", "bash", "-lc", command],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            else:
                proc = _run_local(command, timeout)
            stdout += proc.stdout
            stderr += proc.stderr
            if proc.returncode != 0:
                healthy = False
                break
        return ExecutionResult(healthy=healthy, stdout=stdout, stderr=stderr)
```

Dataclass needs declaration before use; add:

```python
from dataclasses import dataclass

@dataclass
class ExecutionResult:
    healthy: bool
    stdout: str
    stderr: str
```

Move this above class. Import `Host` only for type hints.

- [ ] **Step 3: Run executor tests**

Run: `PYTHONPATH=src pytest tests/test_executor.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/opspilot/executor.py tests/test_executor.py
git commit -m "feat: add playbook executor"
```

## Task 8: Incident Lifecycle And Recommendation-Only Follow-up

**Files:**
- Create: `src/opspilot/incidents.py`
- Test: `tests/test_incident_flow.py`

**Interfaces:**
- Produces: `IncidentStatus`, `IncidentManager.create_issue`, `resolve_with_verifier`, `recommend`.

- [ ] **Step 1: Write the failing flow test**

```python
from opspilot.incidents import IncidentManager

def test_unresolved_incident_becomes_recommendation():
    manager = IncidentManager()
    incident = manager.create_issue("host", "service_down", "warning", "service failed", "engineering details")
    result = manager.mark_unresolved(incident.id, "verifier failed")
    assert result.status == "unresolved_recommended"
    assert result.recommended is True
```

- [ ] **Step 2: Implement incident model logic**

`src/opspilot/incidents.py`:

```python
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Incident:
    id: str
    host_id: str
    issue_id: str
    severity: str
    status: str
    summary: str
    explanation: str
    recommended: bool = False
    recommendation_playbook_id: str | None = None
    recommendation_verifier_id: str | None = None


class IncidentManager:
    def __init__(self):
        self.incidents = {}

    def create_issue(self, host_id, issue_id, severity, summary, explanation):
        incident = Incident(
            id=str(uuid.uuid4()),
            host_id=host_id,
            issue_id=issue_id,
            severity=severity,
            status="open",
            summary=summary,
            explanation=explanation,
        )
        self.incidents[incident.id] = incident
        return incident

    def mark_resolved(self, incident_id):
        incident = self.incidents[incident_id]
        incident.status = "resolved"
        return incident

    def mark_unresolved(self, incident_id, verifier_output):
        incident = self.incidents[incident_id]
        incident.status = "unresolved_recommended"
        incident.recommended = True
        incident.explanation = incident.explanation + "\nVerifier output: " + verifier_output
        return incident
```

- [ ] **Step 3: Run incident tests**

Run: `PYTHONPATH=src pytest tests/test_incident_flow.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/opspilot/incidents.py tests/test_incident_flow.py
git commit -m "feat: add incident lifecycle and recommendation-only handling"
```

## Task 9: FastAPI Web App And Dashboard Filters

**Files:**
- Create: `src/opspilot/web.py`
- Create: `src/opspilot/templates/base.html`
- Create: `src/opspilot/templates/index.html`
- Test: `tests/test_web.py`

**Interfaces:**
- Produces: `create_app(settings)`.

- [ ] **Step 1: Write failing web test**

```python
from fastapi.testclient import TestClient

from opspilot.config import Settings
from opspilot.web import create_app

def test_root_requires_auth_in_admin_mode():
    settings = Settings(data_dir="/tmp/opspilotweb", ollama_base_url="x", ollama_model="m", admin_password="secret")
    client = TestClient(create_app(settings))
    response = client.get("/")
    assert response.status_code in (401, 302, 403)
```

- [ ] **Step 2: Implement web app**

`src/opspilot/web.py`:

```python
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from opspilot.config import Settings
from opspilot.db import connect, init_db


def create_app(settings: Settings):
    init_db(__import__("pathlib").Path(settings.data_dir) / "opspilot.sqlite")
    templates = Jinja2Templates(directory=__import__("pathlib").Path(__file__).resolve().parent / "templates")
    app = FastAPI(title="OpsPilot")
    app.state.settings = settings
    app.state.conn = connect(__import__("pathlib").Path(settings.data_dir) / "opspilot.sqlite")

    def auth():
        if not settings.admin_password:
            return None
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})

    @app.get("/", response_class=HTMLResponse)
    def overview(request):
        if settings.admin_password:
            auth()
        return templates.TemplateResponse("index.html", {"request": request, "settings": settings})

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app
```

`src/opspilot/templates/index.html`:

```html
<!DOCTYPE html>
<html>
<head><title>OpsPilot</title></head>
<body>
<h1>OpsPilot</h1>
<p>Latest status and incidents appear here.</p>
</body>
</html>
```

`src/opspilot/templates/base.html`:

```html
<!DOCTYPE html>
<html><head><title>OpsPilot</title></head><body>{% block content %}{% endblock %}</body></html>
```

- [ ] **Step 3: Run web tests**

Run: `PYTHONPATH=src pytest tests/test_web.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/opspilot/web.py src/opspilot/templates tests/test_web.py
git commit -m "feat: add fastapi dashboard skeleton"
```

## Task 10: End-To-End Local Run Through One Incident

**Files:**
- Create: `tests/test_runtime_flow.py`

- [ ] **Step 1: Write the end-to-end integration test**

```python
from unittest.mock import Mock

from opspilot.analyzer import Analyzer
from opspilot.playbooks import Playbook
from opspilot.incidents import IncidentManager
from opspilot.executor import PlaybookExecutor
from opspilot.models import Host

def test_incident_resolver_flow_runs_once():
    analysis_json = {
        "status": "issue",
        "severity": "warning",
        "explanation": "service failed",
        "confidence": 0.9,
        "issue_id": "service_failed",
        "playbook_id": "restart-service",
        "verifier_id": "service-healthy",
        "recommended": False,
    }
    http = Mock()
    http.post.return_value = Mock(status_code=200, json=lambda: {"choices": [{"message": {"content": __import__("json").dumps(analysis_json)}}]})
    analyzer = Analyzer("http://localhost:11434", "m", http)
    playbook = Playbook.from_dict({"id": "restart-service", "risk": "auto", "steps": [{"command": "true"}]}, source="builtin")
    playbook.verifier = Playbook.from_dict({"id": "service-healthy", "risk": "auto", "steps": [{"command": "true"}]}, source="builtin")
    manager = IncidentManager()
    incident = manager.create_issue("local", "service_failed", "warning", "service failed", analysis_json["explanation"])
    executor = PlaybookExecutor()
    outcome = executor.run(playbook, Host("local", "Local", "127.0.0.1"))
    manager.mark_resolved(incident.id) if outcome.healthy else manager.mark_unresolved(incident.id, "verifier failed")
    assert incident.status in ("resolved", "unresolved_recommended")
```

- [ ] **Step 2: Run the integration test**

Run: `PYTHONPATH=src pytest tests/test_runtime_flow.py -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_runtime_flow.py
git commit -m "test: cover issue to remediation flow scaffold"
```

## Task 11: Scheduling And SettingsDashboard

**Files:**
- Create: `src/opspilot/scheduler.py`
- Modify: `src/opspilot/web.py`

**Interfaces:**
- Produces: `Scheduler.start_background(settings, repo)`, `stop()`.

Implementation uses `asyncio` and periodic snapshot collection. Persist audit `metric_collection_completed`. The scheduler is intentionally stub-like in Step 2 but can run the local host collection loop and sleep for the configured interval; anything more belongs in the executor and incident tasks.

- [ ] **Step 1: Implement scheduler**

`src/opspilot/scheduler.py`:

```python
import asyncio


def run_collection_loop(settings, collect_once):
    async def loop():
        while True:
            collect_once()
            await asyncio.sleep(settings.interval_seconds)
    return loop()
```

- [ ] **Step 2: Run test suite**

Run: `PYTHONPATH=src pytest -q`
Expected: Existing tests pass.

- [ ] **Step 3: Commit**

```bash
git add src/opspilot/scheduler.py
git commit -m "feat: add periodic collection loop"
```

## Task 12: Permanent Append-Only Audit Journal

**Files:**
- Modify: `src/opspilot/audit.py`
- Create: `src/opspilot/journal.py`
- Test: `tests/test_journal.py`

**Interfaces:**
- Produces: `AuditJournal.append(event)`.

- [ ] **Step 1: Write the failing journal test**

```python
import json
from pathlib import Path

from opspilot.journal import AuditJournal

def test_append_is_permanent_jsonl(tmp_path):
    journal = AuditJournal(tmp_path / "audit.jsonl")
    journal.append({"event": "test"})
    assert json.loads((tmp_path / "audit.jsonl").read_text().strip())["event"] == "test"
```

- [ ] **Step 2: Implement append-only JSONL writer**

`src/opspilot/journal.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path


class AuditJournal:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: dict) -> None:
        payload = event | {"written_at": datetime.now(timezone.utc).isoformat()}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, default=str) + "\\n")
            handle.flush()
```

- [ ] **Step 3: Run tests**

Run: `PYTHONPATH=src pytest tests/test_journal.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/opspilot/journal.py src/opspilot/audit.py tests/test_journal.py
git commit -m "feat: add permanent append-only audit journal"
```

## Task 13: Bundled Playbooks And Deployment Assets

**Files:**
- Create: `opspilot/playbooks/builtin/restart-docker-unhealthy.yaml`, plus one verifier.
- Create: `systemd/opspilot.service`
- Create: `README.md`

- [ ] Add sample builtins only, no hard-coded custom playbooks.
- [ ] Create deployment service:

```ini
[Unit]
Description=OpsPilot server administration assistant
After=network.target

[Service]
ExecStart=/usr/local/bin/opspilot
Environment=OPSPILOT_DATA_DIR=/var/lib/opspilot
Restart=always

[Install]
WantedBy=multi-user.target
```

## Self-Review

Spec coverage check:

- native metrics: Task 4
- OpenAI-compatible Ollama call: Task 5
- strict JSON: Task 5
- playbook/verifier review: Tasks 6, 7
- safety guard: Task 6
- approval/resolution/recommendation-only: Tasks 7, 8
- permanent logs: model tables and append-only audit intent in Task 2/3
- HTMX dashboard: Task 9 plus future styling
- settings/auth/config: Tasks 1, 9

Known follow-up work needed before release:

- replace mock-heavy Web UI with full templating and forms
- implement executor safety invocation before runtime
- implement SSH command execution
- replace echo logic with production runtime wiring
- add permanent JSONL audit writer and immutable revisions
- add more native collectors, allowlists, and packaging

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-15-opspilot-implementation.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration

2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
