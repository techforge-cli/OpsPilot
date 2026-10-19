import json

from opspilot.journal import AuditJournal


def test_append_is_permanent_jsonl(tmp_path):
    journal = AuditJournal(tmp_path / "audit.jsonl")
    journal.append({"event": "test"})
    assert json.loads((tmp_path / "audit.jsonl").read_text().strip())["event"] == "test"


def test_audit_journal_hash_chain(tmp_path):
    j = AuditJournal(tmp_path / "audit.jsonl", secret="s3cret")
    j.append({"event": "one"})
    j.append({"event": "two"})
    j.append({"event": "three"})
    issues = j.verify()
    assert issues == []


def test_audit_journal_detects_tampering(tmp_path):
    j = AuditJournal(tmp_path / "audit.jsonl", secret="s3cret")
    j.append({"event": "one"})
    j.append({"event": "two"})
    lines = j.path.read_text().strip().splitlines()
    tampered = json.loads(lines[0])
    tampered["event"] = "HACKED"
    lines[0] = json.dumps(tampered)
    j.path.write_text("\n".join(lines) + "\n")
    issues = j.verify()
    assert len(issues) > 0
