"""Client for interfacing with the thermostat"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from logging import Logger
from typing import Any

from .const import QUEUE_FREQUENCY, Action, Attribute, FunctionalDomain
from .packet import NackPacket, Packet
from .socket_client import SocketClient

# Spec section F: CNT is 2 bytes (0-65535), so a complete frame is at most
# CNT + 5 (REV, SEQ, CNT high/low, PAYLOAD, CRC) bytes. A receive buffer that
# grows past this without ever containing a single complete frame can only be
# a peer that isn't going to complete one (garbage on the wire, or a stalled
# connection) - cap it there so such a peer can't grow the buffer forever.
MAX_BUFFER_SIZE = 65535 + 5

# Sentinel distinguishing "no sequence argument passed" from an explicit
# `sequence=None` (which would mean "match by (functional_domain, attribute)
# only, don't pin to any sequence"). See `AprilaireClient.wait_for_response`.
_SEQUENCE_UNSET = object()


class _AprilaireClientProtocol(asyncio.Protocol):
    """Protocol for interacting with the thermostat over socket connection"""

    def __init__(
        self,
        data_received_callback: Callable[
            [FunctionalDomain, int, dict[str, Any], int | None], None
        ],
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

        # Sequence number of the most recently sent request for each
        # (functional_domain, attribute), keyed the same way as
        # `AprilaireClient.futures`. Spec section F notes 2-3: a Read
        # Response (and any retries of the request) reuse the sequence
        # number of the request that produced them, so this is what lets
        # `AprilaireClient.wait_for_response` correlate a response back to
        # the specific request that asked for it, rather than only
        # fuzzily matching by (functional_domain, attribute) - which is
        # also what an unsolicited COS on the same key would match (spec
        # section H.4).
        self.pending_request_sequences: dict[tuple[FunctionalDomain, int], int] = {}

        # Bytes received but not yet resolved into complete frames, see
        # `data_received`.
        self._receive_buffer = bytearray()

    def _get_sequence(self):
        self.sequence = (self.sequence + 1) % 128

        return self.sequence

    async def _send_packet(self, packet: Packet) -> int:
        """Send a command to the thermostat, returning the sequence number
        it was sent with"""

        packet.sequence = self._get_sequence()

        self.pending_request_sequences[(packet.functional_domain, packet.attribute)] = (
            packet.sequence
        )

        self.logger.debug(
            "Queuing data, sequence=%d, action=%s, functional_domain=%s, attribute=%d",
            packet.sequence,
            str(packet.action),
            str(packet.functional_domain),
            packet.attribute,
        )

        await self.packet_queue.put(packet)

        return packet.sequence

    def _empty_packet_queue(self):
        try:
            for _ in range(self.packet_queue.qsize()):
                self.packet_queue.get_nowait()
                self.packet_queue.task_done()
        except Exception:
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
                        try:
                            serialized_packet = packet.serialize()

                            self.logger.info(
                                "Sent data: %s", serialized_packet.hex(" ")
                            )

                            self.transport.write(serialized_packet)
                        except Exception:
                            self.logger.exception(
                                "Failed to send packet, action=%s, "
                                "functional_domain=%s, attribute=%s",
                                packet.action,
                                packet.functional_domain,
                                packet.attribute,
                            )
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

        # A reconnect must not inherit a partial frame left over from
        # whatever connection preceded this one.
        self._receive_buffer = bytearray()

        asyncio.ensure_future(self._queue_loop())
        asyncio.ensure_future(self._update_status())

    def _parse_received_data(self, data: bytes) -> list[Packet]:
        """Buffer newly-received bytes and parse whatever complete frames
        that leaves available.

        A single TCP read can contain several frames, or only part of one -
        the socket gives no guarantee that frame boundaries line up with
        read boundaries. `Packet.get_parseable_length` tells us how much of
        the accumulated buffer is made up of complete frames; anything past
        that is a partial frame and stays buffered for the next call.
        """
        self._receive_buffer.extend(data)

        parseable_length = Packet.get_parseable_length(self._receive_buffer)

        if parseable_length == 0:
            if len(self._receive_buffer) > MAX_BUFFER_SIZE:  # pragma: no cover
                # Unreachable given get_parseable_length's contract: a
                # frame's declared length is capped at MAX_BUFFER_SIZE (CNT
                # is at most 65535), so a buffer longer than that always
                # has a resolvable frame boundary at its start, making
                # parseable_length == 0 impossible here. Kept as a guard in
                # case that contract ever changes.
                self.logger.error(
                    "Discarding %d bytes without a complete frame",
                    len(self._receive_buffer),
                )
                self._receive_buffer = bytearray()

            return []

        parseable_data = bytes(self._receive_buffer[:parseable_length])
        del self._receive_buffer[:parseable_length]

        return list(Packet.parse(parseable_data))

    def data_received(self, data: bytes) -> None:
        """Called when data has been received from the socket"""
        self.logger.info("Aprilaire data received %s", data.hex(" "))

        try:
            parsed_packets = self._parse_received_data(data)
        except Exception:
            # Whatever went wrong, it must not propagate out of this
            # callback: asyncio's transport treats any exception escaping
            # data_received as fatal and closes the connection (see
            # asyncio/selector_events.py's _read_ready__data_received).
            self.logger.exception("Failed to parse received data")
            return

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
                        packet.functional_domain,
                        packet.attribute,
                        packet.data,
                        packet.sequence,
                    )
                )

    def connection_lost(self, exc: Exception | None) -> None:
        """Called when the connection to the socket has been lost"""
        self.logger.info("Aprilaire connection lost")

        if self.data_received_callback:
            asyncio.ensure_future(
                self.data_received_callback(
                    FunctionalDomain.NONE, 0, {Attribute.AVAILABLE: False}, None
                )
            )

        self.transport = None

        # Don't let a frame that was only half-received on this connection
        # bleed into whatever gets received after a reconnect.
        self._receive_buffer = bytearray()

        if self.reconnect_action:
            asyncio.ensure_future(self.reconnect_action())

    async def read_sensors(self):
        """Send a request for updated sensor data"""
        return await self._send_packet(
            Packet(Action.READ_REQUEST, FunctionalDomain.SENSORS, 2)
        )

    async def read_control(self):
        """Send a request for updated control data"""
        return await self._send_packet(
            Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1)
        )

    async def read_scheduling(self):
        """Send a request for updated scheduling data"""
        return await self._send_packet(
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
        return await self._send_packet(
            Packet(Action.READ_REQUEST, FunctionalDomain.IDENTIFICATION, 2)
        )

    async def read_thermostat_name(self):
        """Send a reques for the thermostat name"""
        return await self._send_packet(
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

    async def set_written_outdoor_temperature_value(self, value: int):
        """Send a request to update the written outdoor temperature value"""
        await self._send_packet(
            Packet(
                Action.WRITE,
                FunctionalDomain.SENSORS,
                4,
                data={
                    Attribute.OUTDOOR_SENSOR_STATUS: 0,
                    Attribute.OUTDOOR_SENSOR: value,
                },
            )
        )

    async def read_thermostat_iaq_available(self):
        """Send a request to read the thermostat/IAQ available data"""
        return await self._send_packet(
            Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 7)
        )

    async def read_thermostat_status(self):
        """Send a request to read the thermostat status"""
        return await self._send_packet(
            Packet(Action.READ_REQUEST, FunctionalDomain.STATUS, 6)
        )

    async def read_iaq_status(self):
        """Send a request to read the IAQ status"""
        return await self._send_packet(
            Packet(Action.READ_REQUEST, FunctionalDomain.STATUS, 7)
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

        # Each entry pairs a waiter's future with the sequence number (spec
        # section F notes 2-3) of the request it is waiting on, captured at
        # `wait_for_response` time - or None if no such request could be
        # found, in which case the future is only ever matched by
        # (functional_domain, attribute), same as before sequence tracking
        # existed. See `data_received` for how that pairing is used to
        # decide which incoming packet, if any, resolves a given future.
        self.futures: dict[
            tuple[FunctionalDomain, int], list[tuple[asyncio.Future, int | None]]
        ] = {}

    async def _reconnect_with_delay(self):
        await super()._reconnect(self.retry_connection_interval)

    def create_protocol(self):
        return _AprilaireClientProtocol(
            self.data_received, self._reconnect_with_delay, self.logger
        )

    async def data_received(
        self,
        functional_domain: FunctionalDomain,
        attribute: int,
        data: dict[str, Any],
        sequence: int | None = None,
    ):
        """Called when data is received from the thermostat"""

        self.data_received_callback(data)

        # `FunctionalDomain.NONE` and attribute 0 are both real, meaningful
        # values (e.g. attribute 0 is used by a mapped response) - only the
        # complete absence of a domain/attribute (as in the connection-state
        # callbacks below, or a caller with nothing to report) should skip
        # future resolution.
        if functional_domain is None or attribute is None:
            return

        future_key = (functional_domain, attribute)

        pending_entries = self.futures.pop(future_key, [])

        unresolved_entries = []

        for future, expected_sequence in pending_entries:
            # A future that captured a specific expected sequence number is
            # pinned to the single request that created it - only a
            # response (or NACK) carrying that same sequence number may
            # resolve it. This is what stops an unsolicited COS on the same
            # (functional_domain, attribute) from resolving a future meant
            # for a read response (spec section H.4): a device-originated
            # COS carries a sequence number in the thermostat's 128-255
            # range (spec section F note 1), which never matches a
            # 0-127 sequence we generated for our own request. It's also
            # what lets two concurrent requests for the same key be
            # resolved independently instead of both being satisfied by
            # whichever response happens to arrive first.
            if expected_sequence is not None and expected_sequence != sequence:
                unresolved_entries.append((future, expected_sequence))
                continue

            try:
                future.set_result(data)
            except asyncio.exceptions.InvalidStateError:
                pass

        if unresolved_entries:
            self.futures[future_key] = unresolved_entries

    def state_changed(self):
        """Send data indicating the state as changed"""
        data = {
            Attribute.CONNECTED: self.connected,
            Attribute.STOPPED: self.stopped,
            Attribute.RECONNECTING: self.reconnecting,
        }

        self.data_received_callback(data)

    async def test_connection(self) -> str:
        """Test connecting to a thermostat without entering a reconnect loop."""

        await self.start_listen_once()

        await self.read_mac_address()

        await self.wait_for_response(FunctionalDomain.IDENTIFICATION, 2, 5)

        self.stop_listen()

    async def wait_for_response(
        self,
        functional_domain: FunctionalDomain,
        attribute: int,
        timeout: int = None,
        sequence: int | None = _SEQUENCE_UNSET,
    ):
        """Wait for a response for a particular request.

        `sequence`, if given, pins this wait to that exact sequence number
        (see `read_mac_address_and_wait` and its siblings, which pass the
        value their own send just returned). This must be used whenever the
        send and the wait aren't a single atomic step from the caller's
        point of view: looking up "the most recently sent request's
        sequence" here instead is racy - a second call to the same
        `read_*`/`set_*` method between this caller's send and its call to
        `wait_for_response` would overwrite `pending_request_sequences`
        before this method ever reads it, pinning this wait to the wrong
        request.
        """

        loop = asyncio.get_event_loop()
        future = loop.create_future()

        future_key = (functional_domain, attribute)

        if sequence is not _SEQUENCE_UNSET:
            expected_sequence = sequence
        else:
            # Fallback for a caller that didn't capture its own send's
            # sequence: use the sequence number of the most recently sent
            # request for this (functional_domain, attribute), if there is
            # one, so the response can still be correlated back to a
            # request rather than to any packet that happens to share its
            # domain/attribute - see `data_received`. Racy as described
            # above; kept only for callers that predate sequence capture.
            expected_sequence = None
            if self.protocol is not None:
                expected_sequence = self.protocol.pending_request_sequences.get(
                    future_key
                )

        entry = (future, expected_sequence)

        self.futures.setdefault(future_key, []).append(entry)

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
        finally:
            # Whether resolved, timed out, or cancelled, this entry must not
            # linger in self.futures - otherwise a timed-out wait leaves a
            # stale entry behind forever (data_received only pops entries
            # when a matching response actually arrives).
            pending_entries = self.futures.get(future_key)

            if pending_entries is not None:
                try:
                    pending_entries.remove(entry)
                except ValueError:
                    pass

                if not pending_entries:
                    self.futures.pop(future_key, None)

    async def read_sensors(self):
        """Send a request for updated sensor data"""
        return await self.protocol.read_sensors()

    async def read_sensors_and_wait(self, timeout: int = None):
        """Send a request for updated sensor data and wait for the response"""
        sequence = await self.read_sensors()
        return await self.wait_for_response(
            FunctionalDomain.SENSORS, 2, timeout, sequence=sequence
        )

    async def read_control(self):
        """Send a request for updated control data"""
        return await self.protocol.read_control()

    async def read_control_and_wait(self, timeout: int = None):
        """Send a request for updated control data and wait for the response"""
        sequence = await self.read_control()
        return await self.wait_for_response(
            FunctionalDomain.CONTROL, 1, timeout, sequence=sequence
        )

    async def read_scheduling(self):
        """Send a request for updated scheduling data"""
        return await self.protocol.read_scheduling()

    async def read_scheduling_and_wait(self, timeout: int = None):
        """Send a request for updated scheduling data and wait for the response"""
        sequence = await self.read_scheduling()
        return await self.wait_for_response(
            FunctionalDomain.SCHEDULING, 4, timeout, sequence=sequence
        )

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
        return await self.protocol.read_mac_address()

    async def read_mac_address_and_wait(self, timeout: int = None):
        """Send a request to read the MAC address and wait for the response"""
        sequence = await self.read_mac_address()
        return await self.wait_for_response(
            FunctionalDomain.IDENTIFICATION, 2, timeout, sequence=sequence
        )

    async def read_thermostat_name(self):
        """Send a request to read the thermostat name"""
        return await self.protocol.read_thermostat_name()

    async def read_thermostat_name_and_wait(self, timeout: int = None):
        """Send a request to read the thermostat name and wait for the response"""
        sequence = await self.read_thermostat_name()
        return await self.wait_for_response(
            FunctionalDomain.IDENTIFICATION, 5, timeout, sequence=sequence
        )

    async def set_dehumidification_setpoint(self, dehumidification_setpoint: int):
        await self.protocol.set_dehumidification_setpoint(dehumidification_setpoint)

    async def set_humidification_setpoint(self, humidification_setpoint: int):
        await self.protocol.set_humidification_setpoint(humidification_setpoint)

    async def set_fresh_air(self, mode: int, event: int):
        await self.protocol.set_fresh_air(mode, event)

    async def set_air_cleaning(self, mode: int, event: int):
        await self.protocol.set_air_cleaning(mode, event)

    async def set_written_outdoor_temperature_value(self, value: int):
        """Send a request to update the written outdoor temperature value"""
        await self.protocol.set_written_outdoor_temperature_value(value)

    async def read_thermostat_iaq_available(self):
        """Send a request to read the thermostat/IAQ available data"""
        return await self.protocol.read_thermostat_iaq_available()

    async def read_thermostat_iaq_available_and_wait(self, timeout: int = None):
        """Send a request to read the thermostat/IAQ available data and wait
        for the response"""
        sequence = await self.read_thermostat_iaq_available()
        return await self.wait_for_response(
            FunctionalDomain.CONTROL, 7, timeout, sequence=sequence
        )

    async def read_thermostat_status(self):
        """Send a request to read the thermostat status"""
        return await self.protocol.read_thermostat_status()

    async def read_thermostat_status_and_wait(self, timeout: int = None):
        """Send a request to read the thermostat status and wait for the
        response"""
        sequence = await self.read_thermostat_status()
        return await self.wait_for_response(
            FunctionalDomain.STATUS, 6, timeout, sequence=sequence
        )

    async def read_iaq_status(self):
        """Send a request to read the IAQ status"""
        return await self.protocol.read_iaq_status()

    async def read_iaq_status_and_wait(self, timeout: int = None):
        """Send a request to read the IAQ status and wait for the response"""
        sequence = await self.read_iaq_status()
        return await self.wait_for_response(
            FunctionalDomain.STATUS, 7, timeout, sequence=sequence
        )
