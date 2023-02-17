"""Client for connecting to the Aprilaire thermostat socket"""

from __future__ import annotations

import asyncio

from logging import Logger

from collections.abc import Callable
from typing import Any


class SocketClient:
    """Client for connecting to the Aprilaire thermostat socket"""

    def __init__(
        self,
        host: str,
        port: int,
        data_received_callback: Callable[[dict[str, Any]], None],
        logger: Logger,
        reconnect_interval: int = None,
        retry_connection_interval: int = None,
    ) -> None:
        """Initialize client"""
        self.host = host
        self.port = port
        self.data_received_callback = data_received_callback
        self.logger = logger
        self.data: dict[str, Any] = {}
        self.reconnect_interval = reconnect_interval
        self.retry_connection_interval = retry_connection_interval

        self.connected = False
        self.stopped = True
        self.reconnecting = False
        self.reconnect_break_future: asyncio.Future = None

        self.protocol: asyncio.Protocol = None

    async def _reconnect_loop(self):
        if not self.reconnect_interval:
            return

        while True:
            if self.stopped or not self.connected:
                break

            if not self.reconnect_break_future:
                loop = asyncio.get_event_loop()
                self.reconnect_break_future = loop.create_future()

            try:
                await asyncio.wait_for(
                    self.reconnect_break_future, self.reconnect_interval
                )
                break
            except asyncio.exceptions.CancelledError:
                break
            except asyncio.exceptions.TimeoutError:
                await self._reconnect(10)

    def _cancel_reconnect_loop(self):
        if self.reconnect_break_future:
            try:
                self.reconnect_break_future.set_result(True)
            except asyncio.exceptions.InvalidStateError:
                pass
            self.reconnect_break_future = None

    def _disconnect(self):
        self._cancel_reconnect_loop()

        self.connected = False

        self.state_changed()

        if self.protocol and self.protocol.transport:
            self.protocol.transport.close()

    async def _reconnect(self, connect_wait_period: int = None):
        if self.reconnecting:
            return

        self.reconnecting = True

        self.state_changed()

        self._disconnect()

        if connect_wait_period:
            await asyncio.sleep(connect_wait_period)

        self.protocol = self.create_protocol()

        while True:
            if self.stopped:
                break

            try:
                await asyncio.get_event_loop().create_connection(
                    lambda: self.protocol,
                    self.host,
                    self.port,
                )

                self.connected = True
                self.reconnecting = False

                self.state_changed()

                asyncio.ensure_future(self._reconnect_loop())

                break

            except Exception as exc:  # pylint: disable=broad-except
                self.logger.error("Failed to connect to thermostat: %s", str(exc))

                if not self.stopped:
                    await asyncio.sleep(self.retry_connection_interval)

    def start_listen(self):
        """Start listening to the socket"""

        self.stopped = False

        self.state_changed()

        asyncio.ensure_future(self._reconnect())

    def stop_listen(self):
        """Stop listening to the socket"""

        self.stopped = True

        self.state_changed()

        self._disconnect()

    def create_protocol(self):
        """Create the socket protocol (implemented in derived class)"""
        raise NotImplementedError()

    def state_changed(self):
        """Handle a state change (implemented in derived class)"""
        raise NotImplementedError()
