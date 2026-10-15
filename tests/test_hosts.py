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


def test_get_host_and_host_id():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "db.sqlite"
        init_db(path)
        conn = connect(path)
        repo = HostRepository(conn)
        host = default_local_host()
        repo.save(host)
        found = repo.get_host("local")
        assert found is not None
        assert found.id == "local"
