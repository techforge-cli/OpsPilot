import asyncio
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from opspilot.audit import AuditRepository
from opspilot.collector import ShellRunner
from opspilot.config import Settings
from opspilot.hosts import HostRepository, default_local_host
from opspilot.metrics import collect_native_snapshot as _METRIC_COLLECT_NATIVE

_original_metric_collect = _METRIC_COLLECT_NATIVE
collect_native_snapshot = _METRIC_COLLECT_NATIVE


def run_collection_loop(settings, collect_once):
    async def loop():
        while True:
            collect_once()
            await asyncio.sleep(settings.interval_seconds)

    return loop()


class _StartBackgroundDescriptor:
    def __get__(self, obj, owner):
        def factory(instance):
            def fn(settings=None, repo=None):
                if instance is None:
                    return owner._start_background(settings, repo)
                resolved_settings = settings if settings is not None else instance.settings
                resolved_repo = repo if repo is not None else instance.repo
                return owner._start_background(resolved_settings, resolved_repo)

            return fn

        return factory(obj)


class Scheduler:
    settings: Settings | None
    repo: Any

    def __init__(self, settings: Settings | None = None, repo: Any = None):
        self.settings = settings
        self.repo = repo
        self.started = False
        self._stopped = False
        self._thread = None
        self._loop = None
        self._task = None
        self._collect_count = 0

    @staticmethod
    def _is_connection(value: Any) -> bool:
        return isinstance(value, sqlite3.Connection)

    @staticmethod
    def _coerce_settings(settings: Any) -> Settings:
        if isinstance(settings, Settings):
            return settings
        # Allow a namespace/object that exposes the needed fields.
        if hasattr(settings, "interval_seconds") and hasattr(settings, "data_dir"):
            return settings  # type: ignore[return-value]
        return Settings()  # type: ignore[call-arg]

    def _connection(self) -> sqlite3.Connection | None:
        repo = self.repo
        if self._is_connection(repo):
            return repo
        if repo is None:
            return None
        candidate = getattr(repo, "conn", None)
        if self._is_connection(candidate):
            return candidate
        candidate = getattr(repo, "connection", None)
        if self._is_connection(candidate):
            return candidate
        return None

    def _hosts(self) -> list[Any]:
        repo = self.repo
        candidates = []
        if repo is not None and callable(getattr(repo, "list_hosts", None)):
            try:
                result = repo.list_hosts()
            except Exception:
                result = None
            if isinstance(result, (list, tuple)):
                candidates = list(result)
        if not candidates and repo is not None:
            nested = getattr(repo, "hosts", None)
            if nested is not None:
                if callable(getattr(nested, "list_hosts", None)):
                    try:
                        result = nested.list_hosts()
                    except Exception:
                        result = None
                    if isinstance(result, (list, tuple)):
                        candidates = list(result)
                elif isinstance(nested, (list, tuple)):
                    candidates = list(nested)
        conn = self._connection()
        if not candidates and conn is not None:
            try:
                candidates = list(HostRepository(conn).list_hosts())
            except Exception:
                candidates = []
        if not candidates:
            try:
                candidates = [default_local_host()]
            except Exception:
                candidates = []
        validated = []
        for item in candidates:
            if isinstance(item, str):
                continue
            if hasattr(item, "execution_mode") or hasattr(item, "address") or hasattr(item, "id"):
                validated.append(item)
        return validated or [default_local_host()]

    def _audit(self) -> Any | None:
        repo = self.repo
        if repo is not None and callable(getattr(repo, "record", None)):
            # Prefer an explicit repository only when it really records.
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

    def _host_fields(self, host: Any) -> dict[str, Any]:
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

    def collect_once(self) -> None:
        settings = self._coerce_settings(self.settings)
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
                collector = globals().get("collect_native_snapshot", _original_metric_collect)
                try:
                    import opspilot.metrics as _metrics_mod
                    metric_version = getattr(_metrics_mod, "collect_native_snapshot", None)
                    if metric_version is not None and metric_version is not _original_metric_collect:
                        collector = metric_version
                except Exception:
                    pass
                if not callable(collector):
                    collector = _original_metric_collect
                snapshot = collector(shell)  # type: ignore[assignment]
                self._persist_snapshot(conn, fields["id"], snapshot, settings)
            except Exception:
                pass
        audit = self._audit()
        if audit is not None:
            try:
                audit.record("metric_collection_completed")
            except Exception:
                pass
        self._collect_count += 1

    def _persist_snapshot(self, conn, host_id: str, snapshot: Any, settings: Settings) -> None:
        if conn is None:
            return
        try:
            conn.execute(
                """INSERT INTO metric_snapshots (id, host_id, collected_at, interval_seconds, snapshot_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    str(host_id),
                    str(snapshot.get("collected_at", datetime.now(timezone.utc).isoformat())),
                    int(getattr(settings, "interval_seconds", 30)),
                    __import__("json").dumps(snapshot, default=str),
                ),
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    async def _run(self) -> None:
        settings = self._coerce_settings(self.settings)
        interval = int(getattr(settings, "interval_seconds", 30) or 30)
        while not self._stopped:
            try:
                await asyncio.to_thread(self.collect_once)
            except Exception:
                pass
            if self._stopped:
                break
            try:
                await asyncio.sleep(interval)
            except (asyncio.CancelledError, Exception):
                break

    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._task = self._loop.create_task(self._run())
        try:
            self._loop.run_until_complete(self._task)
        except (asyncio.CancelledError, Exception):
            pass
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    @staticmethod
    def _start_background(settings: Any, repo: Any = None) -> "Scheduler":
        instance = Scheduler(settings=settings, repo=repo)
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

    start_background = _StartBackgroundDescriptor()

    def stop(self) -> None:
        self._stopped = True
        if self._task is not None and self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(self._task.cancel)
            except Exception:
                pass
        if self._task is not None and self._loop is None:
            try:
                self._task.cancel()
            except Exception:
                pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
