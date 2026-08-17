"""Bootstrap must grant onboard_owner CREATE on the database, not SUPERUSER."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "scripts" / "bootstrap_rls_roles.py"


def test_bootstrap_grants_owner_create_on_database() -> None:
    text = BOOTSTRAP.read_text(encoding="utf-8")
    assert 'GRANT CREATE ON DATABASE "{dbname}" TO onboard_owner' in text
    assert text.count("GRANT CREATE ON DATABASE") == 1
    assert 'GRANT CREATE ON DATABASE "{dbname}" TO onboard_app' not in text
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE" in text
    assert "CREATE ROLE onboard_owner LOGIN PASSWORD {owner_lit} " in text
    assert "ALTER ROLE onboard_owner BYPASSRLS" in text
    assert "ALTER ROLE onboard_app NOBYPASSRLS" in text
    assert "ALTER ROLE onboard_owner SUPERUSER" not in text
    assert "ALTER ROLE onboard_owner CREATEDB" not in text
