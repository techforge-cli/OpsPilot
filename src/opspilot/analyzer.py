import contextlib
import json
import logging

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger("opspilot.analyzer")


class Analysis(BaseModel):
    status: str
    severity: str = "info"
    explanation: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    issue_id: str = ""
    playbook_id: str | None = None
    verifier_id: str | None = None
    recommended: bool = False


class AnalysisFailedError(RuntimeError):
    pass


class Analyzer:
    def __init__(self, base_url: str, model: str, client, *args, **kwargs):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = client
        self.audit = kwargs.get("audit", kwargs.get("audit_repo", kwargs.get("audit_repository")))
        if self.audit is None and args:
            self.audit = args[0]
        self.logger = kwargs.get("logger", logger)
        self.timeout = kwargs.get("timeout", 60)

    def _catalog_ids(self, playbooks):
        ids = set()
        for playbook in playbooks or []:
            if isinstance(playbook, dict):
                if "id" in playbook:
                    ids.add(playbook["id"])
            else:
                pid = getattr(playbook, "id", None)
                if pid is not None:
                    ids.add(pid)
        return ids

    def _post(self, body):
        response = self.client.post(f"{self.base_url}/v1/chat/completions", json=body, timeout=self.timeout)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def _body(self, snapshot, playbooks, recommendation=False):
        catalog = []
        for p in playbooks or []:
            if isinstance(p, dict):
                catalog.append({"id": p.get("id"), "description": p.get("description", "")})
            else:
                catalog.append({"id": getattr(p, "id", None), "description": getattr(p, "description", "")})
        schema = "Return JSON only with fields status, explanation, recommended_playbook_id, recommended_verifier_id." if recommendation else "Return JSON only with the exact fields status, severity, explanation, confidence, issue_id, playbook_id, verifier_id, recommended. Never return commands."
        return {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": schema},
                {"role": "user", "content": json.dumps({"snapshot": snapshot, "playbooks": catalog})},
            ],
        }

    def _parse(self, content, catalog_ids, recommendation=False, host_id=None):
        data = json.loads(content)
        if recommendation:
            data = {
                "status": data.get("status", "issue"),
                "severity": data.get("severity", "info"),
                "explanation": data.get("explanation", ""),
                "confidence": data.get("confidence", 0.0),
                "issue_id": data.get("issue_id", ""),
                "playbook_id": data.get("recommended_playbook_id", data.get("playbook_id")),
                "verifier_id": data.get("recommended_verifier_id", data.get("verifier_id")),
                "recommended": True,
            }
        analysis = Analysis.model_validate(data)
        if analysis.status == "ok":
            analysis.playbook_id = None
            analysis.verifier_id = None
        if analysis.playbook_id is not None and analysis.playbook_id not in catalog_ids:
            raise ValueError("unknown playbook_id")
        if analysis.verifier_id is not None and analysis.verifier_id not in catalog_ids:
            raise ValueError("unknown verifier_id")
        return analysis

    def _log_failure(self, host_id=None, detail=None, audit=None):
        target_audit = audit if audit is not None else self.audit
        if target_audit is not None and callable(getattr(target_audit, "record", None)):
            with contextlib.suppress(OSError, RuntimeError, ValueError, TypeError):
                target_audit.record("analysis_failed", host_id=host_id, message="analysis failed", detail=detail or {})
        with contextlib.suppress(OSError, RuntimeError, ValueError, TypeError):
            self.logger.warning("analysis_failed")

    def analyze(self, snapshot, playbooks, *args, **kwargs):
        audit = kwargs.get("audit", kwargs.get("audit_repo", kwargs.get("audit_repository", self.audit)))
        host_id = None
        if isinstance(snapshot, dict):
            host_id = snapshot.get("host_id")
        catalog_ids = self._catalog_ids(playbooks)
        recommendation = bool(kwargs.get("recommendation", kwargs.get("recommended", False)))
        last_error = None
        for attempt in range(2):
            try:
                content = self._post(self._body(snapshot, playbooks, recommendation))
                return self._parse(content, catalog_ids, recommendation, host_id)
            except (OSError, RuntimeError, ValueError, TypeError, KeyError, httpx.HTTPError) as exc:
                last_error = exc
                continue
        self._log_failure(host_id=host_id, detail={"error": str(last_error)}, audit=audit)
        return Analysis(status="issue", severity="warning", explanation="analysis failed", confidence=0.0, issue_id="analysis_failed", playbook_id=None, verifier_id=None, recommended=False)

    def analyze_recommendation(self, snapshot, playbooks, *args, **kwargs):
        kwargs = dict(kwargs)
        kwargs["recommendation"] = True
        return self.analyze(snapshot, playbooks, *args, **kwargs)

    def recommend(self, *args, **kwargs):
        # accept analyze(snapshot, playbooks) style
        if args and isinstance(args[0], dict):
            snapshot = args[0]
            playbooks = args[1] if len(args) > 1 else kwargs.get("playbooks", [])
            return self.analyze_recommendation(snapshot, playbooks, *args[2:], **kwargs)
        return None
