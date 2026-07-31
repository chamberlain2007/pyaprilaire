"""Async client for the Aprilaire cloud API (v2 - aprilaire.io)."""

from __future__ import annotations

import asyncio
from logging import Logger
from typing import Any

import aiohttp
from botocore.exceptions import BotoCoreError, ClientError
from pycognito import Cognito

from .cloud_models import DehumidifierStatus, DeviceSettings, DeviceStatus, Hierarchy
from .const import (
    CLOUD_COGNITO_CLIENT_ID,
    CLOUD_COGNITO_USER_POOL_ID,
    CLOUD_DEVICE_API_BASE,
    DEHUMIDIFICATION_SETPOINT_MAX,
    DEHUMIDIFICATION_SETPOINT_MIN,
)

REQUEST_TIMEOUT = 10
MAX_RETRIES = 3

# Cognito error codes that indicate a credential problem rather than a
# transient/network failure.
AUTH_ERROR_CODES = frozenset(
    {
        "NotAuthorizedException",
        "UserNotFoundException",
        "UserNotConfirmedException",
        "PasswordResetRequiredException",
    }
)


class CloudClientAuthError(Exception):
    """Raised when authentication fails."""


class CloudClientRequestError(Exception):
    """Raised when an API request fails."""


def _classify_cognito_error(err: Exception) -> Exception:
    """Map a Cognito/boto error to a typed cloud client error."""
    if isinstance(err, ClientError):
        code = err.response.get("Error", {}).get("Code", "")
        if code in AUTH_ERROR_CODES:
            return CloudClientAuthError(f"Authentication failed: {code}")
        return CloudClientRequestError(f"Cognito request failed: {code}")
    if isinstance(err, BotoCoreError):
        return CloudClientRequestError(f"Cognito connection failed: {err}")
    return CloudClientAuthError(f"Authentication failed: {err}")


