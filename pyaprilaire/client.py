"""Client for interfacing with the thermostat"""

from __future__ import annotations

import asyncio

from collections.abc import Callable
from logging import Logger
from typing import Any

from .const import Action, Attribute, FunctionalDomain, QUEUE_FREQUENCY
from .packet import NackPacket, Packet
from .socket_client import SocketClient


class _AprilaireClientProtocol(asyncio.Protocol):
    """Protocol for interacting with the thermostat over socket connection"""

    def __init__(
        self,
        data_received_callback: Callable[[FunctionalDomain, int, dict[str, Any]], None],
        reconnect_action: Callable[[], None],
        logger: Logger,
    ) -> None:
        """Initialize the protocol"""
        self.data_received_callback = data_received_callback
        self.reconnect_action = reconnect_action
        self.logger = logger

        self.transport: asyncio.Transport = None

        self.packet_queue = asyncio.Queue()

        self.sequence = 0

    def _get_sequence(self):
        self.sequence = (self.sequence + 1) % 128

        return self.sequence

    async def _send_packet(self, packet: Packet) -> None:
        """Send a command to the thermostat"""

        packet.sequence = self._get_sequence()

        self.logger.debug(
            "Queuing data, sequence=%d, action=%s, functional_domain=%s, attribute=%d",
            packet.sequence,
            str(packet.action),
            str(packet.functional_domain),
            packet.attribute,
        )

        await self.packet_queue.put(packet)

    def _empty_packet_queue(self):
        try:
            for _ in range(self.packet_queue.qsize()):
                self.packet_queue.get_nowait()
                self.packet_queue.task_done()
        except:  # pylint: disable=bare-except
            pass

    async def _queue_loop(self, loop_count=None):
        """Periodically send items from the queue"""
        while loop_count is None or loop_count > 0:
            if loop_count is not None:
                loop_count -= 1

            try:
                packet: Packet

                while packet := self.packet_queue.get_nowait():
                    if self.transport:
                        serialized_packet = packet.serialize()

                        self.logger.info("Sent data: %s", serialized_packet.hex(" "))

                        self.transport.write(serialized_packet)
            except asyncio.QueueEmpty:
                pass

            await asyncio.sleep(QUEUE_FREQUENCY)

    async def _update_status(self):
        await asyncio.sleep(2)

        await self.read_mac_address()
        await self.read_thermostat_status()
        await self.read_control()
        await self.read_sensors()
        await self.read_thermostat_name()
        await self.configure_cos()
        await self.read_dehumidification_setpoint()
        await self.read_humidification_setpoint()
        await self.sync()

    def connection_made(self, transport: asyncio.Transport):
        """Called when a connection has been made to the socket"""
        self.logger.info("Aprilaire connection made")

        self.transport = transport
        self._empty_packet_queue()

        asyncio.ensure_future(self._queue_loop())
        asyncio.ensure_future(self._update_status())

    def data_received(self, data: bytes) -> None:
        """Called when data has been received from the socket"""
        self.logger.info("Aprilaire data received %s", data.hex(" "))

        parsed_packets = Packet.parse(data)

        for packet in parsed_packets:
            self.logger.debug(
                "Received data, action=%s, functional_domain=%s, attribute=%d",
                str(packet.action),
                str(packet.functional_domain),
                packet.attribute,
            )

            if isinstance(packet, NackPacket):
                self.logger.error(
                    "Received NACK for attribute %d", packet.nack_attribute
                )
                continue

            if Attribute.ERROR in packet.data:
                error = packet.data[Attribute.ERROR]

                if error != 0:
                    self.logger.error("Thermostat error: %d", error)

            if (
                packet.action == Action.COS
                and packet.functional_domain == FunctionalDomain.CONTROL
                and packet.attribute == 1
                and packet.data.get(Attribute.MODE) == 1
            ):
                self.logger.info("Re-reading control because of COS with mode==1")

                asyncio.ensure_future(self.read_control())

                continue

            if self.data_received_callback:
                asyncio.ensure_future(
                    self.data_received_callback(
                        packet.functional_domain, packet.attribute, packet.data
                    )
                )

    def connection_lost(self, exc: Exception | None) -> None:
        """Called when the connection to the socket has been lost"""
        self.logger.info("Aprilaire connection lost")

        if self.data_received_callback:
            asyncio.ensure_future(
                self.data_received_callback(
                    FunctionalDomain.NONE, 0, {Attribute.AVAILABLE: False}
                )
            )

        self.transport = None

        if self.reconnect_action:
            asyncio.ensure_future(self.reconnect_action())

    async def read_sensors(self):
        """Send a request for updated sensor data"""
        await self._send_packet(
            Packet(Action.READ_REQUEST, FunctionalDomain.SENSORS, 2)
        )

    async def read_control(self):
        """Send a request for updated control data"""
        await self._send_packet(
            Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1)
        )

    async def read_scheduling(self):
        """Send a request for updated scheduling data"""
        await self._send_packet(
            Packet(Action.READ_REQUEST, FunctionalDomain.SCHEDULING, 4)
        )

    async def update_mode(self, mode: int):
        """Send a request to update the mode"""
        await self._send_packet(
            Packet(
                Action.WRITE,
                FunctionalDomain.CONTROL,
                1,
                data={
                    Attribute.MODE: mode,
                    Attribute.FAN_MODE: 0,
                    Attribute.HEAT_SETPOINT: 0,
                    Attribute.COOL_SETPOINT: 0,
                },
            )
        )

    async def update_fan_mode(self, fan_mode: int):
        """Send a request to update the fan mode"""
        await self._send_packet(
            Packet(
                Action.WRITE,
                FunctionalDomain.CONTROL,
                1,
                data={
                    Attribute.MODE: 0,
                    Attribute.FAN_MODE: fan_mode,
                    Attribute.HEAT_SETPOINT: 0,
                    Attribute.COOL_SETPOINT: 0,
                },
            )
        )

    async def update_setpoint(self, cool_setpoint: float, heat_setpoint: float):
        """Send a request to update the setpoint"""

        cool_setpoint = round(cool_setpoint * 2) / 2
        heat_setpoint = round(heat_setpoint * 2) / 2

        await self._send_packet(
            Packet(
                Action.WRITE,
                FunctionalDomain.CONTROL,
                1,
                data={
                    Attribute.MODE: 0,
                    Attribute.FAN_MODE: 0,
                    Attribute.HEAT_SETPOINT: heat_setpoint,
                    Attribute.COOL_SETPOINT: cool_setpoint,
                },
            )
        )

    async def set_hold(self, hold: int):
        """Send a request to set the hold status"""

        await self._send_packet(
            Packet(
                Action.WRITE,
                FunctionalDomain.SCHEDULING,
                4,
                data={Attribute.HOLD: hold},
            )
        )

    async def set_dehumidification_setpoint(self, dehumidification_setpoint: int):
        await self._send_packet(
            Packet(
                Action.WRITE,
                FunctionalDomain.CONTROL,
                3,
                data={Attribute.DEHUMIDIFICATION_SETPOINT: dehumidification_setpoint},
            )
        )

        await self.read_dehumidification_setpoint()

    async def set_humidification_setpoint(self, humidification_setpoint: int):
        await self._send_packet(
            Packet(
                Action.WRITE,
                FunctionalDomain.CONTROL,
                4,
                data={Attribute.HUMIDIFICATION_SETPOINT: humidification_setpoint},
            )
        )

        await self.read_humidification_setpoint()

    async def set_fresh_air(self, mode: int, event: int):
        await self._send_packet(
            Packet(
                Action.WRITE,
                FunctionalDomain.CONTROL,
                5,
                data={Attribute.FRESH_AIR_MODE: mode, Attribute.FRESH_AIR_EVENT: event},
            )
        )

    async def set_air_cleaning(self, mode: int, event: int):
        await self._send_packet(
            Packet(
                Action.WRITE,
                FunctionalDomain.CONTROL,
                6,
                data={
                    Attribute.AIR_CLEANING_MODE: mode,
                    Attribute.AIR_CLEANING_EVENT: event,
                },
            )
        )

    async def sync(self):
        """Send a request to sync data"""
        await self._send_packet(
            Packet(
                Action.WRITE,
                FunctionalDomain.STATUS,
                2,
                data={Attribute.SYNCED: 1},
            )
        )

    async def configure_cos(self):
        """Send a request to configure the COS settings"""
        await self._send_packet(
            Packet(
                Action.WRITE,
                FunctionalDomain.STATUS,
                1,
                raw_data=[
                    1,  # Installer Thermostat Settings
                    0,  # Contractor Information
                    0,  # Air Cleaning Installer Variable
                    0,  # Humidity Control Installer Settings
                    0,  # Fresh Air Installer Settings
                    1,  # Thermostat Setpoint & Mode Settings
                    1,  # Dehumidification Setpoint
                    1,  # Humidification Setpoint
                    1,  # Fresh Air Settings
                    1,  # Air Cleaning Settings
                    1,  # Thermostat IAQ Available
                    0,  # Schedule Settings
                    1,  # Away Settings
                    0,  # Schedule Day
                    1,  # Schedule Hold
                    0,  # Heat Blast
                    0,  # Service Reminders Status
                    0,  # Alerts Status
                    0,  # Alerts Settings
                    0,  # Backlight Settings
                    1,  # Thermostat Location & Name
                    0,  # Reserved
                    1,  # Controlling Sensor Values
                    0,  # Over the air ODT update timeout
                    1,  # Thermostat Status
                    1,  # IAQ Status
                    1,  # Model & Revision
                    0,  # Support Module
                    0,  # Lockouts
                ],
            )
        )

    async def read_mac_address(self):
        """Send a request to get identification data (including MAC address)"""
        await self._send_packet(
            Packet(Action.READ_REQUEST, FunctionalDomain.IDENTIFICATION, 2)
        )

    async def read_thermostat_status(self):
        """Send a request for thermostat status"""
        await self._send_packet(
            Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 7)
        )

    async def read_thermostat_name(self):
        """Send a reques for the thermostat name"""
        await self._send_packet(
            Packet(Action.READ_REQUEST, FunctionalDomain.IDENTIFICATION, 5)
        )

    async def read_dehumidification_setpoint(self):
        """Send a request for the dehumidification setpoint"""
        await self._send_packet(
            Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 3)
        )

    async def read_humidification_setpoint(self):
        """Send a request for the humidification setpoint"""
        await self._send_packet(
            Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 4)
        )


