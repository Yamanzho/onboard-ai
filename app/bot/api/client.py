from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID

import httpx

from app.bot.api.schemas import (
    AssignmentDTO,
    AssignmentProgressDTO,
    EmployeeDTO,
    ProgramDTO,
    ProgressItemDTO,
)
from app.bot.identity_debug import log_identity

_DONE_STATUSES = frozenset({"completed", "skipped"})
_access_token_var: ContextVar[str | None] = ContextVar(
    "onboard_api_access_token",
    default=None,
)
_telegram_user_id_var: ContextVar[int | None] = ContextVar(
    "onboard_api_telegram_user_id",
    default=None,
)
_telegram_update_id_var: ContextVar[int | None] = ContextVar(
    "onboard_api_telegram_update_id",
    default=None,
)


@dataclass(slots=True)
class _TokenPair:
    access_token: str
    refresh_token: str


@dataclass(frozen=True, slots=True)
class TelegramUpdateClaim:
    state: str
    receipt_id: UUID
    owner_token: UUID | None

    @property
    def acquired(self) -> bool:
        return self.state == "acquired" and self.owner_token is not None


@dataclass(frozen=True, slots=True)
class TelegramOutboundDelivery:
    state: str
    message_id: UUID | None
    owner_token: UUID | None
    chat_id: int | None
    source_type: str | None
    source_key: str | None
    body: str | None
    parse_mode: str | None
    attempt_count: int
    telegram_message_id: int | None

    @property
    def acquired(self) -> bool:
        return (
            self.state == "acquired"
            and self.message_id is not None
            and self.owner_token is not None
        )


