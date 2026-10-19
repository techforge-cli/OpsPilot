import tempfile
from pathlib import Path

from opspilot.license import (
    generate_license,
    load_license,
    save_license,
    validate_license,
)

KEY = "test-secret-key"


def test_license_roundtrip():
    lic = generate_license(KEY, "TestCorp", expires_days=365, max_hosts=5)
    ok, msg = validate_license(lic, KEY)
    assert ok
    assert msg == "valid"


def test_license_expired():
    lic = generate_license(KEY, "TestCorp", expires_days=365)
    lic["expires_at"] = "2020-01-01T00:00:00+00:00"
    ok, msg = validate_license(lic, KEY)
    assert not ok
    assert "expired" in msg


def test_license_wrong_machine():
    lic = generate_license(KEY, "TestCorp")
    lic["fingerprint"] = "a" * 32
    ok, msg = validate_license(lic, KEY)
    assert not ok
    assert "machine" in msg


def test_license_forged():
    lic = generate_license(KEY, "TestCorp", expires_days=365)
    lic["signature"] = "forged"
    ok, msg = validate_license(lic, KEY)
    assert not ok
    assert "signature" in msg


def test_license_save_and_load():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "license.yml"
        lic = generate_license(KEY, "TestCorp")
        save_license(lic, p)
        loaded = load_license(p)
        assert loaded is not None
        ok, _ = validate_license(loaded, KEY)
        assert ok


def test_license_load_missing():
    with tempfile.TemporaryDirectory() as d:
        loaded = load_license(Path(d) / "nonexistent.yml")
        assert loaded is None


def test_license_empty():
    ok, msg = validate_license(None, KEY)
    assert not ok
    assert "no license" in msg