class AprilaireClient(SocketClient):
    """Client for sending/receiving data"""

    def __init__(
        self,
        host: str,
        port: int,
        data_received_callback: Callable[[dict[str, Any]], None],
        logger: Logger,
        reconnect_interval: int = None,
        retry_connection_interval: int = None,
    ) -> None:
        self.protocol: _AprilaireClientProtocol = None

        super().__init__(
            host,
            port,
            data_received_callback,
            logger,
            reconnect_interval,
            retry_connection_interval,
        )

        self.futures: dict[tuple[FunctionalDomain, int], list[asyncio.Future]] = {}

    async def _reconnect_with_delay(self):
        await super()._reconnect(self.retry_connection_interval)

    def create_protocol(self):
        return _AprilaireClientProtocol(
            self.data_received, self._reconnect_with_delay, self.logger
        )

    async def data_received(
        self, functional_domain: FunctionalDomain, attribute: int, data: dict[str, Any]
    ):
        """Called when data is received from the thermostat"""
        self.data_received_callback(data)

        if not functional_domain or not attribute:
            return

        future_key = (functional_domain, attribute)

        futures_to_complete = self.futures.pop(future_key, [])

        for future in futures_to_complete:
            try:
                future.set_result(data)
            except asyncio.exceptions.InvalidStateError:
                pass

    def state_changed(self):
        """Send data indicating the state as changed"""
        data = {
            Attribute.CONNECTED: self.connected,
            Attribute.STOPPED: self.stopped,
            Attribute.RECONNECTING: self.reconnecting,
        }

        self.data_received_callback(data)

    async def wait_for_response(
        self, functional_domain: FunctionalDomain, attribute: int, timeout: int = None
    ):
        """Wait for a response for a particular request"""

        loop = asyncio.get_event_loop()
        future = loop.create_future()

        future_key = (functional_domain, attribute)

        if future_key not in self.futures:
            self.futures[future_key] = []

        self.futures[future_key].append(future)

        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.exceptions.TimeoutError:
            self.logger.error(
                "Hit timeout of %d waiting for %s, %d",
                timeout,
                int(functional_domain),
                attribute,
            )
            return None

    async def read_sensors(self):
        """Send a request for updated sensor data"""
        await self.protocol.read_sensors()

    async def read_control(self):
        """Send a request for updated control data"""
        await self.protocol.read_control()

    async def read_scheduling(self):
        """Send a request for updated scheduling data"""
        await self.protocol.read_scheduling()

    async def update_mode(self, mode: int):
        """Send a request to update the mode"""
        await self.protocol.update_mode(mode)

    async def update_fan_mode(self, fan_mode: int):
        """Send a request to update the fan mode"""
        await self.protocol.update_fan_mode(fan_mode)

    async def update_setpoint(self, cool_setpoint: float, heat_setpoint: float):
        """Send a request to update the setpoint"""
        await self.protocol.update_setpoint(cool_setpoint, heat_setpoint)

    async def set_hold(self, hold: int):
        """Send a request to update the away status"""
        await self.protocol.set_hold(hold)

    async def sync(self):
        """Send a request to sync data"""
        await self.protocol.sync()

    async def read_mac_address(self):
        """Send a request to read the MAC address"""
        await self.protocol.read_mac_address()

    async def read_thermostat_status(self):
        """Send a request to read the thermostat status"""
        await self.protocol.read_thermostat_status()

    async def read_thermostat_name(self):
        """Send a request to read the thermostat name"""
        await self.protocol.read_thermostat_name()

    async def set_dehumidification_setpoint(self, dehumidification_setpoint: int):
        await self.protocol.set_dehumidification_setpoint(dehumidification_setpoint)

    async def set_humidification_setpoint(self, humidification_setpoint: int):
        await self.protocol.set_humidification_setpoint(humidification_setpoint)

    async def set_fresh_air(self, mode: int, event: int):
        await self.protocol.set_fresh_air(mode, event)

    async def set_air_cleaning(self, mode: int, event: int):
        await self.protocol.set_air_cleaning(mode, event)
