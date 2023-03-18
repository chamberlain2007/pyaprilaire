from pyaprilaire.client import SocketClient

import asyncio
from asyncio import Protocol

import logging

import unittest
from unittest.mock import patch, AsyncMock, Mock


class Test_Socket_Client(unittest.IsolatedAsyncioTestCase):
    def patch_socket(func):
        async def wrapper(*args, **kwargs):
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
                await func(*args, **kwargs)

        return wrapper

    def setUp(self):
        self.logger = logging.getLogger()
        self.logger.propagate = False
        self.client = SocketClient(None, None, None, self.logger)

    @patch_socket
    async def test_client_status(self):
        await self.client.start_listen()

        self.assertFalse(self.client.stopped)
        self.assertTrue(self.client.connected)
        self.assertFalse(self.client.reconnecting)

        self.client._disconnect()

        self.assertFalse(self.client.stopped)
        self.assertFalse(self.client.connected)
        self.assertFalse(self.client.reconnecting)

        self.client.stop_listen()

        self.assertTrue(self.client.stopped)
        self.assertFalse(self.client.connected)
        self.assertFalse(self.client.reconnecting)

    @patch_socket
    async def test_reconnect_loop(self):
        self.client.reconnect_interval = 0.01

        async def _reconnect_nowait(self: SocketClient, connect_wait_period: int = 0):
            self.connected = True
            self.reconnecting = False

        with patch(
            "pyaprilaire.socket_client.SocketClient._reconnect", new=_reconnect_nowait
        ):
            await self.client.start_listen()
            await self.client._reconnect_loop()

        self.assertFalse(self.client.stopped)
        self.assertTrue(self.client.connected)
        self.assertFalse(self.client.reconnecting)

    @patch_socket
    async def test_reconnect_loop_cancelled(self):
        self.client.reconnect_interval = 0.01

        async def _reconnect_nowait(self: SocketClient, connect_wait_period: int = 0):
            self.connected = True
            self.reconnecting = False

        wait_for_mock = AsyncMock(side_effect=asyncio.exceptions.CancelledError)

        with patch(
            "pyaprilaire.socket_client.SocketClient._reconnect", new=_reconnect_nowait
        ), patch("asyncio.wait_for", new=wait_for_mock):
            await self.client.start_listen()
            await self.client._reconnect_loop()

        self.assertFalse(self.client.stopped)
        self.assertTrue(self.client.connected)
        self.assertFalse(self.client.reconnecting)

    @patch_socket
    async def test_reconnect_loop_stopped(self):
        self.client.reconnect_interval = 0.01
        self.client.connected = False
        self.client.stopped = True

        await self.client._reconnect_loop()

        self.assertTrue(self.client.stopped)
        self.assertFalse(self.client.connected)
        self.assertFalse(self.client.reconnecting)

    @patch_socket
    async def test_cancel_reconnect_loop(self):
        self.client.reconnect_interval = 1
        self.client.connected = True
        self.client.stopped = False

        async def cancel_reconnect_loop():
            while not self.client.reconnect_break_future:
                await asyncio.sleep(0.01)
            self.client._cancel_reconnect_loop()

        await asyncio.gather(cancel_reconnect_loop(), self.client._reconnect_loop())

    @patch_socket
    async def test_cancel_reconnect_loop_state_error(self):
        loop = asyncio.get_event_loop()
        future = loop.create_future()

        self.client.reconnect_break_future = future

        future.set_result(None)

        self.client._cancel_reconnect_loop()

    @patch_socket
    async def test_reconnect(self):
        self.client.stopped = False

        sleep_mock = AsyncMock()

        with patch("asyncio.sleep", new=sleep_mock):
            await self.client._reconnect(10)

        self.assertEqual(sleep_mock.await_count, 1)
        self.assertFalse(self.client.stopped)
        self.assertTrue(self.client.connected)
        self.assertFalse(self.client.reconnecting)

    async def test_reconnect_exception(self):
        self.client.stopped = False

        sleep_mock = AsyncMock()

        def create_connection(*args, **kwargs):
            self.client.cancelled = True
            raise Exception("Test failure")

        create_connection_mock = AsyncMock(side_effect=create_connection)

        with (
            patch("asyncio.sleep", new=sleep_mock),
            patch(
                "asyncio.BaseEventLoop.create_connection", new=create_connection_mock
            ),
            self.assertLogs(self.logger, level="ERROR") as cm,
        ):
            await self.client._reconnect(10)

        self.assertEqual(
            cm.output, ["ERROR:root:Failed to connect to thermostat: Test failure"]
        )

        self.assertEqual(sleep_mock.await_count, 2)
        self.assertFalse(self.client.stopped)
        self.assertFalse(self.client.connected)
        self.assertTrue(self.client.reconnecting)

    @patch_socket
    async def test_reconnect_reconnecting(self):
        self.client.stopped = False
        self.client.connected = True
        self.client.reconnecting = True

        sleep_mock = AsyncMock()

        with patch("asyncio.sleep", new=sleep_mock):
            await self.client._reconnect(10)

        self.assertEqual(sleep_mock.await_count, 0)
        self.assertFalse(self.client.stopped)
        self.assertTrue(self.client.connected)
        self.assertTrue(self.client.reconnecting)
