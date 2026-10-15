import json
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
