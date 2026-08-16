from __future__ import annotations

from contextvars import ContextVar
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

_DONE_STATUSES = frozenset({"completed", "skipped"})
_access_token_var: ContextVar[str | None] = ContextVar(
    "onboard_api_access_token",
    default=None,
)
_telegram_user_id_var: ContextVar[int | None] = ContextVar(
    "onboard_api_telegram_user_id",
    default=None,
)


@dataclass(slots=True)
class _TokenPair:
    access_token: str
    refresh_token: str


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
        company_id: UUID,
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

    async def find_employee_by_telegram(self, telegram_user_id: int) -> EmployeeDTO | None:
        """Resolve employee: cached session (+ refresh) first, else bot exchange."""
        if self.bind_telegram_token(telegram_user_id):
            try:
                return await self.get_me()
            except OnboardApiError as exc:
                # Access expired and refresh failed, or unexpected error —
                # fall through to a fresh identity exchange.
                if exc.status_code == 403:
                    raise

        try:
            return await self.authenticate_telegram(telegram_user_id)
        except OnboardApiError as exc:
            if exc.status_code == 404:
                return None
            raise

    async def get_me(self) -> EmployeeDTO:
        payload = await self._get("/api/v1/auth/me")
        return EmployeeDTO.model_validate(payload)

    async def authenticate_telegram(self, telegram_user_id: int) -> EmployeeDTO:
        """Exchange service token + Telegram id for an employee JWT pair."""
        client = self._ensure_client()
        response = await client.post(
            "/api/v1/auth/bot/telegram",
            headers={"X-Bot-Service-Token": self._service_token},
            json={
                "company_id": str(self._company_id),
                "telegram_user_id": telegram_user_id,
            },
        )
        payload = self._parse(response)
        assert isinstance(payload, dict)

        self._store_tokens(
            telegram_user_id,
            access_token=str(payload["access_token"]),
            refresh_token=str(payload["refresh_token"]),
        )
        return EmployeeDTO.model_validate(payload["employee"])

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
            "company_id": str(self._company_id),
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
        payload = await self._post("/api/v1/ai/chat", json=body)
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

    async def _post(self, path: str, *, json: dict | None = None) -> object:
        return await self._request("POST", path, json=json)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
    ) -> object:
        client = self._ensure_client()
        response = await client.request(
            method,
            path,
            params=params,
            json=json,
            headers=self._auth_headers(),
        )
        if response.status_code == 401:
            telegram_user_id = _telegram_user_id_var.get()
            if telegram_user_id is not None and await self.refresh_session(telegram_user_id):
                response = await client.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    headers=self._auth_headers(),
                )
        return self._parse(response)

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
