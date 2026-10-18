import yaml

from opspilot.playbooks import Playbook, load_builtin_playbooks


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
    assert playbook.verifier_id == "verify-test"
    assert playbook.commands() == ["echo ok"]


def test_load_builtin_playbooks():
    playbooks = load_builtin_playbooks()
    assert any(playbook.id == "sample-noop" for playbook in playbooks)
    assert all(playbook.is_builtin for playbook in playbooks)
