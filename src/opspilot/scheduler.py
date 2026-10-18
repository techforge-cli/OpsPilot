import asyncio
import json
import logging
import sqlite3
import threading
import uuid
from datetime import UTC, datetime

from opspilot.audit import AuditRepository
from opspilot.collector import ShellRunner
from opspilot.config import Settings
from opspilot.hosts import HostRepository, default_local_host
from opspilot.incidents import IncidentManager
from opspilot.metrics import collect_native_snapshot
from opspilot.playbooks import load_builtin_playbooks

logger = logging.getLogger("opspilot.scheduler")


def run_collection_loop(settings, collect_once):
    async def loop():
        while True:
            collect_once()
            await asyncio.sleep(settings.interval_seconds)

    return loop()


class Scheduler:
    def __init__(self, settings=None, repo=None, **kwargs):
        self.settings = self._coerce_settings(settings)
        self.repo = repo
        self.analyzer = kwargs.get("analyzer", getattr(repo, "analyzer", None) if repo is not None else None)
        self.incident_manager = kwargs.get("incident_manager", getattr(repo, "incident_manager", getattr(repo, "incidents", None)) if repo is not None else None)
        self.playbooks = kwargs.get("playbooks", getattr(repo, "playbooks", None) if repo is not None else None)
        self.started = False
        self._stopped = False
        self._thread = None
        self._loop = None
        self._task = None
        self._collect_count = 0

    @staticmethod
    def _is_connection(value):
        return isinstance(value, sqlite3.Connection)

    @staticmethod
    def _coerce_settings(settings):
        if isinstance(settings, Settings):
            return settings
        if settings is not None and hasattr(settings, "interval_seconds") and hasattr(settings, "data_dir"):
            return settings
        return Settings()

    def _connection(self):
        repo = self.repo
        if self._is_connection(repo):
            return repo
        if repo is None:
            return None
        for name in ("conn", "connection", "db"):
            candidate = getattr(repo, name, None)
            if self._is_connection(candidate):
                return candidate
        return None

    def _hosts(self):
        repo = self.repo
        candidates = []
        if repo is not None and callable(getattr(repo, "list_hosts", None)):
            try:
                result = repo.list_hosts()
            except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
                result = None
            if isinstance(result, (list, tuple)):
                candidates = list(result)
        if not candidates and repo is not None:
            nested = getattr(repo, "hosts", None)
            if nested is not None:
                if callable(getattr(nested, "list_hosts", None)):
                    try:
                        result = nested.list_hosts()
                    except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
                        result = None
                    if isinstance(result, (list, tuple)):
                        candidates = list(result)
                elif isinstance(nested, (list, tuple)):
                    candidates = list(nested)
        conn = self._connection()
        if not candidates and conn is not None:
            try:
                candidates = list(HostRepository(conn).list_hosts())
            except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
                candidates = []
        if not candidates:
            try:
                candidates = [default_local_host()]
            except (OSError, RuntimeError, ValueError, TypeError):
                candidates = []
        validated = []
        for item in candidates:
            if isinstance(item, str):
                continue
            if hasattr(item, "execution_mode") or hasattr(item, "address") or hasattr(item, "id"):
                validated.append(item)
        return validated or [default_local_host()]

    def _audit(self):
        repo = self.repo
        if repo is not None and callable(getattr(repo, "record", None)):
            return repo
        if repo is not None:
            for name in ("audit", "audit_repo", "audit_repository", "audits"):
                nested = getattr(repo, name, None)
                if nested is not None and callable(getattr(nested, "record", None)):
                    return nested
        conn = self._connection()
        if conn is not None:
            return AuditRepository(conn)
        return None

    def _playbooks(self):
        if self.playbooks is not None:
            if callable(getattr(self.playbooks, "list_playbooks", None)):
                try:
                    return list(self.playbooks.list_playbooks())
                except (OSError, RuntimeError, ValueError, TypeError):
                    pass
            if isinstance(self.playbooks, (list, tuple)):
                return list(self.playbooks)
        repo = self.repo
        if repo is not None:
            for name in ("playbooks", "playbook_catalog", "catalog"):
                value = getattr(repo, name, None)
                if value is not None:
                    if callable(getattr(value, "list_playbooks", None)):
                        try:
                            return list(value.list_playbooks())
                        except (OSError, RuntimeError, ValueError, TypeError):
                            pass
                    if isinstance(value, (list, tuple)):
                        return list(value)
        try:
            return load_builtin_playbooks()
        except (OSError, RuntimeError, ValueError, TypeError):
            return []

    def _incident_manager(self):
        if self.incident_manager is not None:
            return self.incident_manager
        repo = self.repo
        if repo is not None:
            for name in ("incident_manager", "incidents", "incident_repo", "incident_repository"):
                value = getattr(repo, name, None)
                if value is not None:
                    return value
        conn = self._connection()
        if conn is not None:
            return IncidentManager(conn)
        return None

    def _host_fields(self, host):
        def get(name, default=None):
            if isinstance(host, dict):
                return host.get(name, default)
            return getattr(host, name, default)

        return {
            "execution_mode": get("execution_mode", "local") or "local",
            "ssh_user": get("ssh_user", None),
            "address": get("address", "127.0.0.1") or "127.0.0.1",
            "ssh_key_path": get("ssh_key_path", None),
            "ssh_port": get("ssh_port", 22) or 22,
            "id": get("id", "local"),
        }

    def collect_once(self):
        settings = self.settings
        conn = self._connection()
        for host in self._hosts():
            fields = self._host_fields(host)
            try:
                shell = ShellRunner(
                    execution_mode=fields["execution_mode"],
                    ssh_user=fields["ssh_user"],
                    address=fields["address"],
                    ssh_key_path=fields["ssh_key_path"],
                    ssh_port=fields["ssh_port"],
                )
                snapshot = collect_native_snapshot(
                    shell,
                    host_id=fields["id"],
                    interval_seconds=getattr(settings, "interval_seconds", 30),
                )
                self._persist_snapshot(conn, fields["id"], snapshot, settings)
            except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error, KeyError, AttributeError):
                logger.exception("collection failed for host %s", fields["id"])
                continue
            analyzer = self.analyzer
            if analyzer is not None:
                try:
                    analysis = analyzer.analyze(snapshot, self._playbooks())
                    if getattr(analysis, "status", None) == "issue" and getattr(analysis, "playbook_id", None):
                        manager = self._incident_manager()
                        if manager is not None and callable(getattr(manager, "create_issue", None)):
                            manager.create_issue(
                                fields["id"],
                                getattr(analysis, "issue_id", "") or "issue",
                                getattr(analysis, "severity", "warning"),
                                getattr(analysis, "issue_id", "") or "issue",
                                getattr(analysis, "explanation", ""),
                            )
                except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error, KeyError, AttributeError):
                    logger.exception("analysis failed for host %s", fields["id"])
        audit = self._audit()
        if audit is not None:
            try:
                audit.record("metric_collection_completed")
            except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
                pass
        self._collect_count += 1

    def _persist_snapshot(self, conn, host_id, snapshot, settings):
        if conn is None:
            return
        try:
            conn.execute(
                """INSERT INTO metric_snapshots (id, host_id, collected_at, interval_seconds, snapshot_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    str(host_id),
                    str(snapshot.get("collected_at", datetime.now(UTC).isoformat())),
                    int(getattr(settings, "interval_seconds", 30)),
                    json.dumps(snapshot, default=str),
                ),
            )
            conn.commit()
        except (sqlite3.Error, ValueError, TypeError):
            try:
                conn.rollback()
            except sqlite3.Error:
                pass

    async def _run(self):
        settings = self.settings
        interval = int(getattr(settings, "interval_seconds", 30) or 30)
        while not self._stopped:
            try:
                await asyncio.to_thread(self.collect_once)
            except (asyncio.CancelledError, RuntimeError, ValueError, TypeError):
                pass
            if self._stopped:
                break
            try:
                await asyncio.sleep(interval)
            except (asyncio.CancelledError, RuntimeError):
                break

    def _thread_main(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._task = self._loop.create_task(self._run())
        try:
            self._loop.run_until_complete(self._task)
        except (asyncio.CancelledError, RuntimeError):
            pass
        finally:
            try:
                self._loop.close()
            except RuntimeError:
                pass

    @staticmethod
    def start_background(settings=None, repo=None, **kwargs):
        instance = Scheduler(settings=settings, repo=repo, **kwargs)
        instance.started = True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            instance._thread = None
            instance._task = loop.create_task(instance._run())
        else:
            thread = threading.Thread(target=instance._thread_main, daemon=True, name="opspilot-scheduler")
            instance._thread = thread
            thread.start()
        return instance

    def stop(self):
        self._stopped = True
        if self._task is not None and self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(self._task.cancel)
            except RuntimeError:
                pass
        if self._task is not None and self._loop is None:
            try:
                self._task.cancel()
            except RuntimeError:
                pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
