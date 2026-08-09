"""F-09: JWT iss/aud binding and algorithm / claim adversarial cases."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_token,
)
from app.db.enums import EmployeeRole


def test_decode_accepts_valid_iss_aud() -> None:
    token = create_access_token(
        subject=uuid4(),
        role=EmployeeRole.ADMIN.value,
        company_id=uuid4(),
    )
    payload = decode_token(token, expected_type="access")
    settings = get_settings()
    assert payload["iss"] == settings.jwt_issuer
    assert payload["aud"] == settings.jwt_audience
    assert payload["type"] == "access"


def test_decode_rejects_missing_iss() -> None:
    settings = get_settings()
    subject = uuid4()
    token = jwt.encode(
        {
            "sub": str(subject),
            "role": EmployeeRole.ADMIN.value,
            "company_id": None,
            "type": "access",
            "aud": settings.jwt_audience,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iat": datetime.now(UTC),
        },
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(InvalidTokenError):
        decode_token(token, expected_type="access")


def test_decode_rejects_missing_aud() -> None:
    settings = get_settings()
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "role": EmployeeRole.ADMIN.value,
            "company_id": None,
            "type": "access",
            "iss": settings.jwt_issuer,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iat": datetime.now(UTC),
        },
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(InvalidTokenError):
        decode_token(token, expected_type="access")


def test_decode_rejects_wrong_iss() -> None:
    settings = get_settings()
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "role": EmployeeRole.ADMIN.value,
            "company_id": None,
            "type": "access",
            "iss": "evil-issuer",
            "aud": settings.jwt_audience,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iat": datetime.now(UTC),
        },
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(InvalidTokenError):
        decode_token(token, expected_type="access")


def test_decode_rejects_wrong_aud() -> None:
    settings = get_settings()
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "role": EmployeeRole.ADMIN.value,
            "company_id": None,
            "type": "access",
            "iss": settings.jwt_issuer,
            "aud": "evil-audience",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iat": datetime.now(UTC),
        },
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(InvalidTokenError):
        decode_token(token, expected_type="access")


def test_decode_rejects_wrong_token_type() -> None:
    settings = get_settings()
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "role": EmployeeRole.ADMIN.value,
            "company_id": None,
            "type": "refresh",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iat": datetime.now(UTC),
        },
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(InvalidTokenError, match="type"):
        decode_token(token, expected_type="access")


def test_decode_rejects_algorithm_confusion_none() -> None:
    settings = get_settings()
    # Manually craft alg=none — must not validate against the HS256 allow-list.
    import base64
    import json

    def _b64(obj: dict) -> str:
        raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    header = {"alg": "none", "typ": "JWT"}
    payload = {
        "sub": str(uuid4()),
        "role": "admin",
        "type": "access",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
        "iat": int(datetime.now(UTC).timestamp()),
    }
    token = f"{_b64(header)}.{_b64(payload)}."
    with pytest.raises(InvalidTokenError):
        decode_token(token, expected_type="access")


def test_create_access_token_embeds_configured_iss_aud() -> None:
    settings = get_settings()
    token = create_access_token(subject=uuid4(), role="hr", company_id=None)
    unverified = jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.jwt_algorithm],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )
    assert unverified["iss"] == settings.jwt_issuer
    assert unverified["aud"] == settings.jwt_audience
