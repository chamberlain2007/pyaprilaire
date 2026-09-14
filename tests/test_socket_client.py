# pylint: disable=redefined-outer-name,missing-function-docstring,missing-module-docstring,protected-access
import asyncio
import logging
from asyncio import Protocol
from unittest.mock import AsyncMock, Mock, patch

import pytest

from pyaprilaire.client import SocketClient


@pytest.fixture
def client():
    return SocketClient(None, None, None)


def patch_socket(func):
    async def wrapper(client, *args, **kwargs):
        state_changed_mock = Mock()
        create_connection_mock = AsyncMock()
        create_protocol_mock = Mock(spec=Protocol)

        with (
            patch(
                "asyncio.BaseEventLoop.create_connection",
                new=create_connection_mock,
            ),
            patch(
                "pyaprilaire.socket_client.SocketClient.state_changed",
                new=state_changed_mock,
            ),
            patch(
                "pyaprilaire.socket_client.SocketClient.create_protocol",
                new=create_protocol_mock,
            ),
        ):
            await func(client, *args, **kwargs)

    return wrapper


@patch_socket
async def test_client_status(client: SocketClient):
    await client.start_listen()

    assert not client.stopped
    assert client.connected
    assert not client.reconnecting
    assert not client.auto_reconnecting

    client._disconnect()

    assert not client.stopped
    assert not client.connected
    assert not client.reconnecting
    assert not client.auto_reconnecting

    client.stop_listen()

    assert client.stopped
    assert not client.connected
    assert not client.reconnecting
    assert not client.auto_reconnecting


@patch_socket
async def test_auto_reconnect_loop(client: SocketClient):
    client.reconnect_interval = 0.01

    first_call = True

    async def _reconnect_nowait(*args, **kwargs):  # pylint: disable=unused-arguments
        if not first_call:
            assert client.auto_reconnecting

        client.connected = True
        client.reconnecting = False
        client.auto_reconnecting = False

    with patch(
        "pyaprilaire.socket_client.SocketClient._reconnect", new=_reconnect_nowait
    ):
        await client.start_listen()
        await client._auto_reconnect_loop()

    assert not client.stopped
    assert client.connected
    assert not client.reconnecting
    assert not client.auto_reconnecting


@patch_socket
async def test_auto_reconnect_loop_cancelled(client: SocketClient):
    client.reconnect_interval = 0.01

    async def _reconnect_nowait(self: SocketClient):
        self.connected = True
        self.reconnecting = False

    wait_for_mock = AsyncMock(side_effect=asyncio.CancelledError)

    with (
        patch(
            "pyaprilaire.socket_client.SocketClient._reconnect", new=_reconnect_nowait
        ),
        patch("asyncio.wait_for", new=wait_for_mock),
    ):
        await client.start_listen()
        await client._auto_reconnect_loop()

    assert not client.stopped
    assert client.connected
    assert not client.reconnecting


@patch_socket
async def test_auto_reconnect_loop_stopped(client: SocketClient):
    client.reconnect_interval = 0.01
    client.connected = False
    client.stopped = True

    await client._auto_reconnect_loop()

    assert client.stopped
    assert not client.connected
    assert not client.reconnecting


@patch_socket
async def test_cancel_auto_reconnect_loop(client: SocketClient):
    client.reconnect_interval = 1
    client.connected = True
    client.stopped = False

    async def cancel_auto_reconnect_loop():
        while not client.reconnect_break_future:
            await asyncio.sleep(0.01)
        client._cancel_auto_reconnect_loop()

    await asyncio.gather(cancel_auto_reconnect_loop(), client._auto_reconnect_loop())


@patch_socket
async def test_cancel_auto_reconnect_loop_state_error(client: SocketClient):
    loop = asyncio.get_event_loop()
    future = loop.create_future()

    client.reconnect_break_future = future

    future.set_result(None)

    client._cancel_auto_reconnect_loop()


