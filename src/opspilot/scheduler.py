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
from opspilot.db import prune_snapshots
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
    def __init__(
        self,
        settings=None,
        repo=None,
        *,
        analyzer=None,
        safety_guard=None,
        executor=None,
        incident_manager=None,
        playbooks=None,
        audit=None,
        write_lock=None,
    ):
        self.settings = self._coerce_settings(settings)
        self.repo = repo
        self.conn = repo if isinstance(repo, sqlite3.Connection) else None
        self.analyzer = analyzer
        self.safety_guard = safety_guard
        self.executor = executor
        self.incident_manager = incident_manager if incident_manager is not None else self._default_incident_manager()
        self._playbook_list = playbooks
        self.audit = audit if audit is not None else self._default_audit()
        self.write_lock = write_lock if write_lock is not None else threading.Lock()
        self.started = False
        self._stopped = False
        self._thread = None
        self._loop = None
        self._task = None
        self._collect_count = 0

    @staticmethod
    def _coerce_settings(settings):
        if isinstance(settings, Settings):
            return settings
        if settings is not None and hasattr(settings, "interval_seconds") and hasattr(settings, "data_dir"):
            return settings
        return Settings()

    def _default_incident_manager(self):
        if self.conn is None:
            return None
        return IncidentManager(conn=self.conn)

    def _default_audit(self):
        if self.conn is None:
            return None
        return AuditRepository(self.conn)

    def _hosts(self):
        if self.conn is not None:
            try:
                hosts = HostRepository(self.conn).list_hosts()
            except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
                hosts = []
            active = [h for h in hosts if getattr(h, "is_active", True)]
            if active:
                return active
        return [default_local_host()]

    def _playbooks(self):
        if self._playbook_list is not None:
            if callable(getattr(self._playbook_list, "list_playbooks", None)):
                try:
                    return list(self._playbook_list.list_playbooks())
                except (OSError, RuntimeError, ValueError, TypeError):
                    pass
            if isinstance(self._playbook_list, (list, tuple)):
                return list(self._playbook_list)
        try:
            return load_builtin_playbooks()
        except (OSError, RuntimeError, ValueError, TypeError):
            return []

    @staticmethod
    def _find_playbook(playbooks, playbook_id):
        for playbook in playbooks or []:
            if getattr(playbook, "id", None) == playbook_id:
                return playbook
        return None

    def _shell_for(self, host):
        return ShellRunner(
            execution_mode=getattr(host, "execution_mode", "local") or "local",
            ssh_user=getattr(host, "ssh_user", None),
            address=getattr(host, "address", "127.0.0.1") or "127.0.0.1",
            ssh_key_path=getattr(host, "ssh_key_path", None),
            ssh_port=getattr(host, "ssh_port", 22) or 22,
        )

    def collect_once(self):
        settings = self.settings
        interval = int(getattr(settings, "interval_seconds", 30) or 30)
        for host in self._hosts():
            host_id = getattr(host, "id", "local")
            try:
                snapshot = collect_native_snapshot(
                    self._shell_for(host),
                    host_id=host_id,
                    interval_seconds=interval,
                )
                self._persist_snapshot(self.conn, host_id, snapshot, settings)
            except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error, KeyError, AttributeError):
                logger.exception("collection failed for host %s", host_id)
                continue
            if self.analyzer is None:
                continue
            with self.write_lock:
                try:
                    analysis = self.analyzer.analyze(snapshot, self._playbooks())
                except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error, KeyError, AttributeError):
                    logger.exception("analysis failed for host %s", host_id)
                    continue
                try:
                    self.handle_analysis(host, snapshot, analysis)
                except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error, KeyError, AttributeError):
                    logger.exception("incident handling failed for host %s", host_id)
        self._prune()
        if self.audit is not None:
            try:
                self.audit.record("metric_collection_completed")
            except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
                pass
        self._collect_count += 1

    def handle_analysis(self, host, snapshot, analysis):
        """Run the spec lifecycle: dedup -> guard -> execute/confirm/block/recommend."""
        if getattr(analysis, "status", None) != "issue":
            return None
        playbook_id = getattr(analysis, "playbook_id", None)
        if not playbook_id:
            return None
        host_id = getattr(host, "id", "local")
        issue_id = getattr(analysis, "issue_id", "") or "issue"
        manager = self.incident_manager
        if manager is None:
            return None

        repository = getattr(manager, "repository", None)
        if (
            repository is not None
            and callable(getattr(repository, "find_active", None))
            and repository.find_active(host_id, issue_id) is not None
        ):
            return None

        playbooks = self._playbooks()
        playbook = self._find_playbook(playbooks, playbook_id)
        if playbook is None:
            self._audit("playbook_missing", host_id, {"playbook_id": playbook_id}, "playbook not in catalog")
            return None

        incident = manager.create_issue(
            host_id,
            issue_id,
            getattr(analysis, "severity", "warning"),
            getattr(analysis, "summary", issue_id) or issue_id,
            getattr(analysis, "explanation", ""),
            playbook_id=playbook.id,
            verifier_id=playbook.verifier_id,
        )
        guard = self.safety_guard
        safety = guard.evaluate(playbook, host, self.settings, audit=self.audit) if guard is not None else None
        if safety is not None and not safety.allowed:
            manager.mark_blocked(incident, reason="; ".join(safety.reasons))
            self._audit("incident_blocked", host_id, {"incident_id": incident.id, "reasons": safety.reasons}, "blocked")
            return incident
        if safety is not None and safety.requires_confirmation:
            manager.mark_pending_confirmation(incident)
            self._audit(
                "incident_pending_confirmation",
                host_id,
                {"incident_id": incident.id, "playbook_id": playbook_id},
                "awaiting confirmation",
            )
            return incident

        self.execute_incident(incident, playbook, host, snapshot)
        return incident

    def execute_incident(self, incident, playbook, host, snapshot):
        manager = self.incident_manager
        if manager is None or self.executor is None:
            return incident
        playbooks = self._playbooks()
        verifier = self._find_playbook(playbooks, playbook.verifier_id) if playbook.verifier_id else None
        recheck = self._make_recheck(host)
        outcome = self.executor.run(playbook, host, verifier=verifier, metric_recheck=recheck)
        self._record_run(incident, playbook, verifier, outcome)
        if outcome.blocked:
            reason = "; ".join(outcome.safety.reasons) if outcome.safety is not None else outcome.stderr
            manager.mark_blocked(incident, reason=reason)
            self._audit("incident_blocked", incident.host_id, {"incident_id": incident.id}, "blocked at execution")
        elif outcome.healthy:
            manager.mark_resolved(incident, verifier_output=outcome.stdout)
            self._audit("incident_resolved", incident.host_id, {"incident_id": incident.id}, "resolved")
        else:
            self._recommend(incident, snapshot)
        return incident

    def _recommend(self, incident, snapshot):
        manager = self.incident_manager
        if manager is None:
            return incident
        explanation = "remediation did not resolve the issue"
        playbook_id = None
        verifier_id = None
        if self.analyzer is not None:
            try:
                rec = self.analyzer.analyze_recommendation(snapshot, self._playbooks())
                playbook_id = getattr(rec, "playbook_id", None)
                verifier_id = getattr(rec, "verifier_id", None)
                explanation = getattr(rec, "explanation", "") or explanation
            except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
                logger.warning("recommendation analysis failed: %s", exc)
        manager.recommend(
            incident,
            playbook_id=playbook_id,
            verifier_id=verifier_id,
            explanation=explanation,
        )
        self._audit(
            "incident_unresolved_recommended",
            incident.host_id,
            {"incident_id": incident.id, "recommended_playbook_id": playbook_id},
            "unresolved; recommendation recorded",
        )
        return incident

    def _make_recheck(self, host):
        analyzer = self.analyzer
        if analyzer is None:
            return None
        settings = self.settings
        interval = int(getattr(settings, "interval_seconds", 30) or 30)
        host_id = getattr(host, "id", "local")

        def recheck() -> bool:
            snapshot = collect_native_snapshot(self._shell_for(host), host_id=host_id, interval_seconds=interval)
            result = analyzer.analyze(snapshot, self._playbooks())
            return getattr(result, "status", "") == "ok"

        return recheck

    def _record_run(self, incident, playbook, verifier, outcome):
        repository = getattr(self.incident_manager, "repository", None)
        if repository is None or not callable(getattr(repository, "record_run", None)):
            return
        status = "blocked" if outcome.blocked else ("completed" if outcome.healthy else "unresolved")
        try:
            repository.record_run(
                incident.id,
                host_id=incident.host_id,
                playbook_id=getattr(playbook, "id", None),
                verifier_id=getattr(verifier, "id", None),
                status=status,
                exit_code=0 if outcome.healthy else 1,
                stdout=outcome.stdout,
                stderr=outcome.stderr,
                detail={"metric_recheck": outcome.metric_recheck},
            )
        except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
            pass

    def _audit(self, event_type, host_id, detail, message=""):
        if self.audit is None:
            return
        try:
            self.audit.record(event_type, host_id=host_id, message=message, detail=detail)
        except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
            pass

    def _prune(self):
        if self.conn is None:
            return
        days = int(getattr(self.settings, "snapshot_retention_days", 7) or 7)
        try:
            prune_snapshots(self.conn, days)
        except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
            pass

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
        interval = int(getattr(self.settings, "interval_seconds", 30) or 30)
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
