"""Alembic graph must stay a single head (migration consistency)."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]
M4B = ROOT / "alembic" / "versions" / "f5e6f7a8b9c0_rls_m4b_companies_update.py"


def test_alembic_has_single_head() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert len(heads) == 1, f"expected one Alembic head, got {heads}"


def test_companies_m4b_upgrade_drops_policies_before_create() -> None:
    """f4 already creates companies_*; f5 must DROP IF EXISTS before CREATE."""
    text = M4B.read_text(encoding="utf-8")
    upgrade = text.split("def downgrade()", 1)[0]
    assert 'DROP POLICY IF EXISTS tenant_isolation ON "companies"' in upgrade
    for policy in (
        "companies_select",
        "companies_update",
        "companies_insert",
        "companies_delete",
    ):
        drop = f'DROP POLICY IF EXISTS {policy} ON "companies"'
        create = f"CREATE POLICY {policy} ON \"companies\""
        assert drop in upgrade, f"f5 upgrade missing {drop}"
        assert create in upgrade, f"f5 upgrade missing {create}"
        assert upgrade.index(drop) < upgrade.index(create), f"{policy} DROP must precede CREATE"