class OnboardApiError(Exception):
    """Raised when the OnboardAI REST API returns an error response."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: int | None = None,
        request_id: str | None = None,
        detail: object | None = None,
    ) -> None:
        self.status_code = status_code
        self.retry_after = retry_after
        self.request_id = request_id
        self.detail = detail
        super().__init__(message)


class OnboardApiClient:
    """Async HTTP client for OnboardAI REST API (no direct DB access).

    Authentication flow:
    1. Exchange Telegram identity via ``POST /auth/bot/telegram`` using
       ``BOT_SERVICE_TOKEN`` (header ``X-Bot-Service-Token``).
    2. Use the returned employee JWT as ``Authorization: Bearer``.
    3. On access-token expiry (401), renew via ``POST /auth/refresh`` using
       the cached refresh token — not a fresh bot/telegram exchange.

    Tokens are cached per Telegram user id; the active access token for the
    current update is held in a contextvar for concurrency safety.
    """

    def __init__(
        self,
        base_url: str,
        company_id: UUID | None = None,
        *,
        service_token: str,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._company_id = company_id
        self._service_token = service_token
        self._client: httpx.AsyncClient | None = None
        self._token_cache: dict[int, _TokenPair] = {}

    async def start(self) -> None:
        if not self._service_token:
            raise RuntimeError("BOT_SERVICE_TOKEN is required for the Telegram bot")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(30.0),
            headers={"Accept": "application/json"},
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def find_employee_by_telegram(
        self,
        telegram_user_id: int,
        *,
        handler: str = "find_employee_by_telegram",
        chat_id: int | None = None,
    ) -> EmployeeDTO | None:
        """Resolve employee: cached session (+ refresh) first, else bot exchange."""
        if self.bind_telegram_token(telegram_user_id):
            try:
                employee = await self.get_me()
            except OnboardApiError as exc:
                # Access expired and refresh failed, or unexpected error —
                # fall through to a fresh identity exchange.
                if exc.status_code == 403:
                    log_identity(
                        handler=handler,
                        telegram_user_id=telegram_user_id,
                        chat_id=chat_id,
                        result="FORBIDDEN",
                        company_id=self._company_id,
                        status_code=403,
                    )
                    raise
            else:
                log_identity(
                    handler=handler,
                    telegram_user_id=telegram_user_id,
                    chat_id=chat_id,
                    result="FOUND",
                    employee_id=employee.id,
                    company_id=employee.company_id,
                )
                return employee

        try:
            employee = await self.authenticate_telegram(telegram_user_id)
        except OnboardApiError as exc:
            if exc.status_code == 404:
                log_identity(
                    handler=handler,
                    telegram_user_id=telegram_user_id,
                    chat_id=chat_id,
                    result="NOT_FOUND",
                    company_id=self._company_id,
                    status_code=404,
                )
                return None
            log_identity(
                handler=handler,
                telegram_user_id=telegram_user_id,
                chat_id=chat_id,
                result="FORBIDDEN" if exc.status_code == 403 else "ERROR",
                company_id=self._company_id,
                status_code=exc.status_code,
            )
            raise
        log_identity(
            handler=handler,
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
            result="FOUND",
            employee_id=employee.id,
            company_id=employee.company_id,
        )
        return employee

    async def get_me(self) -> EmployeeDTO:
        payload = await self._get("/api/v1/auth/me")
        return EmployeeDTO.model_validate(payload)

    async def authenticate_telegram(self, telegram_user_id: int) -> EmployeeDTO:
        """Exchange service token + Telegram id for an employee JWT pair."""
        client = self._ensure_client()
        response = await client.post(
            "/api/v1/auth/bot/telegram",
            headers={"X-Bot-Service-Token": self._service_token},
            json={"telegram_user_id": telegram_user_id},
        )
        payload = self._parse(response)
        assert isinstance(payload, dict)

        self._store_tokens(
            telegram_user_id,
            access_token=str(payload["access_token"]),
            refresh_token=str(payload["refresh_token"]),
        )
        return EmployeeDTO.model_validate(payload["employee"])

    async def claim_telegram_update(
        self,
        *,
        update_id: int,
        update_type: str,
    ) -> TelegramUpdateClaim:
        payload = await self._bot_service_post(
            "/api/v1/auth/bot/updates/claim",
            json={"update_id": update_id, "update_type": update_type},
        )
        return TelegramUpdateClaim(
            state=str(payload["state"]),
            receipt_id=UUID(str(payload["receipt_id"])),
            owner_token=(
                UUID(str(payload["owner_token"]))
                if payload.get("owner_token") is not None
                else None
            ),
        )

    async def complete_telegram_update(
        self,
        *,
        receipt_id: UUID,
        owner_token: UUID,
    ) -> bool:
        payload = await self._bot_service_post(
            "/api/v1/auth/bot/updates/complete",
            json={
                "receipt_id": str(receipt_id),
                "owner_token": str(owner_token),
            },
        )
        return bool(payload.get("updated"))

    async def fail_telegram_update(
        self,
        *,
        receipt_id: UUID,
        owner_token: UUID,
    ) -> bool:
        payload = await self._bot_service_post(
            "/api/v1/auth/bot/updates/fail",
            json={
                "receipt_id": str(receipt_id),
                "owner_token": str(owner_token),
            },
        )
        return bool(payload.get("updated"))

    async def claim_telegram_outbound(
        self,
        *,
        source_type: str,
        source_key: str,
    ) -> TelegramOutboundDelivery:
        payload = await self._bot_service_post(
            "/api/v1/auth/bot/outbound/claim",
            json={"source_type": source_type, "source_key": source_key},
        )
        return _telegram_outbound_from_payload(payload)

    async def claim_due_telegram_outbound(
        self,
        *,
        limit: int = 20,
    ) -> list[TelegramOutboundDelivery]:
        payload = await self._bot_service_post(
            "/api/v1/auth/bot/outbound/claim-due",
            json={"limit": limit},
        )
        raw = payload.get("deliveries")
        if not isinstance(raw, list):
            raise OnboardApiError("API returned invalid Telegram outbound batch")
        return [
            _telegram_outbound_from_payload(item)
            for item in raw
            if isinstance(item, dict)
        ]

    async def mark_telegram_outbound_sent(
        self,
        *,
        message_id: UUID,
        owner_token: UUID,
        telegram_message_id: int,
    ) -> bool:
        payload = await self._bot_service_post(
            "/api/v1/auth/bot/outbound/sent",
            json={
                "message_id": str(message_id),
                "owner_token": str(owner_token),
                "telegram_message_id": telegram_message_id,
            },
        )
        return bool(payload.get("updated"))

    async def mark_telegram_outbound_failed(
        self,
        *,
        message_id: UUID,
        owner_token: UUID,
        retryable: bool,
        error_category: str,
        retry_after_seconds: int | None = None,
    ) -> bool:
        body: dict[str, object] = {
            "message_id": str(message_id),
            "owner_token": str(owner_token),
            "retryable": retryable,
            "error_category": error_category,
        }
        if retry_after_seconds is not None:
            body["retry_after_seconds"] = retry_after_seconds
        payload = await self._bot_service_post(
            "/api/v1/auth/bot/outbound/failed",
            json=body,
        )
        return bool(payload.get("updated"))

    async def accept_invite_via_telegram(
        self,
        *,
        token: str,
        telegram_user_id: int,
        telegram_username: str | None = None,
        telegram_chat_id: int | None = None,
    ) -> EmployeeDTO:
        """Bind Telegram to an invited EMPLOYEE using deep-link invite token."""
        client = self._ensure_client()
        body: dict[str, object] = {
            "token": token,
            "telegram_user_id": telegram_user_id,
        }
        if telegram_username is not None:
            body["telegram_username"] = telegram_username
        if telegram_chat_id is not None:
            body["telegram_chat_id"] = telegram_chat_id
        response = await client.post(
            "/api/v1/auth/bot/invite/accept",
            headers={"X-Bot-Service-Token": self._service_token},
            json=body,
        )
        payload = self._parse(response)
        assert isinstance(payload, dict)
        self._store_tokens(
            telegram_user_id,
            access_token=str(payload["access_token"]),
            refresh_token=str(payload["refresh_token"]),
        )
        return EmployeeDTO.model_validate(payload["employee"])

    async def ensure_session(self, telegram_user_id: int) -> bool:
        """Bind cached tokens, or re-exchange if the process has no session yet."""
        if self.bind_telegram_token(telegram_user_id):
            return True
        try:
            await self.authenticate_telegram(telegram_user_id)
            return True
        except OnboardApiError:
            return False

    async def refresh_session(self, telegram_user_id: int) -> bool:
        """Renew access token via ``/auth/refresh``. Returns False on failure."""
        pair = self._token_cache.get(telegram_user_id)
        if pair is None:
            return False

        client = self._ensure_client()
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": pair.refresh_token},
        )
        if response.is_error:
            self._token_cache.pop(telegram_user_id, None)
            return False

        payload = response.json()
        self._store_tokens(
            telegram_user_id,
            access_token=str(payload["access_token"]),
            refresh_token=str(payload["refresh_token"]),
        )
        return True

    async def list_assignments(
        self,
        employee_id: UUID,
        *,
        status: str | None = None,
    ) -> list[AssignmentDTO]:
        params: dict[str, str | int] = {"limit": 100}
        if status is not None:
            params["status"] = status
        payload = await self._get(
            f"/api/v1/employees/{employee_id}/assignments",
            params=params,
        )
        assert isinstance(payload, list)
        return [AssignmentDTO.model_validate(item) for item in payload]

    async def get_active_assignment(self, employee_id: UUID) -> AssignmentDTO | None:
        in_progress = await self.list_assignments(employee_id, status="in_progress")
        if in_progress:
            return sorted(in_progress, key=lambda a: a.assigned_at, reverse=True)[0]

        pending = await self.list_assignments(employee_id, status="pending")
        if pending:
            return sorted(pending, key=lambda a: a.assigned_at, reverse=True)[0]
        return None

    async def get_program(self, program_id: UUID) -> ProgramDTO:
        payload = await self._get(f"/api/v1/programs/{program_id}")
        return ProgramDTO.model_validate(payload)

    async def get_progress(self, assignment_id: UUID) -> AssignmentProgressDTO:
        payload = await self._get(f"/api/v1/assignments/{assignment_id}/progress")
        return AssignmentProgressDTO.model_validate(payload)

    async def post_ai_chat(
        self,
        message: str,
        conversation_id: UUID | str | None = None,
    ) -> dict:
        """POST /api/v1/ai/chat using the bound employee JWT.

        Tenant identity comes from that JWT. The JSON body is the user
        question and, when continuing a thread, the server-issued
        conversation_id. Telegram never generates the id.
        """
        body: dict[str, str] = {"message": message}
        if conversation_id is not None:
            body["conversation_id"] = str(conversation_id)
        update_id = _telegram_update_id_var.get()
        headers = (
            {
                "Idempotency-Key": f"telegram-update:{update_id}:ai-chat",
                "X-Telegram-Delivery": "durable",
                "X-Bot-Service-Token": self._service_token,
            }
            if update_id is not None
            else None
        )
        payload = await self._post(
            "/api/v1/ai/chat",
            json=body,
            headers=headers,
        )
        assert isinstance(payload, dict)
        return payload

    async def complete_progress(
        self,
        progress_id: UUID,
        payload: dict | None = None,
    ) -> ProgressItemDTO:
        body = {"source": "telegram_bot"}
        if payload:
            body.update(payload)
        response = await self._post(
            f"/api/v1/progress/{progress_id}/complete",
            json={"payload": body},
            headers={
                "X-Telegram-Delivery": "durable",
                "X-Bot-Service-Token": self._service_token,
            },
        )
        return ProgressItemDTO.model_validate(response)

    @staticmethod
    def first_incomplete_step(
        progress: AssignmentProgressDTO,
    ) -> tuple[int, ProgressItemDTO] | None:
        for index, item in enumerate(progress.items, start=1):
            if item.status not in _DONE_STATUSES:
                return index, item
        return None

    def bind_telegram_token(self, telegram_user_id: int) -> bool:
        """Restore a cached token pair into the current request context."""
        pair = self._token_cache.get(telegram_user_id)
        if pair is None:
            return False
        _access_token_var.set(pair.access_token)
        _telegram_user_id_var.set(telegram_user_id)
        return True

    def invalidate_session(self, telegram_user_id: int) -> None:
        """Drop targeted JWT cache for one Telegram user (no Redis FLUSHDB)."""
        self._token_cache.pop(telegram_user_id, None)
        if _telegram_user_id_var.get() == telegram_user_id:
            _access_token_var.set(None)
            _telegram_user_id_var.set(None)

    def bind_telegram_update(self, update_id: int) -> Token[int | None]:
        """Bind a claimed Telegram update to this concurrent handler task."""
        return _telegram_update_id_var.set(update_id)

    def reset_telegram_update(self, token: Token[int | None]) -> None:
        _telegram_update_id_var.reset(token)

    def current_ai_outbound_source_key(self) -> str | None:
        update_id = _telegram_update_id_var.get()
        if update_id is None:
            return None
        return f"telegram-update:{update_id}:ai-chat"

    def current_telegram_update_id(self) -> int | None:
        return _telegram_update_id_var.get()

    def _store_tokens(
        self,
        telegram_user_id: int,
        *,
        access_token: str,
        refresh_token: str,
    ) -> None:
        self._token_cache[telegram_user_id] = _TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
        )
        _access_token_var.set(access_token)
        _telegram_user_id_var.set(telegram_user_id)

    async def _get(self, path: str, *, params: dict | None = None) -> object:
        return await self._request("GET", path, params=params)

    async def _post(
        self,
        path: str,
        *,
        json: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> object:
        return await self._request("POST", path, json=json, headers=headers)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> object:
        client = self._ensure_client()
        request_headers = {**self._auth_headers(), **(headers or {})}
        response = await client.request(
            method,
            path,
            params=params,
            json=json,
            headers=request_headers,
        )
        if response.status_code == 401:
            telegram_user_id = _telegram_user_id_var.get()
            if telegram_user_id is not None and await self.refresh_session(telegram_user_id):
                response = await client.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    headers={**self._auth_headers(), **(headers or {})},
                )
        return self._parse(response)

    async def _bot_service_post(
        self,
        path: str,
        *,
        json: dict[str, object],
    ) -> dict[str, object]:
        client = self._ensure_client()
        response = await client.post(
            path,
            headers={"X-Bot-Service-Token": self._service_token},
            json=json,
        )
        payload = self._parse(response)
        assert isinstance(payload, dict)
        return payload

    def _auth_headers(self) -> dict[str, str]:
        token = _access_token_var.get()
        if not token:
            raise OnboardApiError(
                "API client is not authenticated for this Telegram user",
                status_code=401,
            )
        return {"Authorization": f"Bearer {token}"}

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("OnboardApiClient is not started")
        return self._client

    @staticmethod
    def _parse(response: httpx.Response) -> object:
        if response.is_error:
            detail: object
            try:
                body = response.json()
                detail = body.get("detail", body)
            except Exception:
                detail = response.text
            raise OnboardApiError(
                f"API {response.request.method} {response.request.url.path} "
                f"failed ({response.status_code}): {detail}",
                status_code=response.status_code,
                retry_after=_retry_after_seconds(response),
                request_id=_response_request_id(response),
                detail=detail,
            )
        if response.status_code == 204:
            return None
        return response.json()


def _telegram_outbound_from_payload(
    payload: dict[str, object],
) -> TelegramOutboundDelivery:
    return TelegramOutboundDelivery(
        state=str(payload.get("state") or ""),
        message_id=(
            UUID(str(payload["message_id"]))
            if payload.get("message_id") is not None
            else None
        ),
        owner_token=(
            UUID(str(payload["owner_token"]))
            if payload.get("owner_token") is not None
            else None
        ),
        chat_id=(
            int(payload["chat_id"])
            if payload.get("chat_id") is not None
            else None
        ),
        source_type=(
            str(payload["source_type"])
            if payload.get("source_type") is not None
            else None
        ),
        source_key=(
            str(payload["source_key"])
            if payload.get("source_key") is not None
            else None
        ),
        body=(
            str(payload["body"])
            if payload.get("body") is not None
            else None
        ),
        parse_mode=(
            str(payload["parse_mode"])
            if payload.get("parse_mode") is not None
            else None
        ),
        attempt_count=int(payload.get("attempt_count") or 0),
        telegram_message_id=(
            int(payload["telegram_message_id"])
            if payload.get("telegram_message_id") is not None
            else None
        ),
    )


def _retry_after_seconds(response: httpx.Response) -> int | None:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    stripped = raw.strip()
    if stripped.isdigit():
        return int(stripped)
    return None


def _response_request_id(response: httpx.Response) -> str | None:
    from app.core.request_id import read_request_id

    return read_request_id(response.headers.get("X-Request-ID"))
