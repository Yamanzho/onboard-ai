"""Phase 7E migration stays conservative and reversible."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "alembic" / "versions" / "d1e2f3a4b5c6_kb_version_index_state.py"


def test_kb_index_state_migration_is_linear_and_reversible() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'down_revision: str | Sequence[str] | None = "c0d1e2f3a4b5"' in source
    assert "def upgrade()" in source
    assert "def downgrade()" in source
    assert "op.drop_column(_TABLE, column)" in source


def test_kb_index_backfill_requires_proven_complete_known_chunks() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert "proven.min_chunk_index = 0" in source
    assert "proven.max_chunk_index = proven.chunk_count - 1" in source
    assert "proven.model_count = 1" in source
    assert "proven.model_value_count = proven.chunk_count" in source
    assert "proven.dimension_ok" in source
    assert "('fake', 'text-embedding-3-small')" in source
    assert 'server_default="pending"' in source
