"""Async client for the Aprilaire cloud API (v2 - aprilaire.io)."""

from __future__ import annotations

from logging import Logger
from typing import Any

import aiohttp
from pycognito import Cognito

from .cloud_models import (
    DehumidifierStatus,
    DeviceSettings,
    DeviceStatus,
    Hierarchy,
)
from .const import (
    CLOUD_COGNITO_CLIENT_ID,
    CLOUD_COGNITO_USER_POOL_ID,
    CLOUD_DEVICE_API_BASE,
    DEHUMIDIFICATION_SETPOINT_MAX,
    DEHUMIDIFICATION_SETPOINT_MIN,
)

REQUEST_TIMEOUT = 10
MAX_RETRIES = 3


class CloudClientAuthError(Exception):
    """Raised when authentication fails."""


class CloudClientRequestError(Exception):
    """Raised when an API request fails."""


class AprilaireCloudClient:
    """Async client for the Aprilaire cloud API (v2)."""

    def __init__(self, username: str, password: str, logger: Logger) -> None:
        self.username = username
        self.password = password
        self.logger = logger

        self._cognito: Cognito | None = None
        self._session: aiohttp.ClientSession | None = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            self._session = aiohttp.ClientSession(timeout=timeout)
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
                    method, url, json=json, headers=self._headers()
                ) as resp:
                    if resp.status == 401 and retry_auth and self._cognito:
                        self.logger.info("Token expired, refreshing")
                        refreshed = await self.refresh_token()
                        if refreshed:
                            return await self._request(
                                method, path, json=json, retry_auth=False
                            )
                        raise CloudClientAuthError("Token refresh failed")

                    if resp.status >= 400:
                        text = await resp.text()
                        raise CloudClientRequestError(
                            f"Request failed with status {resp.status}: {text}"
                        )

                    return await resp.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError) as err:
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

    async def authenticate(self) -> bool:
        """Authenticate with Cognito SRP."""
        try:
            self._cognito = Cognito(
                CLOUD_COGNITO_USER_POOL_ID,
                CLOUD_COGNITO_CLIENT_ID,
                username=self.username,
            )
            self._cognito.authenticate(password=self.password)
        except Exception as err:
            self.logger.error("Cognito authentication failed: %s", err)
            self._cognito = None
            return False

        self.logger.info("Authenticated via Cognito")
        return True

    async def refresh_token(self) -> bool:
        """Refresh the Cognito tokens."""
        if not self._cognito:
            return False

        try:
            self._cognito.renew_access_token()
        except Exception as err:
            self.logger.error("Cognito token refresh failed: %s", err)
            return False

        self.logger.info("Cognito token refreshed")
        return True

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

    async def get_dehumidifier_status(
        self, device_id: str
    ) -> DehumidifierStatus:
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

        if not DEHUMIDIFICATION_SETPOINT_MIN <= setpoint <= DEHUMIDIFICATION_SETPOINT_MAX:
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
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
