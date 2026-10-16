import json
from pathlib import Path

from opspilot.journal import AuditJournal


def test_append_is_permanent_jsonl(tmp_path):
    journal = AuditJournal(tmp_path / "audit.jsonl")
    journal.append({"event": "test"})
    assert json.loads((tmp_path / "audit.jsonl").read_text().strip())["event"] == "test"
