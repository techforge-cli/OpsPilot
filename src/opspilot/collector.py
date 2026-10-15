import shlex
import subprocess
import time


class ShellRunner:
    def __init__(self, execution_mode="local", ssh_user=None, address=None, ssh_key_path=None, ssh_port=22):
        self.execution_mode = execution_mode
        self.ssh_user = ssh_user
        self.address = address
        self.ssh_key_path = ssh_key_path
        self.ssh_port = ssh_port

    def run(self, command: str, timeout: int = 15):
        start = time.monotonic()
        if self.execution_mode == "ssh":
            argv = [
                "ssh", "-i", self.ssh_key_path, "-p", str(self.ssh_port),
                "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
                f"{self.ssh_user}@{self.address}", "bash", "-lc", command,
            ]
        else:
            argv = ["bash", "-lc", command]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr, time.monotonic() - start
