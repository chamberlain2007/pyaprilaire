"""Client for interfacing with the thermostat"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

from .const import QUEUE_FREQUENCY, Action, Attribute, FunctionalDomain, NackStatus
from .packet import NackPacket, Packet
from .socket_client import SocketClient

_LOGGER = logging.getLogger(__name__)

# Spec section F: CNT is 2 bytes, so a complete frame is at most CNT + 5
# (REV, SEQ, CNT high/low, PAYLOAD, CRC) bytes. A buffer past this holds no
# complete frame and never will.
MAX_BUFFER_SIZE = 65535 + 5

# Spec section H.5 "Action in Case of NACK": the only status codes whose
# action is to retry rather than to clear the transaction from the queue.
RETRYABLE_NACK_STATUSES = frozenset(
    {
        NackStatus.GENERIC_ERROR,
        NackStatus.BUFFER_FULL_OR_DEVICE_BUSY,
        NackStatus.TIMED_OUT_WAITING_FOR_RESPONSE,
    }
)

# Spec section H.5: "Retry 2 additional times", i.e. 3 attempts in total.
MAX_NACK_RETRIES = 2

# Spec section H.5: "0.5 to 1 second delay between retries".
NACK_RETRY_DELAY_RANGE = (0.5, 1.0)

# The NACK status codes that say the device does not implement an attribute
# at all, as opposed to refusing this one request. `AprilaireClient` caches
# these against the attribute (see `unsupported_attributes`) and stops asking;
# every other status code is about the request, so caching it would disable a
# working attribute.
UNSUPPORTED_NACK_STATUSES = frozenset(
    {
        NackStatus.UNKNOWN_FUNCTIONAL_DOMAIN,
        NackStatus.UNKNOWN_ATTRIBUTE,
        NackStatus.UNSUPPORTED_MODEL,
    }
)


class AprilaireResponseError(Exception):
    """Base class for a request failing to produce response data.

    The subclasses say why: `ResponseTimeoutError` for nothing coming back
    in time, `NackError` for the thermostat rejecting the request.
    """


class NackError(AprilaireResponseError):
    """Raised to fail a `wait_for_response` future for a terminally-NACKed
    request.

    Per spec section H.5 the request has permanently failed; the codes in
    `RETRYABLE_NACK_STATUSES` raise this only once their retries are spent.
    """

    def __init__(self, status: NackStatus | None, raw_status: int) -> None:
        self.status = status
        self.raw_status = raw_status

        status_description = status.name if status is not None else "UNKNOWN"

        super().__init__(
            f"Request was NACKed with status {status_description} (0x{raw_status:02X})"
        )


class UnsupportedAttributeError(NackError):
    """Raised for a request this device has already permanently refused.

    Once a terminal NACK with one of `UNSUPPORTED_NACK_STATUSES` proves the
    thermostat doesn't implement an attribute, `AprilaireClient` raises this
    instead of putting the request on the wire. The NACK that discovers it
    raises this too, so catching the type doesn't depend on whether the
    answer came from the device or from the cache. It carries the status of
    the NACK behind it.
    """


class ResponseTimeoutError(AprilaireResponseError):
    """Raised when no response arrived for a request before its timeout.

    A failure to hear back rather than a refusal, so the same request may
    succeed later. Deliberately not a subclass of `TimeoutError`, which is an
    `OSError` and would put a protocol timeout inside every `except OSError`
    meant for the socket.
    """

    def __init__(
        self,
        functional_domain: FunctionalDomain,
        attribute: int,
        timeout: float | None,
    ) -> None:
        self.functional_domain = functional_domain
        self.attribute = attribute
        self.timeout = timeout

        super().__init__(
            f"Timed out after {timeout} seconds waiting for a response for "
            f"{functional_domain.name} ({int(functional_domain)}), "
            f"attribute {attribute}"
        )


# How long to wait for a COS Subscriptions read response (spec 7.1) before
# falling back to writing the desired mask unconditionally.
COS_SUBSCRIPTIONS_READ_TIMEOUT = 5

# Spec 7.1: the 29 COS Subscription bytes in wire order, paired with the value
# this library wants for each. The device enables every channel by default
# (spec Appendix J.1); enabled here are only the channels a `read_*`/`set_*`
# method consumes, plus bytes 16-18 and 23, which spec J.18/J.19/J.15 name as
# the only source for data this library supports. Byte 21 is Reserved, hence
# `None`. `AprilaireClient.configure_cos` overrides any of it.
COS_SUBSCRIPTIONS = [
    (Attribute.COS_INSTALLER_THERMOSTAT_SETTINGS, 0),
    (Attribute.COS_CONTRACTOR_INFORMATION, 0),
    (Attribute.COS_AIR_CLEANING_INSTALLER_SETTINGS, 0),
    (Attribute.COS_HUMIDITY_CONTROL_INSTALLER_SETTINGS, 0),
    (Attribute.COS_FRESH_AIR_INSTALLER_SETTINGS, 0),
    (Attribute.COS_THERMOSTAT_SETPOINT_AND_MODE_SETTINGS, 1),
    (Attribute.COS_DEHUMIDIFICATION_SETPOINT, 1),
    (Attribute.COS_HUMIDIFICATION_SETPOINT, 1),
    (Attribute.COS_FRESH_AIR_SETTING, 1),
    (Attribute.COS_AIR_CLEANING_SETTINGS, 1),
    (Attribute.COS_THERMOSTAT_IAQ_AVAILABLE, 1),
    (Attribute.COS_SCHEDULE_SETTINGS, 1),
    (Attribute.COS_AWAY_SETTINGS, 0),
    (Attribute.COS_SCHEDULE_DAY, 0),
    (Attribute.COS_SCHEDULE_HOLD, 1),
    (Attribute.COS_HEAT_BLAST, 0),
    (Attribute.COS_SERVICE_REMINDERS_STATUS, 1),
    (Attribute.COS_ALERTS_STATUS, 1),
    (Attribute.COS_ALERTS_SETTINGS, 1),
    (Attribute.COS_BACKLIGHT_SETTINGS, 0),
    (Attribute.COS_THERMOSTAT_LOCATION_AND_NAME, 1),
    (None, 0),
    (Attribute.COS_CONTROLLING_SENSOR_VALUES, 1),
    (Attribute.COS_OVER_THE_AIR_ODT_UPDATE_TIMEOUT, 1),
    (Attribute.COS_THERMOSTAT_STATUS, 1),
    (Attribute.COS_IAQ_STATUS, 1),
    (Attribute.COS_MODEL_AND_REVISION, 0),
    (Attribute.COS_SUPPORT_MODULE, 0),
    (Attribute.COS_LOCKOUTS, 0),
]

# The desired mask as a dict, excluding byte 21 (Reserved has no Attribute).
DEFAULT_COS_SUBSCRIPTIONS: dict[Attribute, int] = {
    attribute: value for attribute, value in COS_SUBSCRIPTIONS if attribute is not None
}

type AttributeKey = tuple[FunctionalDomain, int]

# Attributes whose support varies by thermostat model (spec 5.1 RAT/LAT
# sensors, spec 5.4 written outdoor temperature), paired with the attribute
# `AprilaireClient` reports their availability under. A model without them
# answers a read with a NACK rather than with data.
AVAILABILITY_ATTRIBUTES: dict[AttributeKey, Attribute] = {
    (FunctionalDomain.SENSORS, 1): Attribute.SENSOR_VALUES_AVAILABLE,
    (FunctionalDomain.SENSORS, 4): Attribute.WRITTEN_OUTDOOR_TEMPERATURE_AVAILABLE,
}


class _AprilaireClientProtocol(asyncio.Protocol):
    """Protocol for interacting with the thermostat over socket connection"""

    def __init__(
        self,
        data_received_callback: Callable[
            [FunctionalDomain, int, dict[str, Any], int | None], None
        ],
        reconnect_action: Callable[[], Awaitable[None]] | None = None,
        connected_action: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Initialize the protocol"""
        self.data_received_callback = data_received_callback
        self.reconnect_action = reconnect_action

        # Called once the socket is up and the send queue is running, so the
        # owning client can run its own request sequence on a fresh
        # connection. `None` means connecting only starts the queue loop.
        self.connected_action = connected_action

        self.transport: asyncio.Transport | None = None

        self.packet_queue = asyncio.Queue()

        self.sequence = 0

        # The most recently sent packet for each sequence number, with its
        # NACK retry count, so `_handle_nack` can attribute a NACK back to
        # the request that caused it. Bounded at 128 entries by
        # `_get_sequence` cycling sequence numbers through 0-127.
        self._in_flight_requests: dict[int, tuple[Packet, int]] = {}

        self._receive_buffer = bytearray()

    def _get_sequence(self):
        self.sequence = (self.sequence + 1) % 128

        return self.sequence

    async def _send_packet(self, packet: Packet) -> int:
        """Send a command to the thermostat, returning the sequence number
        it was sent with"""

        packet.sequence = self._get_sequence()

        self._in_flight_requests[packet.sequence] = (packet, 0)

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

                            _LOGGER.debug("Sent data: %s", serialized_packet.hex(" "))

                            self.transport.write(serialized_packet)
                        except Exception:
                            _LOGGER.exception(
                                "Failed to send packet, action=%s, "
                                "functional_domain=%s, attribute=%s",
                                packet.action,
                                packet.functional_domain,
                                packet.attribute,
                            )
            except asyncio.QueueEmpty:
                pass

            await asyncio.sleep(QUEUE_FREQUENCY)

    def connection_made(self, transport: asyncio.Transport):
        """Called when a connection has been made to the socket"""
        self.transport = transport
        self._empty_packet_queue()

        self._receive_buffer = bytearray()

        asyncio.ensure_future(self._queue_loop())

        if self.connected_action:
            asyncio.ensure_future(self.connected_action())

    def _parse_received_data(self, data: bytes) -> list[Packet]:
        """Buffer newly-received bytes and parse whatever complete frames
        that leaves available.

        A single TCP read can contain several frames, or only part of one, so
        a trailing partial frame stays buffered for the next call.
        """
        self._receive_buffer.extend(data)

        parseable_length = Packet.get_parseable_length(self._receive_buffer)

        if parseable_length == 0:
            if len(self._receive_buffer) > MAX_BUFFER_SIZE:  # pragma: no cover
                # Unreachable while get_parseable_length always finds a
                # frame boundary in a buffer this long.
                self._receive_buffer = bytearray()

            return []

        parseable_data = bytes(self._receive_buffer[:parseable_length])
        del self._receive_buffer[:parseable_length]

        return list(Packet.parse(parseable_data))

    def data_received(self, data: bytes) -> None:
        """Called when data has been received from the socket"""
        _LOGGER.debug("Aprilaire data received %s", data.hex(" "))

        try:
            parsed_packets = self._parse_received_data(data)
        except Exception:
            # asyncio's transport closes the connection on any exception
            # escaping data_received, so nothing may propagate out of here.
            _LOGGER.exception("Failed to parse received data")
            return

        for packet in parsed_packets:
            if isinstance(packet, NackPacket):
                self._handle_nack(packet)
                continue

            # A non-NACK response means the request sharing its sequence
            # number succeeded.
            self._in_flight_requests.pop(packet.sequence, None)

            if (
                packet.action == Action.COS
                and packet.functional_domain == FunctionalDomain.CONTROL
                and packet.attribute == 1
                and packet.data.get(Attribute.MODE) == 1
            ):
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

    def _handle_nack(self, packet: NackPacket) -> None:
        """Handle a NACK per spec section H.5's "Action in Case of NACK"
        column.

        Decodes `packet.status_code` into a `NackStatus`, retries the request
        if the spec calls for it, and otherwise fails that request's
        `wait_for_response` future rather than letting it time out.
        """
        raw_status = packet.status_code

        try:
            status = NackStatus(raw_status)
        except ValueError:
            status = None

        in_flight = self._in_flight_requests.pop(packet.sequence, None)

        if in_flight is not None:
            original_packet, retry_count = in_flight

            if status in RETRYABLE_NACK_STATUSES and retry_count < MAX_NACK_RETRIES:
                _LOGGER.error(
                    "Received NACK: %s, sequence=%d - retrying (%d/%d)",
                    status.name,
                    packet.sequence,
                    retry_count + 1,
                    MAX_NACK_RETRIES,
                )

                self._in_flight_requests[packet.sequence] = (
                    original_packet,
                    retry_count + 1,
                )

                asyncio.ensure_future(self._retry_packet(original_packet))
                return

        _LOGGER.error(
            "Received NACK: %s, sequence=%d",
            status.name if status is not None else f"unknown status 0x{raw_status:02X}",
            packet.sequence,
        )

        if in_flight is None or not self.data_received_callback:
            return

        original_packet, _ = in_flight

        # `AprilaireClient.data_received` recognizes this `NackError` and
        # fails the pending future rather than reporting it as response data.
        asyncio.ensure_future(
            self.data_received_callback(
                original_packet.functional_domain,
                original_packet.attribute,
                NackError(status, raw_status),
                packet.sequence,
            )
        )

    async def _retry_packet(self, packet: Packet) -> None:
        """Retry a NACKed packet per spec section H.5.

        Spec section F note 3: "Retries of a packet will use the same
        sequence number as the initial packet", so the packet is re-queued
        as-is rather than going through `_send_packet`.
        """
        await asyncio.sleep(random.uniform(*NACK_RETRY_DELAY_RANGE))
        await self.packet_queue.put(packet)

    def connection_lost(self, exc: Exception | None) -> None:
        """Called when the connection to the socket has been lost"""
        if self.data_received_callback:
            asyncio.ensure_future(
                self.data_received_callback(
                    FunctionalDomain.NONE, 0, {Attribute.AVAILABLE: False}, None
                )
            )

        self.transport = None

        self._receive_buffer = bytearray()

        if self.reconnect_action:
            asyncio.ensure_future(self.reconnect_action())

    async def read_sensors(self):
        """Send a request for the controlling sensor values (spec 5.2)"""
        return await self._send_packet(
            Packet(Action.READ_REQUEST, FunctionalDomain.SENSORS, 2)
        )

    async def read_sensor_values(self):
        """Send a request for the full sensor values array (spec 5.1)"""
        return await self._send_packet(
            Packet(Action.READ_REQUEST, FunctionalDomain.SENSORS, 1)
        )

    async def read_written_outdoor_temperature(self):
        """Send a request for the written outdoor temperature value (spec 5.4)"""
        return await self._send_packet(
            Packet(Action.READ_REQUEST, FunctionalDomain.SENSORS, 4)
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

    async def read_cos_subscriptions(self):
        """Send a request to read the current COS subscription settings
        (spec 7.1), returning the sequence number it was sent with"""
        return await self._send_packet(
            Packet(Action.READ_REQUEST, FunctionalDomain.STATUS, 1)
        )

    async def write_cos_subscriptions(self, subscriptions: dict[Attribute, int]):
        """Write the COS subscription mask (spec 7.1).

        `subscriptions` supplies the value for each of the 28 named channels,
        laid out in the wire order of `COS_SUBSCRIPTIONS`. Byte 21 is
        Reserved and is emitted as a placeholder `0`.
        """
        raw_data = [
            0 if attribute is None else subscriptions[attribute]
            for attribute, _default in COS_SUBSCRIPTIONS
        ]

        await self._send_packet(
            Packet(
                Action.WRITE,
                FunctionalDomain.STATUS,
                1,
                raw_data=raw_data,
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

    async def set_written_outdoor_temperature_value(self, value: float):
        """Send a request to update the written outdoor temperature value
        (spec 5.4).

        `value` is degrees Celsius and may carry a half degree; it is packed
        by `Packet._encode_temperature`, so callers shouldn't pre-round it.
        Spec 5.4 requires the status byte of a write to be 0.
        """
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
        reconnect_interval: int | None = None,
        retry_connection_interval: int | None = None,
    ) -> None:
        self.protocol: _AprilaireClientProtocol | None = None

        super().__init__(
            host,
            port,
            data_received_callback,
            reconnect_interval,
            retry_connection_interval,
        )

        # Each entry pairs a waiter's future with the sequence number (spec
        # section F notes 2-3) of the request it is waiting on, or None to
        # match on (functional_domain, attribute) alone.
        self.futures: dict[AttributeKey, list[tuple[asyncio.Future, int | None]]] = {}

        # Attributes this thermostat has proved it doesn't implement, mapped
        # to the terminal NACK that proved it. Held here rather than on the
        # protocol, which is rebuilt on every reconnect.
        self.unsupported_attributes: dict[AttributeKey, NackError] = {}

        # The last availability reported for each key of
        # `AVAILABILITY_ATTRIBUTES`, so it is pushed only on a change.
        self._reported_availability: dict[AttributeKey, bool] = {}

    async def _reconnect_with_delay(self):
        """Reconnect after a lost connection.

        Wired in as the protocol's `reconnect_action`. Only a real
        disconnect is logged, not the periodic reconnect of
        `SocketClient._auto_reconnect_loop`, which sets `auto_reconnecting`.
        """
        if not self.auto_reconnecting:
            _LOGGER.info("Aprilaire connection lost")

        await super()._reconnect(self.retry_connection_interval)

    def create_protocol(self):
        return _AprilaireClientProtocol(
            self.data_received,
            self._reconnect_with_delay,
            self.connection_made,
        )

    async def connection_made(self):
        """Called when a connection to the thermostat has been made.

        Fired by `_AprilaireClientProtocol.connection_made` as its
        `connected_action`.
        """
        await self._update_status()

    async def _update_status(self):
        """Bring this client's view of the thermostat up to date on a fresh
        connection, per spec Appendix J's Best Practices.

        Runs from `connection_made`, so it happens once per connection -
        including each hourly reconnect.
        """
        await asyncio.sleep(2)

        await self.read_mac_address()
        await self.read_thermostat_status()
        await self.read_iaq_status()  # spec Appendix J.13
        await self.read_control()
        await self.read_thermostat_iaq_available()  # spec Appendix J.4
        await self.read_sensors()

        # Model-dependent (see `AVAILABILITY_ATTRIBUTES`); checking rather
        # than catching keeps an unsupported model from aborting the rest.
        if self.is_attribute_supported(FunctionalDomain.SENSORS, 1):
            await self.read_sensor_values()

        if self.is_attribute_supported(FunctionalDomain.SENSORS, 4):
            await self.read_written_outdoor_temperature()

        await self.read_thermostat_name()
        await self.read_scheduling()  # spec Appendix J.11
        await self.configure_cos()
        await self.read_dehumidification_setpoint()
        await self.read_humidification_setpoint()
        await self.sync()

    async def data_received(
        self,
        functional_domain: FunctionalDomain,
        attribute: int,
        data: dict[str, Any] | NackError,
        sequence: int | None = None,
    ):
        """Called when data is received from the thermostat"""

        # A `NackError` fails a matching future below rather than being
        # reported as response data to the user-supplied callback.
        is_nack_error = isinstance(data, NackError)

        if is_nack_error:
            # The call that discovers the attribute is missing must raise
            # the same type as every call after it.
            data = self._record_unsupported_attribute(
                functional_domain, attribute, data
            )
        else:
            # Anything coming back for one of these attributes, response or
            # COS, proves the thermostat implements it.
            self._set_availability(functional_domain, attribute, True)

            self.data_received_callback(data)

        # `FunctionalDomain.NONE` and attribute 0 are both real values, so
        # only their complete absence skips future resolution.
        if functional_domain is None or attribute is None:
            return

        future_key = (functional_domain, attribute)

        pending_entries = self.futures.pop(future_key, [])

        unresolved_entries = []

        for future, expected_sequence in pending_entries:
            # A future carrying an expected sequence number is pinned to the
            # one request that created it, so an unsolicited COS (spec
            # section H.4, sequence 128-255 per section F note 1) cannot
            # resolve a wait meant for a read response.
            if expected_sequence is not None and expected_sequence != sequence:
                unresolved_entries.append((future, expected_sequence))
                continue

            try:
                if is_nack_error:
                    future.set_exception(data)
                else:
                    future.set_result(data)
            except asyncio.InvalidStateError:
                pass

        if unresolved_entries:
            self.futures[future_key] = unresolved_entries

    def _record_unsupported_attribute(
        self,
        functional_domain: FunctionalDomain,
        attribute: int,
        nack_error: NackError,
    ) -> NackError:
        """Remember an attribute a terminal NACK proved this device doesn't
        implement, so it is never requested again.

        Only the statuses in `UNSUPPORTED_NACK_STATUSES` say anything about
        the device; every other NACK is ignored here.

        Returns the error that should fail this request's pending
        `wait_for_response`: `nack_error` unchanged, or an
        `UnsupportedAttributeError` when this NACK is the one that proved the
        attribute unsupported.
        """
        if nack_error.status not in UNSUPPORTED_NACK_STATUSES:
            return nack_error

        key = (functional_domain, attribute)

        unsupported_error = UnsupportedAttributeError(
            nack_error.status, nack_error.raw_status
        )

        self.unsupported_attributes[key] = unsupported_error

        self._set_availability(functional_domain, attribute, False)

        return unsupported_error

    def _set_availability(
        self,
        functional_domain: FunctionalDomain,
        attribute: int,
        available: bool,
    ) -> None:
        """Report whether a model-dependent attribute is available, if that
        has changed since it was last reported.

        A no-op for anything outside `AVAILABILITY_ATTRIBUTES`. Nothing is
        reported until the thermostat has answered, so a consumer has no key
        at all while support is unknown, as distinct from a `False`.
        """
        availability_attribute = AVAILABILITY_ATTRIBUTES.get(
            (functional_domain, attribute)
        )

        if availability_attribute is None:
            return

        key = (functional_domain, attribute)

        if self._reported_availability.get(key) == available:
            return

        self._reported_availability[key] = available

        self.data_received_callback({availability_attribute: available})

    def is_attribute_supported(
        self, functional_domain: FunctionalDomain, attribute: int
    ) -> bool:
        """Whether this thermostat may still be sent requests for an
        attribute.

        `False` only once a terminal NACK has proved it isn't implemented;
        an attribute that has never been requested is optimistically `True`.
        """
        return (functional_domain, attribute) not in self.unsupported_attributes

    def _raise_if_unsupported(
        self, functional_domain: FunctionalDomain, attribute: int
    ) -> None:
        """Raise rather than send a request this device has already refused.

        The raised `UnsupportedAttributeError` carries the status of the NACK
        that originally proved the attribute unsupported.
        """
        nack_error = self.unsupported_attributes.get((functional_domain, attribute))

        if nack_error is None:
            return

        raise UnsupportedAttributeError(nack_error.status, nack_error.raw_status)

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

        try:
            await self.start_listen_once()

            await self.read_mac_address_and_wait(5)
        finally:
            # The device accepts only one home automation connection at a
            # time (see the README), so every exit path must close this one.
            self.stop_listen()

    async def wait_for_response(
        self,
        functional_domain: FunctionalDomain,
        attribute: int,
        timeout: int | None = None,
        sequence: int | None = None,
    ):
        """Wait for a response for a particular request.

        With `sequence`, the wait resolves only for a response or NACK
        carrying that exact sequence number; the `read_*_and_wait` methods
        pass the value their own send returned. Without it, the wait resolves
        on the next response for `(functional_domain, attribute)` whatever
        caused it, including an unsolicited COS (spec section H.4).

        Returns the response data, or raises `ResponseTimeoutError` if none
        arrived within `timeout` and `NackError` if the request was
        terminally NACKed.
        """

        loop = asyncio.get_running_loop()
        future = loop.create_future()

        future_key = (functional_domain, attribute)

        entry = (future, sequence)

        self.futures.setdefault(future_key, []).append(entry)

        try:
            return await asyncio.wait_for(future, timeout)
        except TimeoutError as exc:
            # Not logged: only the caller knows whether a missed response
            # matters. A `NackError` propagates from the future as-is and is
            # logged by `_AprilaireClientProtocol._handle_nack`.
            raise ResponseTimeoutError(functional_domain, attribute, timeout) from exc
        finally:
            # data_received only pops entries a response resolves, so a
            # timed-out or cancelled wait has to clean up after itself.
            pending_entries = self.futures.get(future_key)

            if pending_entries is not None:
                try:
                    pending_entries.remove(entry)
                except ValueError:
                    pass

                if not pending_entries:
                    self.futures.pop(future_key, None)

    async def read_sensors(self):
        """Send a request for the controlling sensor values (spec 5.2)"""
        return await self.protocol.read_sensors()

    async def read_sensors_and_wait(self, timeout: int | None = None):
        """Send a request for the controlling sensor values (spec 5.2) and
        wait for the response"""
        sequence = await self.read_sensors()
        return await self.wait_for_response(
            FunctionalDomain.SENSORS, 2, timeout, sequence=sequence
        )

    async def read_sensor_values(self):
        """Send a request for the full sensor values array (spec 5.1).

        The only source for the non-controlling sensors (notably RAT and LAT)
        and the per-sensor installed status. Spec 5.1 is not COS-capable, so
        a consumer wanting updates has to call this again.

        Raises `UnsupportedAttributeError` on a model that has already
        refused it; see `is_attribute_supported`.
        """
        self._raise_if_unsupported(FunctionalDomain.SENSORS, 1)

        return await self.protocol.read_sensor_values()

    async def read_sensor_values_and_wait(self, timeout: int | None = None):
        """Send a request for the full sensor values array (spec 5.1) and
        wait for the response"""
        sequence = await self.read_sensor_values()
        return await self.wait_for_response(
            FunctionalDomain.SENSORS, 1, timeout, sequence=sequence
        )

    async def read_written_outdoor_temperature(self):
        """Send a request for the written outdoor temperature value (spec 5.4).

        Worth reading on connect as well as after a write, since the status
        byte is how a previously written value is reported as stale.

        Raises `UnsupportedAttributeError` on a model that has already
        refused it; see `is_attribute_supported`.
        """
        self._raise_if_unsupported(FunctionalDomain.SENSORS, 4)

        return await self.protocol.read_written_outdoor_temperature()

    async def read_written_outdoor_temperature_and_wait(
        self, timeout: int | None = None
    ):
        """Send a request for the written outdoor temperature value
        (spec 5.4) and wait for the response"""
        sequence = await self.read_written_outdoor_temperature()
        return await self.wait_for_response(
            FunctionalDomain.SENSORS, 4, timeout, sequence=sequence
        )

    async def read_control(self):
        """Send a request for updated control data"""
        return await self.protocol.read_control()

    async def read_control_and_wait(self, timeout: int | None = None):
        """Send a request for updated control data and wait for the response"""
        sequence = await self.read_control()
        return await self.wait_for_response(
            FunctionalDomain.CONTROL, 1, timeout, sequence=sequence
        )

    async def read_scheduling(self):
        """Send a request for updated scheduling data"""
        return await self.protocol.read_scheduling()

    async def read_scheduling_and_wait(self, timeout: int | None = None):
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

    async def read_mac_address_and_wait(self, timeout: int | None = None):
        """Send a request to read the MAC address and wait for the response"""
        sequence = await self.read_mac_address()
        return await self.wait_for_response(
            FunctionalDomain.IDENTIFICATION, 2, timeout, sequence=sequence
        )

    async def read_thermostat_name(self):
        """Send a request to read the thermostat name"""
        return await self.protocol.read_thermostat_name()

    async def read_thermostat_name_and_wait(self, timeout: int | None = None):
        """Send a request to read the thermostat name and wait for the response"""
        sequence = await self.read_thermostat_name()
        return await self.wait_for_response(
            FunctionalDomain.IDENTIFICATION, 5, timeout, sequence=sequence
        )

    async def read_dehumidification_setpoint(self):
        """Send a request for the dehumidification setpoint"""
        await self.protocol.read_dehumidification_setpoint()

    async def read_humidification_setpoint(self):
        """Send a request for the humidification setpoint"""
        await self.protocol.read_humidification_setpoint()

    async def set_dehumidification_setpoint(self, dehumidification_setpoint: int):
        await self.protocol.set_dehumidification_setpoint(dehumidification_setpoint)

    async def set_humidification_setpoint(self, humidification_setpoint: int):
        await self.protocol.set_humidification_setpoint(humidification_setpoint)

    async def set_fresh_air(self, mode: int, event: int):
        await self.protocol.set_fresh_air(mode, event)

    async def set_air_cleaning(self, mode: int, event: int):
        await self.protocol.set_air_cleaning(mode, event)

    async def set_written_outdoor_temperature_value(self, value: float):
        """Send a request to update the written outdoor temperature value
        (spec 5.4), then read back what the thermostat actually stored.

        `value` is degrees Celsius and may carry a half degree; it is packed
        by `Packet._encode_temperature`, so callers shouldn't pre-round it.
        Spec 5.4 wants this refreshed more often than every ten minutes, or
        the thermostat marks the value stale.

        Raises `UnsupportedAttributeError` on a model that has already
        refused this attribute, for a read or a write alike.
        """
        self._raise_if_unsupported(FunctionalDomain.SENSORS, 4)

        await self.protocol.set_written_outdoor_temperature_value(value)

        await self.read_written_outdoor_temperature()

    async def read_thermostat_iaq_available(self):
        """Send a request to read the thermostat/IAQ available data"""
        return await self.protocol.read_thermostat_iaq_available()

    async def read_thermostat_iaq_available_and_wait(self, timeout: int | None = None):
        """Send a request to read the thermostat/IAQ available data and wait
        for the response"""
        sequence = await self.read_thermostat_iaq_available()
        return await self.wait_for_response(
            FunctionalDomain.CONTROL, 7, timeout, sequence=sequence
        )

    async def read_thermostat_status(self):
        """Send a request to read the thermostat status"""
        return await self.protocol.read_thermostat_status()

    async def read_thermostat_status_and_wait(self, timeout: int | None = None):
        """Send a request to read the thermostat status and wait for the
        response"""
        sequence = await self.read_thermostat_status()
        return await self.wait_for_response(
            FunctionalDomain.STATUS, 6, timeout, sequence=sequence
        )

    async def read_iaq_status(self):
        """Send a request to read the IAQ status"""
        return await self.protocol.read_iaq_status()

    async def read_iaq_status_and_wait(self, timeout: int | None = None):
        """Send a request to read the IAQ status and wait for the response"""
        sequence = await self.read_iaq_status()
        return await self.wait_for_response(
            FunctionalDomain.STATUS, 7, timeout, sequence=sequence
        )

    async def read_cos_subscriptions(self):
        """Send a request to read the current COS subscription settings (spec 7.1)"""
        return await self.protocol.read_cos_subscriptions()

    async def read_cos_subscriptions_and_wait(self, timeout: int | None = None):
        """Send a request to read the current COS subscription settings
        (spec 7.1) and wait for the response"""
        sequence = await self.read_cos_subscriptions()
        return await self.wait_for_response(
            FunctionalDomain.STATUS, 1, timeout, sequence=sequence
        )

    async def configure_cos(self, overrides: dict[Attribute, int] | None = None):
        """Configure which COS subscriptions (spec 7.1) the thermostat sends.

        Reads the current mask first, per spec Appendix J.1, and writes only
        when the desired mask differs from what the thermostat reports. If
        the read times out the current mask is unknown, so the desired one is
        written unconditionally.

        `overrides` adjusts individual channels away from
        `DEFAULT_COS_SUBSCRIPTIONS`. Byte 21 is Reserved and is never part of
        the desired mask, so it can't be set here.
        """
        desired = dict(DEFAULT_COS_SUBSCRIPTIONS)

        if overrides:
            desired.update(
                {
                    attribute: value
                    for attribute, value in overrides.items()
                    if attribute in desired
                }
            )

        try:
            current = await self.read_cos_subscriptions_and_wait(
                COS_SUBSCRIPTIONS_READ_TIMEOUT
            )
        except ResponseTimeoutError:
            # With the current mask unknown, this falls through to writing
            # the desired one unconditionally.
            current = None

        if current is not None and all(
            current.get(attribute) == value for attribute, value in desired.items()
        ):
            return

        await self.protocol.write_cos_subscriptions(desired)
