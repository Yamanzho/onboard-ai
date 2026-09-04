"""Phase 9D: ordered text blocks and legacy Step.content compatibility."""

from __future__ import annotations

import pytest

from app.core.exceptions import ValidationError
from app.services.step_content import (
    normalize_step_content,
    payload_block_index,
    validate_step_content,
)


def test_normalize_new_blocks_preserves_order() -> None:
    content = {
        "blocks": [
            {"id": "b2", "type": "text", "text": "Second first in id"},
            {"id": "b1", "type": "text", "text": "Actually second"},
        ]
    }
    blocks = normalize_step_content(content)
    assert [block.text for block in blocks] == [
        "Second first in id",
        "Actually second",
    ]
    assert [block.id for block in blocks] == ["b2", "b1"]


def test_normalize_legacy_body_and_text() -> None:
    assert normalize_step_content({"body": "  Hello  "})[0].text == "Hello"
    assert normalize_step_content({"text": "Legacy"})[0].text == "Legacy"
    assert normalize_step_content({"body": "Body", "text": "Ignored"})[0].text == "Body"


def test_normalize_prefers_blocks_over_legacy() -> None:
    content = {
        "body": "Old",
        "blocks": [{"type": "text", "text": "New"}],
    }
    blocks = normalize_step_content(content)
    assert len(blocks) == 1
    assert blocks[0].text == "New"


def test_normalize_does_not_mutate_stored_json() -> None:
    original = {
        "body": "Keep me",
        "blocks": [{"id": "x", "type": "text", "text": "Block"}],
    }
    snapshot = {
        "body": "Keep me",
        "blocks": [{"id": "x", "type": "text", "text": "Block"}],
    }
    normalize_step_content(original)
    assert original == snapshot


def test_normalize_skips_invalid_block_items_on_read() -> None:
    blocks = normalize_step_content(
        {
            "blocks": [
                "skip-me",
                {"type": "video", "text": "nope"},
                {"type": "text", "text": "ok"},
            ]
        }
    )
    assert [block.text for block in blocks] == ["ok"]


def test_validate_rejects_invalid_blocks() -> None:
    with pytest.raises(ValidationError, match="list"):
        validate_step_content("content", {"blocks": "nope"})
    with pytest.raises(ValidationError, match="type"):
        validate_step_content(
            "content",
            {"blocks": [{"type": "video", "text": "x"}]},
        )
    with pytest.raises(ValidationError, match="text"):
        validate_step_content("content", {"blocks": [{"type": "text"}]})


def test_validate_accepts_text_blocks_and_legacy() -> None:
    validate_step_content(
        "content",
        {"blocks": [{"id": "a", "type": "text", "text": "Hi"}]},
    )
    validate_step_content("content", {"body": "legacy"})
    validate_step_content("content", {"text": "also legacy"})


def test_payload_block_index() -> None:
    assert payload_block_index({"block_index": 2}) == 2
    assert payload_block_index({"block_index": "3"}) == 3
    assert payload_block_index({"block_index": -1}) is None
    assert payload_block_index({}) is None
    assert payload_block_index(None) is None