class AprilaireCloudClient:
    """Async client for the Aprilaire cloud API (v2)."""

    def __init__(
        self,
        username: str,
        password: str,
        logger: Logger,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.username = username
        self.password = password
        self.logger = logger

        self._cognito: Cognito | None = None
        self._session = session
        self._owns_session = session is None
        self._auth_lock = asyncio.Lock()

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or (self._owns_session and self._session.closed):
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._cognito and self._cognito.id_token:
            headers["Authorization"] = f"Bearer {self._cognito.id_token}"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> Any:
        """Make an API request with retry and auto-refresh logic."""
        url = f"{CLOUD_DEVICE_API_BASE}{path}"

        for attempt in range(MAX_RETRIES):
            try:
                session = self._get_session()
                async with session.request(
                    method,
                    url,
                    json=json,
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                ) as resp:
                    if resp.status == 401:
                        if retry_auth and self._cognito:
                            self.logger.info("Token expired, refreshing")
                            await self.refresh_token()
                            return await self._request(
                                method, path, json=json, retry_auth=False
                            )
                        raise CloudClientAuthError(
                            "Request unauthorized after token refresh"
                        )

                    if resp.status >= 400:
                        text = await resp.text()
                        raise CloudClientRequestError(
                            f"Request failed with status {resp.status}: {text}"
                        )

                    return await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                self.logger.warning(
                    "Request attempt %d/%d failed: %s",
                    attempt + 1,
                    MAX_RETRIES,
                    err,
                )
                if attempt == MAX_RETRIES - 1:
                    raise CloudClientRequestError(
                        f"Request failed after {MAX_RETRIES} attempts"
                    ) from err

    def _authenticate_sync(self) -> Cognito:
        """Perform blocking Cognito SRP authentication."""
        cognito = Cognito(
            CLOUD_COGNITO_USER_POOL_ID,
            CLOUD_COGNITO_CLIENT_ID,
            username=self.username,
        )
        cognito.authenticate(password=self.password)
        return cognito

    async def authenticate(self) -> None:
        """Authenticate with Cognito SRP.

        Raises CloudClientAuthError for credential problems and
        CloudClientRequestError for network/service failures.
        """
        loop = asyncio.get_running_loop()
        async with self._auth_lock:
            try:
                self._cognito = await loop.run_in_executor(
                    None, self._authenticate_sync
                )
            except Exception as err:
                self.logger.error("Cognito authentication failed: %s", err)
                self._cognito = None
                raise _classify_cognito_error(err) from err

        self.logger.info("Authenticated via Cognito")

    async def refresh_token(self) -> None:
        """Refresh the Cognito tokens.

        Raises CloudClientAuthError if there is no session or the refresh
        token is no longer valid, and CloudClientRequestError for
        network/service failures.
        """
        if not self._cognito:
            raise CloudClientAuthError("Not authenticated")

        loop = asyncio.get_running_loop()
        async with self._auth_lock:
            try:
                await loop.run_in_executor(None, self._cognito.renew_access_token)
            except Exception as err:
                self.logger.error("Cognito token refresh failed: %s", err)
                raise _classify_cognito_error(err) from err

        self.logger.info("Cognito token refreshed")

    @property
    def id_token(self) -> str | None:
        """Return the current Cognito ID token."""
        return self._cognito.id_token if self._cognito else None

    async def get_hierarchy(self) -> Hierarchy:
        """Get the device hierarchy (locations, rooms, devices)."""
        if not self._cognito:
            raise CloudClientAuthError("Not authenticated")

        data = await self._request("GET", "/hierarchy")
        return Hierarchy.from_dict(data or {})

    async def get_device_status(self, device_id: str) -> DeviceStatus:
        """Get device status (model, firmware, etc.)."""
        if not self._cognito:
            raise CloudClientAuthError("Not authenticated")

        data = await self._request("GET", f"/{device_id}/status")
        return DeviceStatus.from_dict(data or {})

    async def get_dehumidifier_status(self, device_id: str) -> DehumidifierStatus:
        """Get dehumidifier status (sensors, alerts, equipment state)."""
        if not self._cognito:
            raise CloudClientAuthError("Not authenticated")

        data = await self._request("GET", f"/{device_id}/status/dehumidifier")
        return DehumidifierStatus.from_dict(data or {})

    async def get_device_settings(self, device_id: str) -> DeviceSettings:
        """Get device settings (mode, setpoints, sensor config)."""
        if not self._cognito:
            raise CloudClientAuthError("Not authenticated")

        data = await self._request("GET", f"/{device_id}/settings")
        return DeviceSettings.from_dict(data or {})

    async def set_dehumidification_setpoint(
        self, device_id: str, setpoint: int
    ) -> bool:
        """Set the dehumidification humidity setpoint."""
        if not self._cognito:
            raise CloudClientAuthError("Not authenticated")

        if (
            not DEHUMIDIFICATION_SETPOINT_MIN
            <= setpoint
            <= DEHUMIDIFICATION_SETPOINT_MAX
        ):
            raise ValueError(
                f"Setpoint must be between {DEHUMIDIFICATION_SETPOINT_MIN} "
                f"and {DEHUMIDIFICATION_SETPOINT_MAX}, got {setpoint}"
            )

        payload = {"dehumidifier": {"humiditySetpoint": setpoint}}
        await self._request("PATCH", f"/{device_id}/settings", json=payload)
        return True

    async def set_dehumidifier_mode(self, device_id: str, mode: str) -> bool:
        """Set the dehumidifier mode (e.g. 'on', 'off', 'auto')."""
        if not self._cognito:
            raise CloudClientAuthError("Not authenticated")

        payload = {"dehumidifier": {"mode": mode}}
        await self._request("PATCH", f"/{device_id}/settings", json=payload)
        return True

    async def close(self) -> None:
        """Close the HTTP session if this client owns it."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()
        if self._owns_session:
            self._session = None
