import sqlite3

from opspilot.models import Host


class HostRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def save(self, host: Host) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO hosts
               (id, name, address, execution_mode, ssh_user, ssh_port, ssh_key_path, tags_json, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                host.id,
                host.name,
                host.address,
                host.execution_mode,
                host.ssh_user,
                host.ssh_port,
                host.ssh_key_path,
                host.tags_json(),
                int(host.is_active),
            ),
        )
        self.conn.commit()

    def list_hosts(self) -> list[Host]:
        rows = self.conn.execute("SELECT * FROM hosts ORDER BY name").fetchall()
        return [Host.from_row(row) for row in rows]

    def get_host(self, host_id: str) -> Host | None:
        row = self.conn.execute("SELECT * FROM hosts WHERE id = ?", (host_id,)).fetchone()
        return Host.from_row(row) if row else None


def default_local_host() -> Host:
    return Host("local", "Local admin box", "127.0.0.1", execution_mode="local")
