import httpx

from opspilot.analyzer import Analyzer
from opspilot.audit import AuditRepository
from opspilot.config import Settings
from opspilot.executor import PlaybookExecutor
from opspilot.incidents import IncidentManager
from opspilot.playbooks import load_builtin_playbooks
from opspilot.safety import SafetyGuard


def build_runtime(settings: Settings, conn, audit_repo=None):
    if audit_repo is None:
        audit_repo = AuditRepository(conn, journal_path=None)
    client = httpx.Client(timeout=getattr(settings, "ollama_timeout", 60))
    analyzer = Analyzer(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        client=client,
        audit=audit_repo,
        timeout=getattr(settings, "ollama_timeout", 60),
    )
    safety_guard = SafetyGuard()
    executor = PlaybookExecutor(settings=settings, safety_guard=safety_guard, audit=audit_repo)
    incident_manager = IncidentManager(conn=conn, audit=audit_repo)
    catalog = load_builtin_playbooks()
    return {
        "analyzer": analyzer,
        "safety_guard": safety_guard,
        "executor": executor,
        "incident_manager": incident_manager,
        "playbooks": catalog,
    }
