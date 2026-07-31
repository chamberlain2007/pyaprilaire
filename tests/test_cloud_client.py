"""Tests for the cloud API v2 client."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from unittest.mock import MagicMock, patch

import aiohttp
import pytest
from aioresponses import aioresponses
from botocore.exceptions import ClientError, EndpointConnectionError

from pyaprilaire.cloud_client import (
    AprilaireCloudClient,
    CloudClientAuthError,
    CloudClientRequestError,
)
from pyaprilaire.const import (
    CLOUD_DEVICE_API_BASE,
    DEHUMIDIFICATION_SETPOINT_MAX,
    DEHUMIDIFICATION_SETPOINT_MIN,
)

BASE = CLOUD_DEVICE_API_BASE
DEVICE_ID = "BC8D7EECB7D1"


@pytest.fixture
def logger():
    return logging.getLogger("test_cloud")


def _mock_cognito():
    """Return a mock Cognito object with tokens set."""
    mock = MagicMock()
    mock.id_token = "mock-id-token"
    mock.access_token = "mock-access-token"
    mock.refresh_token = "mock-refresh-token"
    return mock


@pytest.fixture
def client(logger):
    c = AprilaireCloudClient("user@example.com", "password123", logger)
    c._cognito = _mock_cognito()
    return c


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "InitiateAuth")


def _hierarchy_response():
    return {
        "locations": [
            {
                "locationId": "loc-1",
                "name": "Home",
                "timeZone": "America/Los_Angeles",
                "rooms": [
                    {
                        "name": "Whole Home",
                        "devices": [
                            {"deviceId": DEVICE_ID, "access": "manage", "zone": 1}
                        ],
                    }
                ],
            }
        ]
    }


def _dehum_status_response():
    return {
        "deviceId": DEVICE_ID,
        "asOf": "2026-05-25T20:27:36.650Z",
        "equipmentStatus": "inactive",
        "alerts": {
            "highTemp": False,
            "lowHum": False,
            "highHum": False,
            "lowTemp": False,
        },
        "fanTimeHours": 0,
        "filterService": {"needsService": False, "remaining": 100},
        "humSensors": [
            {
                "reading": 47,
                "uid": 1,
                "isControlling": True,
                "type": "inlet-air",
                "isWireless": False,
                "status": "reporting",
            }
        ],
        "isCompOn": False,
        "isDehumFanOn": False,
        "isHvacFanOn": False,
        "tempSensors": [],
        "wifiRSSI": -43,
    }


def _device_settings_response():
    return {
        "deviceId": DEVICE_ID,
        "asOf": "2026-05-25T20:20:41.265Z",
        "dehumidifier": {
            "mode": "on",
            "humiditySetpoint": 50,
            "sensors": [{"uid": 1, "dispName": "Inlet Air"}],
        },
    }


# --- Authentication ---


async def test_authenticate_success(logger):
    client = AprilaireCloudClient("user@example.com", "pw", logger)
    mock_cognito = _mock_cognito()

    with patch("pyaprilaire.cloud_client.Cognito", return_value=mock_cognito):
        await client.authenticate()

    assert client.id_token == "mock-id-token"
    await client.close()


async def test_authenticate_runs_off_event_loop(logger):
    """The blocking Cognito calls must run in an executor thread."""
    client = AprilaireCloudClient("user@example.com", "pw", logger)
    calling_threads = []

    def _record_thread(*args, **kwargs):
        calling_threads.append(threading.current_thread())
        return _mock_cognito()

    with patch("pyaprilaire.cloud_client.Cognito", side_effect=_record_thread):
        await client.authenticate()

    assert calling_threads[0] is not threading.main_thread()
    await client.close()


async def test_authenticate_invalid_credentials(logger):
    client = AprilaireCloudClient("user@example.com", "pw", logger)

    with patch(
        "pyaprilaire.cloud_client.Cognito",
        side_effect=_client_error("NotAuthorizedException"),
    ):
        with pytest.raises(CloudClientAuthError, match="NotAuthorizedException"):
            await client.authenticate()

    assert client.id_token is None
    await client.close()


async def test_authenticate_service_error(logger):
    client = AprilaireCloudClient("user@example.com", "pw", logger)

    with patch(
        "pyaprilaire.cloud_client.Cognito",
        side_effect=_client_error("ThrottlingException"),
    ):
        with pytest.raises(CloudClientRequestError, match="ThrottlingException"):
            await client.authenticate()

    await client.close()


async def test_authenticate_connection_error(logger):
    client = AprilaireCloudClient("user@example.com", "pw", logger)

    with patch(
        "pyaprilaire.cloud_client.Cognito",
        side_effect=EndpointConnectionError(endpoint_url="https://cognito"),
    ):
        with pytest.raises(CloudClientRequestError, match="connection failed"):
            await client.authenticate()

    await client.close()


async def test_authenticate_unexpected_error(logger):
    client = AprilaireCloudClient("user@example.com", "pw", logger)

    with patch(
        "pyaprilaire.cloud_client.Cognito",
        side_effect=Exception("Bad credentials"),
    ):
        with pytest.raises(CloudClientAuthError, match="Bad credentials"):
            await client.authenticate()

    assert client.id_token is None
    await client.close()


# --- Token Refresh ---


async def test_refresh_token_success(client):
    await client.refresh_token()
    client._cognito.renew_access_token.assert_called_once()
    await client.close()


async def test_refresh_token_not_authenticated(logger):
    client = AprilaireCloudClient("user@example.com", "pw", logger)
    with pytest.raises(CloudClientAuthError, match="Not authenticated"):
        await client.refresh_token()
    await client.close()


async def test_refresh_token_expired(client):
    client._cognito.renew_access_token.side_effect = _client_error(
        "NotAuthorizedException"
    )
    with pytest.raises(CloudClientAuthError):
        await client.refresh_token()
    await client.close()


async def test_refresh_token_unexpected_error(client):
    client._cognito.renew_access_token.side_effect = Exception("expired")
    with pytest.raises(CloudClientAuthError, match="expired"):
        await client.refresh_token()
    await client.close()


async def test_refresh_token_serialized_by_lock(client):
    """Concurrent refreshes must not run in parallel."""
    concurrent = 0
    max_concurrent = 0

    def _slow_renew():
        nonlocal concurrent, max_concurrent
        concurrent += 1
        max_concurrent = max(max_concurrent, concurrent)
        time.sleep(0.05)
        concurrent -= 1

    client._cognito.renew_access_token.side_effect = _slow_renew

    await asyncio.gather(client.refresh_token(), client.refresh_token())

    assert client._cognito.renew_access_token.call_count == 2
    assert max_concurrent == 1
    await client.close()


async def test_auto_refresh_on_401(client):
    with aioresponses() as m:
        m.get(f"{BASE}/hierarchy", status=401, body="Unauthorized")
        client._cognito.renew_access_token.return_value = None
        m.get(f"{BASE}/hierarchy", payload=_hierarchy_response())

        hierarchy = await client.get_hierarchy()

        assert len(hierarchy.locations) == 1
        await client.close()


async def test_auto_refresh_on_401_fails(client):
    with aioresponses() as m:
        m.get(f"{BASE}/hierarchy", status=401, body="Unauthorized")
        client._cognito.renew_access_token.side_effect = Exception("expired")

        with pytest.raises(CloudClientAuthError, match="expired"):
            await client.get_hierarchy()
        await client.close()


async def test_401_after_refresh_raises_auth_error(client):
    with aioresponses() as m:
        m.get(f"{BASE}/hierarchy", status=401, body="Unauthorized")
        client._cognito.renew_access_token.return_value = None
        m.get(f"{BASE}/hierarchy", status=401, body="Unauthorized")

        with pytest.raises(CloudClientAuthError, match="after token refresh"):
            await client.get_hierarchy()
        await client.close()


# --- Session handling ---


async def test_injected_session_is_used_and_not_closed(logger):
    session = aiohttp.ClientSession()
    client = AprilaireCloudClient("user@example.com", "pw", logger, session=session)
    client._cognito = _mock_cognito()

    with aioresponses() as m:
        m.get(f"{BASE}/hierarchy", payload=_hierarchy_response())
        await client.get_hierarchy()

    await client.close()
    assert not session.closed
    assert client._session is session
    await session.close()


async def test_owned_session_recreated_after_close(client):
    with aioresponses() as m:
        m.get(f"{BASE}/hierarchy", payload=_hierarchy_response())
        await client.get_hierarchy()

    first_session = client._session
    await client.close()
    assert client._session is None

    with aioresponses() as m:
        m.get(f"{BASE}/hierarchy", payload=_hierarchy_response())
        await client.get_hierarchy()

    assert client._session is not first_session
    await client.close()


# --- Get Hierarchy ---


async def test_get_hierarchy(client):
    with aioresponses() as m:
        m.get(f"{BASE}/hierarchy", payload=_hierarchy_response())

        hierarchy = await client.get_hierarchy()

        assert len(hierarchy.locations) == 1
        assert hierarchy.device_ids == [DEVICE_ID]
        await client.close()


async def test_get_hierarchy_not_authenticated(logger):
    client = AprilaireCloudClient("user@example.com", "pw", logger)
    with pytest.raises(CloudClientAuthError):
        await client.get_hierarchy()
    await client.close()


# --- Get Device Status ---


async def test_get_device_status(client):
    payload = {
        "deviceId": DEVICE_ID,
        "asOf": "2026-05-25T17:44:35.171Z",
        "hardwareRev": "D",
        "firmwareRev": "1.1.3",
        "altFirmwareRev": "1.9.0",
        "model": "E080W",
    }
    with aioresponses() as m:
        m.get(f"{BASE}/{DEVICE_ID}/status", payload=payload)

        status = await client.get_device_status(DEVICE_ID)

        assert status.device_id == DEVICE_ID
        assert status.model == "E080W"
        assert status.firmware_rev == "1.1.3"
        await client.close()


async def test_get_device_status_not_authenticated(logger):
    client = AprilaireCloudClient("user@example.com", "pw", logger)
    with pytest.raises(CloudClientAuthError):
        await client.get_device_status(DEVICE_ID)
    await client.close()


# --- Get Dehumidifier Status ---


async def test_get_dehumidifier_status(client):
    with aioresponses() as m:
        m.get(
            f"{BASE}/{DEVICE_ID}/status/dehumidifier",
            payload=_dehum_status_response(),
        )

        status = await client.get_dehumidifier_status(DEVICE_ID)

        assert status.device_id == DEVICE_ID
        assert status.equipment_status == "inactive"
        assert len(status.hum_sensors) == 1
        assert status.hum_sensors[0].reading == 47.0
        assert status.wifi_rssi == -43
        await client.close()


async def test_get_dehumidifier_status_not_authenticated(logger):
    client = AprilaireCloudClient("user@example.com", "pw", logger)
    with pytest.raises(CloudClientAuthError):
        await client.get_dehumidifier_status(DEVICE_ID)
    await client.close()


# --- Get Device Settings ---


async def test_get_device_settings(client):
    with aioresponses() as m:
        m.get(
            f"{BASE}/{DEVICE_ID}/settings",
            payload=_device_settings_response(),
        )

        settings = await client.get_device_settings(DEVICE_ID)

        assert settings.device_id == DEVICE_ID
        assert settings.dehumidifier is not None
        assert settings.dehumidifier.mode == "on"
        assert settings.dehumidifier.humidity_setpoint == 50
        await client.close()


async def test_get_device_settings_not_authenticated(logger):
    client = AprilaireCloudClient("user@example.com", "pw", logger)
    with pytest.raises(CloudClientAuthError):
        await client.get_device_settings(DEVICE_ID)
    await client.close()


# --- Set Dehumidification Setpoint ---


async def test_set_dehumidification_setpoint(client):
    with aioresponses() as m:
        m.patch(f"{BASE}/{DEVICE_ID}/settings", payload={})

        result = await client.set_dehumidification_setpoint(DEVICE_ID, 55)

        assert result is True
        await client.close()


async def test_set_dehumidification_setpoint_too_low(client):
    with pytest.raises(ValueError, match="Setpoint must be between"):
        await client.set_dehumidification_setpoint(
            DEVICE_ID, DEHUMIDIFICATION_SETPOINT_MIN - 1
        )
    await client.close()


async def test_set_dehumidification_setpoint_too_high(client):
    with pytest.raises(ValueError, match="Setpoint must be between"):
        await client.set_dehumidification_setpoint(
            DEVICE_ID, DEHUMIDIFICATION_SETPOINT_MAX + 1
        )
    await client.close()


async def test_set_dehumidification_setpoint_boundaries(client):
    with aioresponses() as m:
        m.patch(f"{BASE}/{DEVICE_ID}/settings", payload={})
        m.patch(f"{BASE}/{DEVICE_ID}/settings", payload={})

        assert (
            await client.set_dehumidification_setpoint(
                DEVICE_ID, DEHUMIDIFICATION_SETPOINT_MIN
            )
            is True
        )
        assert (
            await client.set_dehumidification_setpoint(
                DEVICE_ID, DEHUMIDIFICATION_SETPOINT_MAX
            )
            is True
        )
        await client.close()


async def test_set_dehumidification_setpoint_not_authenticated(logger):
    client = AprilaireCloudClient("user@example.com", "pw", logger)
    with pytest.raises(CloudClientAuthError):
        await client.set_dehumidification_setpoint(DEVICE_ID, 50)
    await client.close()


# --- Set Dehumidifier Mode ---


async def test_set_dehumidifier_mode(client):
    with aioresponses() as m:
        m.patch(f"{BASE}/{DEVICE_ID}/settings", payload={})

        result = await client.set_dehumidifier_mode(DEVICE_ID, "auto")

        assert result is True
        await client.close()


async def test_set_dehumidifier_mode_not_authenticated(logger):
    client = AprilaireCloudClient("user@example.com", "pw", logger)
    with pytest.raises(CloudClientAuthError):
        await client.set_dehumidifier_mode(DEVICE_ID, "on")
    await client.close()


# --- Error responses ---


async def test_request_error_response(client):
    with aioresponses() as m:
        m.get(f"{BASE}/hierarchy", status=500, body="Server error")

        with pytest.raises(CloudClientRequestError, match="status 500"):
            await client.get_hierarchy()
        await client.close()


# --- Retry Logic ---


async def test_request_retries_on_connection_error(client):
    with aioresponses() as m:
        m.get(f"{BASE}/hierarchy", exception=aiohttp.ClientConnectionError())
        m.get(f"{BASE}/hierarchy", exception=aiohttp.ClientConnectionError())
        m.get(f"{BASE}/hierarchy", payload=_hierarchy_response())

        hierarchy = await client.get_hierarchy()

        assert len(hierarchy.locations) == 1
        await client.close()


async def test_request_fails_after_max_retries(client):
    with aioresponses() as m:
        m.get(f"{BASE}/hierarchy", exception=aiohttp.ClientConnectionError())
        m.get(f"{BASE}/hierarchy", exception=aiohttp.ClientConnectionError())
        m.get(f"{BASE}/hierarchy", exception=aiohttp.ClientConnectionError())

        with pytest.raises(CloudClientRequestError, match="after 3 attempts"):
            await client.get_hierarchy()
        await client.close()


async def test_request_retries_on_timeout(client):
    with aioresponses() as m:
        m.get(f"{BASE}/hierarchy", exception=asyncio.TimeoutError())
        m.get(f"{BASE}/hierarchy", payload=_hierarchy_response())

        hierarchy = await client.get_hierarchy()

        assert len(hierarchy.locations) == 1
        await client.close()


# --- Close ---


async def test_close_without_session(logger):
    client = AprilaireCloudClient("user@example.com", "pw", logger)
    await client.close()


async def test_close_with_session(client):
    with aioresponses() as m:
        m.get(f"{BASE}/hierarchy", payload=_hierarchy_response())

        await client.get_hierarchy()
        assert client._session is not None
        await client.close()
        assert client._session is None
