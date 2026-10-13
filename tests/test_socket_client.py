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


@pytest.mark.parametrize("restart", [False, True])
async def test_stop_during_reconnect_delay(client: SocketClient, restart):
    entered = asyncio.Event()
    release = asyncio.Event()
    dial = AsyncMock()

    async def backoff(seconds):
        assert seconds == 10
        entered.set()
        await release.wait()

    client.create_protocol = Mock(return_value=Mock(transport=None))
    client.stopped = False
    with (
        patch("asyncio.sleep", new=backoff),
        patch("asyncio.BaseEventLoop.create_connection", new=dial),
    ):
        reconnect = asyncio.create_task(client._reconnect(10))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            client.stop_listen()
            if restart:
                await client.start_listen()
                assert dial.await_count == 1
                assert client.connected
            release.set()
            await asyncio.wait_for(reconnect, 1)
            assert dial.await_count == int(restart)
            assert client.connected is restart
            assert client.stopped is not restart
            assert not client.reconnecting
        finally:
            release.set()
            await reconnect
            client.stop_listen()


async def test_cancel_during_reconnect_delay(client: SocketClient):
    entered = asyncio.Event()
    release = asyncio.Event()
    dial = AsyncMock()
    retry = Mock()

    async def backoff(seconds):
        entered.set()
        await release.wait()

    client.stopped = False
    with (
        patch("asyncio.sleep", new=backoff),
        patch("asyncio.BaseEventLoop.create_connection", new=dial),
        patch("asyncio.ensure_future", new=retry),
    ):
        reconnect = asyncio.create_task(client._reconnect(10))
        await asyncio.wait_for(entered.wait(), 1)
        reconnect.cancel()
        with pytest.raises(asyncio.CancelledError):
            await reconnect
        client.stop_listen()
        assert dial.await_count == 0
        retry.assert_not_called()
        assert not client.connected


@pytest.mark.parametrize("action", ["stop", "restart", "continue"])
async def test_delayed_reconnect_loopback(action):
    tasks_before = asyncio.all_tasks()
    accepted = asyncio.Queue()
    closed = asyncio.Queue()
    transports = []

    class Peer(Protocol):
        def connection_made(self, transport):
            transports.append(transport)
            accepted.put_nowait(transport)

        def connection_lost(self, exc):
            closed.put_nowait(True)

    class ClientProtocol(Protocol):
        def connection_made(self, transport):
            self.transport = transport

    client = SocketClient("127.0.0.1", 0, None)
    client.create_protocol = ClientProtocol
    entered = asyncio.Event()
    release = asyncio.Event()

    async def backoff(seconds):
        assert seconds == 10
        entered.set()
        await release.wait()

    server = await asyncio.get_running_loop().create_server(Peer, "127.0.0.1", 0)
    client.port = server.sockets[0].getsockname()[1]
    reconnect = None
    try:
        await client.start_listen()
        await asyncio.wait_for(accepted.get(), 1)
        with patch("asyncio.sleep", new=backoff):
            reconnect = asyncio.create_task(client._reconnect(10))
            await asyncio.wait_for(entered.wait(), 1)
            await asyncio.wait_for(closed.get(), 1)
            if action != "continue":
                client.stop_listen()
            if action == "restart":
                await client.start_listen()
                await asyncio.wait_for(accepted.get(), 1)
            release.set()
            await asyncio.wait_for(reconnect, 1)
        if action == "continue":
            await asyncio.wait_for(accepted.get(), 1)
        assert len(transports) == (1 if action == "stop" else 2)
        assert client.connected is (action != "stop")
        assert client.stopped is (action == "stop")
        assert not client.reconnecting
        assert sum(not transport.is_closing() for transport in transports) == (
            0 if action == "stop" else 1
        )
        if action != "stop":
            client.stop_listen()
            await asyncio.wait_for(closed.get(), 1)
    finally:
        release.set()
        if reconnect is not None:
            await reconnect
        client.stop_listen()
        for transport in transports:
            transport.close()
        server.close()
        await server.wait_closed()
        loop_turn = asyncio.get_running_loop().create_future()
        asyncio.get_running_loop().call_soon(loop_turn.set_result, None)
        await loop_turn
    pending = asyncio.all_tasks() - tasks_before
    if pending:
        await asyncio.wait_for(asyncio.gather(*pending), 1)
    assert asyncio.all_tasks() - tasks_before == set()