@patch_socket
async def test_reconnect(client: SocketClient):
    client.stopped = False

    sleep_mock = AsyncMock()

    with patch("asyncio.sleep", new=sleep_mock):
        await client._reconnect(10)

    assert sleep_mock.await_count == 1
    assert not client.stopped
    assert client.connected
    assert not client.reconnecting


async def test_reconnect_exception(client: SocketClient):
    client.stopped = False

    sleep_mock = AsyncMock()

    def create_connection(*args, **kwargs):  # pylint: disable=unused-arguments
        client.cancelled = True
        raise Exception("Test failure")  # pylint: disable=broad-exception-raised

    create_connection_mock = AsyncMock(side_effect=create_connection)

    with (
        patch("asyncio.sleep", new=sleep_mock),
        patch("asyncio.BaseEventLoop.create_connection", new=create_connection_mock),
    ):
        await client._reconnect(10)

    assert sleep_mock.await_count == 1
    assert not client.stopped
    assert not client.connected
    assert not client.reconnecting
    assert not client.auto_reconnecting


@patch_socket
async def test_reconnect_reconnecting(client: SocketClient):
    client.stopped = False
    client.connected = True
    client.reconnecting = True

    sleep_mock = AsyncMock()

    with patch("asyncio.sleep", new=sleep_mock):
        await client._reconnect(10)

    assert sleep_mock.await_count == 0
    assert not client.stopped
    assert client.connected
    assert client.reconnecting


@patch_socket
async def test_reconnect_stopped(client: SocketClient):
    client.stopped = True

    sleep_mock = AsyncMock()

    with patch("asyncio.sleep", new=sleep_mock):
        await client._reconnect(10)

    assert sleep_mock.await_count == 0
    assert client.stopped
    assert not client.connected
    assert not client.reconnecting


async def test_reconnect_exception_no_retry_when_stopped(client: SocketClient):
    client.stopped = False

    sleep_mock = AsyncMock()

    def create_connection(*args, **kwargs):  # pylint: disable=unused-arguments
        # Simulate stop_listen() being called while the connection attempt
        # is in flight (e.g. from another task).
        client.stopped = True
        raise Exception("Test failure")  # pylint: disable=broad-exception-raised

    create_connection_mock = AsyncMock(side_effect=create_connection)
    ensure_future_mock = Mock()

    with (
        patch("asyncio.sleep", new=sleep_mock),
        patch("asyncio.BaseEventLoop.create_connection", new=create_connection_mock),
        patch("asyncio.ensure_future", new=ensure_future_mock),
    ):
        await client._reconnect(10)

    assert sleep_mock.await_count == 1
    assert client.stopped
    assert not client.connected
    assert not client.reconnecting
    ensure_future_mock.assert_not_called()


@patch_socket
async def test_reconnect_noop_after_stop_listen(client: SocketClient):
    """A reconnect triggered after stop_listen() (e.g. by the protocol's
    connection_lost handler firing once the transport actually closes) must
    not open a new connection."""

    await client.start_listen()

    assert client.connected
    assert not client.stopped

    client.stop_listen()

    assert client.stopped
    assert not client.connected

    await client._reconnect()

    assert client.stopped
    assert not client.connected
    assert not client.reconnecting


@patch_socket
async def test_reconnect_once(client: SocketClient):
    await client._reconnect_once()

    assert client.connected
    assert not client.reconnecting
    assert not client.auto_reconnecting


def test_connection_established_logged(client: SocketClient, caplog):
    with caplog.at_level(logging.INFO, logger="pyaprilaire.socket_client"):
        client._connection_established()

    assert "Aprilaire connection made" in caplog.text
    assert client.connected


def test_connection_established_silent_for_auto_reconnect(client: SocketClient, caplog):
    client.auto_reconnecting = True

    with caplog.at_level(logging.INFO, logger="pyaprilaire.socket_client"):
        client._connection_established()

    assert "Aprilaire connection made" not in caplog.text
    assert client.connected
    assert not client.auto_reconnecting
