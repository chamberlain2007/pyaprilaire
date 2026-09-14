"""Client for connecting to the Aprilaire thermostat socket"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

_LOGGER = logging.getLogger(__name__)


class SocketClient:
    """Client for connecting to the Aprilaire thermostat socket"""

    def __init__(
        self,
        host: str,
        port: int,
        data_received_callback: Callable[[dict[str, Any]], None],
        reconnect_interval: int | None = None,
        retry_connection_interval: int | None = None,
    ) -> None:
        """Initialize client"""
        self.host = host
        self.port = port
        self.data_received_callback = data_received_callback
        self.reconnect_interval = reconnect_interval
        self.retry_connection_interval = retry_connection_interval

        self.connected = False
        self.stopped = True
        self.reconnecting = False
        self.auto_reconnecting = False
        self.cancelled = False
        self.reconnect_break_future: asyncio.Future | None = None

        self.protocol: asyncio.Protocol | None = None

    async def _auto_reconnect_loop(self):
        """Wait for cancellable reconnect interval to pass, and perform reconnect"""
        if not self.reconnect_interval:
            return

        while True:
            if self.stopped or not self.connected:
                break

            if not self.reconnect_break_future:
                loop = asyncio.get_running_loop()
                self.reconnect_break_future = loop.create_future()

            try:
                await asyncio.wait_for(
                    self.reconnect_break_future, self.reconnect_interval
                )
                break
            except asyncio.CancelledError:
                break
            except TimeoutError:
                self.auto_reconnecting = True
                self.state_changed()

                await self._reconnect(10)

    def _cancel_auto_reconnect_loop(self):
        """Cancel the loop which does periodic reconnection"""
        if self.reconnect_break_future:
            try:
                self.reconnect_break_future.set_result(True)
            except asyncio.InvalidStateError:
                pass
            self.reconnect_break_future = None

    def _disconnect(self):
        """Disconnect from the socket"""
        self._cancel_auto_reconnect_loop()

        self.connected = False

        self.state_changed()

        if self.protocol and self.protocol.transport:
            self.protocol.transport.close()

    async def _reconnect(self, connect_wait_period: int = 0):
        """Reconnect to the socket"""

        if self.stopped or self.reconnecting:
            return

        self.reconnecting = True

        self.state_changed()

        self._disconnect()

        if connect_wait_period is not None and connect_wait_period > 0:
            await asyncio.sleep(connect_wait_period)

        self.protocol = self.create_protocol()

        try:
            await asyncio.get_running_loop().create_connection(
                lambda: self.protocol,
                self.host,
                self.port,
            )

            self._connection_established()

            asyncio.ensure_future(self._auto_reconnect_loop())

        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.error("Failed to connect to thermostat: %s", str(exc))

            self.reconnecting = False

            self.state_changed()

            if not self.stopped:
                asyncio.ensure_future(self._reconnect(10))

    async def _reconnect_once(self):
        """Reconnect to the socket without reconnect loop"""

        self.reconnecting = True

        self.state_changed()

        self._disconnect()

        self.protocol = self.create_protocol()

        await asyncio.get_running_loop().create_connection(
            lambda: self.protocol,
            self.host,
            self.port,
        )

        self._connection_established()

    def _connection_established(self):
        """Record a newly established connection.

        The "connection made" line is skipped for the periodic reconnect of
        `_auto_reconnect_loop`, which does not mean the connection was down.
        """
        if not self.auto_reconnecting:
            _LOGGER.info("Aprilaire connection made")

        self.connected = True
        self.reconnecting = False
        self.auto_reconnecting = False

        self.state_changed()

    async def start_listen(self):
        """Start listening to the socket"""

        self.stopped = False

        self.state_changed()

        await self._reconnect()

    async def start_listen_once(self):
        """Start listening to the socket without reconnect loop"""

        self.stopped = False

        self.state_changed()

        await self._reconnect_once()

    def stop_listen(self):
        """Stop listening to the socket"""

        self.stopped = True
        self.connected = False
        self.reconnecting = False
        self.auto_reconnecting = False

        self.state_changed()

        self._disconnect()

    def create_protocol(self) -> asyncio.Protocol:
        """Create the socket protocol (implemented in derived class)"""

    def state_changed(self):
        """Handle a state change (implemented in derived class)"""
