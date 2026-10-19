import hashlib
import hmac
import json
import platform
import socket
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml


def _machine_fingerprint() -> str:
    components = [
        platform.node(),
        platform.machine(),
        platform.processor() or "",
        str(uuid.getnode()),
        socket.gethostname(),
    ]
    return hashlib.sha256("|".join(components).encode()).hexdigest()[:32]


def generate_license(private_key: str, customer: str, expires_days: int = 365, max_hosts: int = 10) -> dict:
    license_data = {
        "customer": customer,
        "issued_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(days=expires_days)).isoformat(),
        "max_hosts": max_hosts,
        "fingerprint": _machine_fingerprint(),
    }
    payload = json.dumps(license_data, sort_keys=True)
    signature = hmac.new(private_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    license_data["signature"] = signature
    return license_data


def validate_license(license_data: dict | None, private_key: str) -> tuple[bool, str]:
    if not license_data:
        return False, "no license file found"

    required = ["customer", "issued_at", "expires_at", "max_hosts", "fingerprint", "signature"]
    for field in required:
        if field not in license_data:
            return False, f"missing field: {field}"

    try:
        expires = datetime.fromisoformat(license_data["expires_at"])
        if expires < datetime.now(UTC):
            return False, "license expired"
    except (ValueError, TypeError):
        return False, "invalid expiration date"

    if license_data["fingerprint"] != _machine_fingerprint():
        return False, "license not valid for this machine"

    payload = json.dumps({k: v for k, v in license_data.items() if k != "signature"}, sort_keys=True)
    expected = hmac.new(private_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(license_data["signature"], expected):
        return False, "invalid signature"

    return True, "valid"


def save_license(license_data: dict, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(license_data, default_flow_style=False))


def load_license(path: str | Path) -> dict | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text())
    except (yaml.YAMLError, OSError):
        return None
