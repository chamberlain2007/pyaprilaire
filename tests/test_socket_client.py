from pyaprilaire.const import Action, FunctionalDomain
from pyaprilaire.client import SocketClient

import asyncio
from asyncio import Protocol, Transport

import unittest
from unittest.mock import patch, AsyncMock
import logging
import sys


class MockTransport(Transport):
    def __init__(self):
        super().__init__()

    def close(self):
        pass


class MockProtocol(Protocol):
    def __init__(self):
        self.transport: Transport = MockTransport()


class Test_Socket_Client(unittest.IsolatedAsyncioTestCase):
    def patch_socket(func):
        async def create_connection(
            self,
            protocol_factory,
            host=None,
            port=None,
            *,
            ssl=None,
            family=0,
            proto=0,
            flags=0,
            sock=None,
            local_addr=None,
            server_hostname=None,
            ssl_handshake_timeout=None,
            ssl_shutdown_timeout=None,
            happy_eyeballs_delay=None,
            interleave=None,
            all_errors=False,
        ):
            return None

        def state_changed(self):
            pass

        def create_protocol(self):
            return MockProtocol()

        async def wrapper(*args, **kwargs):
            with (
                patch("asyncio.BaseEventLoop.create_connection", new=create_connection),
                patch(
                    "pyaprilaire.socket_client.SocketClient.state_changed",
                    new=state_changed,
                ),
                patch(
                    "pyaprilaire.socket_client.SocketClient.create_protocol",
                    new=create_protocol,
                ),
            ):
                await func(*args, **kwargs)

        return wrapper

    def setUp(self):
        self.logger = logging.getLogger()
        self.logger.propagate = False

    @patch_socket
    async def test_client_status(self):
        client = SocketClient("", 0, lambda x: (), None)

        await client.start_listen()

        self.assertFalse(client.stopped)
        self.assertTrue(client.connected)
        self.assertFalse(client.reconnecting)

        client._disconnect()

        self.assertFalse(client.stopped)
        self.assertFalse(client.connected)
        self.assertFalse(client.reconnecting)

        client.stop_listen()

        self.assertTrue(client.stopped)
        self.assertFalse(client.connected)
        self.assertFalse(client.reconnecting)

    async def reconnect_nowait(self, connect_wait_period: int = 0):
        self.connected = True
        self.reconnecting = False

    @patch_socket
    @patch("pyaprilaire.socket_client.SocketClient._reconnect", new=reconnect_nowait)
    async def test_reconnect_loop(self):
        client = SocketClient("", 0, lambda x: (), None, reconnect_interval=1)

        await client.start_listen()
        await client._reconnect_loop()

        self.assertFalse(client.stopped)
        self.assertTrue(client.connected)
        self.assertFalse(client.reconnecting)

    @patch_socket
    async def test_reconnect_loop_stopped(self):
        client = SocketClient("", 0, lambda x: (), None, reconnect_interval=1)

        await client._reconnect_loop()

        self.assertTrue(client.stopped)
        self.assertFalse(client.connected)
        self.assertFalse(client.reconnecting)

    @patch_socket
    async def test_cancel_reconnect_loop(self):
        client = SocketClient("", 0, lambda x: (), None, reconnect_interval=1000000)

        async def cancel_reconnect_loop():
            while not client.reconnect_break_future:
                await asyncio.sleep(0.5)
            client._cancel_reconnect_loop()

        client.connected = True
        client.stopped = False
        await asyncio.gather(cancel_reconnect_loop(), client._reconnect_loop())

    @patch_socket
    async def test_reconnect(self):
        client = SocketClient("", 0, lambda x: (), None, reconnect_interval=1000000)

        sleep_mock = AsyncMock()

        with patch("asyncio.sleep", new=sleep_mock):
            await client._reconnect(10)

        self.assertEqual(sleep_mock.await_count, 1)

    # @patch_socket
    async def test_reconnect_exception(self):
        with self.assertLogs(logger=self.logger) as cm:
            client = SocketClient(
                "",
                0,
                lambda x: (),
                self.logger,
                reconnect_interval=1000000,
            )

            client.stopped = False

            sleep_mock = AsyncMock()

            def create_connection(*args, **kwargs):
                client.stopped = True
                raise Exception("Test failure")

            create_connection_mock = AsyncMock(side_effect=create_connection)

            with patch("asyncio.sleep", new=sleep_mock), patch(
                "asyncio.BaseEventLoop.create_connection", new=create_connection_mock
            ):
                await client._reconnect(10)

            self.assertEqual(sleep_mock.await_count, 1)
            self.assertTrue(client.stopped)
            self.assertFalse(client.connected)
            self.assertTrue(client.reconnecting)
