"""Client for interfacing with the thermostat"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

from .const import QUEUE_FREQUENCY, Action, Attribute, FunctionalDomain, NackStatus
from .packet import NackPacket, Packet
from .socket_client import SocketClient

_LOGGER = logging.getLogger(__name__)

# Spec section F: CNT is 2 bytes (0-65535), so a complete frame is at most
# CNT + 5 (REV, SEQ, CNT high/low, PAYLOAD, CRC) bytes. A receive buffer that
# grows past this without ever containing a single complete frame can only be
# a peer that isn't going to complete one (garbage on the wire, or a stalled
# connection) - cap it there so such a peer can't grow the buffer forever.
MAX_BUFFER_SIZE = 65535 + 5

# Spec section H.5 "Action in Case of NACK": these three status codes are the
# only ones with an action of "Retry 2 additional times with 0.5 to 1 second
# delay between retries and then clear the transaction from the queue."
# Every other status code's action is just "Clear the transaction from the
# queue" - i.e. give up immediately.
RETRYABLE_NACK_STATUSES = frozenset(
    {
        NackStatus.GENERIC_ERROR,
        NackStatus.BUFFER_FULL_OR_DEVICE_BUSY,
        NackStatus.TIMED_OUT_WAITING_FOR_RESPONSE,
    }
)

# Spec section H.5: "Retry 2 additional times" - i.e. up to 2 retries beyond
# the original attempt (3 attempts total).
MAX_NACK_RETRIES = 2

# Spec section H.5: "0.5 to 1 second delay between retries".
NACK_RETRY_DELAY_RANGE = (0.5, 1.0)

# The NACK status codes that mean a request will *never* succeed against this
# particular device, as opposed to having failed this once. Only these three
# say something about the device rather than about the request:
#
#   UNKNOWN_FUNCTIONAL_DOMAIN / UNKNOWN_ATTRIBUTE - the device's firmware has
#     no such domain/attribute at all.
#   UNSUPPORTED_MODEL - spec section H.5's own code for an attribute this
#     model doesn't implement, even though the protocol defines it. This is
#     what a thermostat without RAT/LAT sensors or written outdoor
#     temperature support answers with.
#
# `AprilaireClient` remembers these (see its `unsupported_attributes`) and
# stops re-requesting the attribute. Everything else is deliberately left
# out, because caching it would disable a working attribute:
#
#   ATTRIBUTE_NOT_AVAILABLE_TRY_LATER - explicitly temporary.
#   ATTRIBUTE_READ_ONLY / ATTRIBUTE_NOT_READABLE /
#     ATTRIBUTE_NOT_WRITEABLE_IN_CURRENT_CONFIGURATION - direction- or
#     configuration-specific. Reads and writes of one attribute share a
#     cache key, so a write refused as read-only must not be taken to mean
#     the attribute can't be read either.
#   VALUE_OUT_OF_RANGE / INCORRECT_WRITE_DATA_LENGTH /
#     INCORRECT_READ_DATA_LENGTH - a complaint about this one request's
#     contents; the same attribute with different data may well be fine.
#   The RETRYABLE_NACK_STATUSES above - transient by definition, and already
#     retried before any NackError surfaces.
UNSUPPORTED_NACK_STATUSES = frozenset(
    {
        NackStatus.UNKNOWN_FUNCTIONAL_DOMAIN,
        NackStatus.UNKNOWN_ATTRIBUTE,
        NackStatus.UNSUPPORTED_MODEL,
    }
)


class AprilaireResponseError(Exception):
    """Base class for a request failing to produce response data.

    A caller that only needs to know it has no data can catch this; the
    subclasses say why, which is what decides whether trying again is
    worth anything:

      `ResponseTimeoutError` - nothing came back in time. The request may
        well succeed on a later attempt; the thermostat never said
        otherwise.
      `NackError` - the thermostat explicitly rejected the request, and
        permanently: the status codes the spec calls for retrying are
        already retried before this surfaces.
    """


class NackError(AprilaireResponseError):
    """Raised to fail a `wait_for_response` future for a terminally-NACKed
    request.

    Per spec section H.5, most NACK status codes mean the transaction is
    simply cleared from the queue - the request has permanently failed and
    will not be retried. The three codes that are retried
    (`RETRYABLE_NACK_STATUSES`) only raise this once those retries are
    exhausted. See `_AprilaireClientProtocol._handle_nack`.
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

    Once a terminal NACK with one of `UNSUPPORTED_NACK_STATUSES` has proved
    the thermostat doesn't implement an attribute, re-requesting it can only
    produce the same NACK again - once per connection, forever, since
    `_update_status` runs on every hourly reconnect. `AprilaireClient`
    remembers those attributes and raises this instead of putting the
    request on the wire.

    The NACK that proves the point raises this as well, rather than a plain
    `NackError`: the attribute is just as unsupported on the call that
    discovers it as on every call after, so catching this type must not
    depend on whether the answer came from the device or from the cache.

    It subclasses `NackError`, carrying the status of the NACK behind it,
    because it *is* that same failure. A caller handling `NackError`
    therefore needs no changes. Note this is a distinct type from
    `ResponseTimeoutError` rather than the same "no data" signal: a
    timed-out request may still succeed on a retry, an unsupported one
    never will.
    """


class ResponseTimeoutError(AprilaireResponseError):
    """Raised when no response arrived for a request before its timeout.

    This is a failure to hear back, not a refusal - the thermostat may
    simply be slow, or the socket may have silently stalled (see the
    README on this device's connection behaviour), so the same request may
    succeed on a later attempt. Contrast `NackError`, which is the device
    explicitly and permanently rejecting the request.

    Deliberately *not* a subclass of `asyncio.TimeoutError`: that name is
    two different classes depending on the Python version - the builtin
    `TimeoutError` (itself an `OSError`) from 3.11 on, and a plain
    `Exception` subclass before that - so inheriting it would give this
    error a lineage that changes under the caller's feet, and on 3.11+
    would quietly put a protocol-level timeout inside every `except
    OSError` meant for socket failures.
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
# giving up and falling back to writing the desired mask unconditionally.
# Matches the timeout AprilaireClient.test_connection() uses for a similar
# single read/response round trip.
COS_SUBSCRIPTIONS_READ_TIMEOUT = 5

# Spec 7.1: the 29 COS Subscription bytes, in wire order, paired with this
# library's desired subscription value for each.
#
# Per spec Appendix J.1: "All COS subscription outputs are enabled by
# default, but can be disabled if unused to reduce network traffic."
# Unlike the device's own all-enabled default, this library only enables a
# channel it actually has a reason to want: either a `read_*`/`set_*`
# method that consumes the resulting attribute, or one of spec Appendix
# J's Best Practices items naming a channel as the *only* source for
# information this library aims to support (even before a dedicated read
# method exists for it). Every other channel defaults to off; a caller
# that wants one anyway can turn it back on via the `overrides` argument
# to `AprilaireClient.configure_cos`.
#
# Notes on specific bytes:
#   0-4   Installer settings (thermostat, contractor, air cleaning,
#         humidity control, fresh air) - disabled, nothing in this
#         library reads them.
#   5-9   Setpoint/mode, dehumidification, humidification, fresh air, and
#         air cleaning settings back update_mode()/update_fan_mode()/
#         update_setpoint()/set_dehumidification_setpoint()/
#         set_humidification_setpoint()/set_fresh_air()/set_air_cleaning().
#   10    Backs read_thermostat_iaq_available().
#   11    Schedule Settings - without this, set_hold()/read_scheduling()
#         are never told whether the user enabled/disabled the onboard
#         schedule at the thermostat.
#   12    Away Settings - disabled. Its data lives at SCHEDULING/2, which
#         has no packet.py MAPPING entry yet, so enabling this channel
#         would only make the thermostat send packets that
#         Packet.parse silently drops before they ever reach a callback
#         (see its unmapped functional_domain/attribute handling) - pure
#         wasted traffic today, not just an unused one.
#   13    Schedule Day - disabled, nothing in this library reads it.
#   14    Schedule Hold backs set_hold()/read_scheduling().
#   15    Heat Blast - disabled, nothing in this library reads it.
#   16    Service Reminders Status - spec J.18: the only channel to
#         monitor service reminder status. Kept on despite no dedicated
#         read method, since a consuming app has no other way to ever
#         see this data (spec Appendix J Best Practices item).
#   17-18 Alerts Status/Settings - spec J.19: the only channel for hi/lo
#         temperature and RH alerts. Same reasoning as 16.
#   19    Backlight Settings - disabled, nothing in this library reads it.
#   20    Thermostat Location & Name backs read_thermostat_name().
#   21    Reserved - spec 7.1 defines no semantics for this byte. Paired
#         with `None` instead of an Attribute: it never enters the
#         current-vs-desired comparison in
#         `AprilaireClient.configure_cos`, and the 0
#         below is only ever sent as a structurally-required placeholder
#         byte on a write triggered by some other channel's mismatch -
#         never because byte 21 itself was judged wrong.
#   22    Controlling Sensor Values backs read_sensors().
#   23    Over the air ODT update timeout - spec J.15: the only
#         notification that a written ODT
#         (set_written_outdoor_temperature_value()) is more than 10
#         minutes stale. Same reasoning as 16.
#   24-25 Thermostat/IAQ Status back read_thermostat_status()/
#         read_iaq_status().
#   26    Model & Revision - disabled, nothing in this library reads it.
#   27    Support Module - disabled; support module reads are out of
#         scope for this library.
#   28    Lockouts - disabled, nothing in this library reads it.
COS_SUBSCRIPTIONS = [
    (Attribute.COS_INSTALLER_THERMOSTAT_SETTINGS, 0),  # 0 Installer Thermostat Settings
    (Attribute.COS_CONTRACTOR_INFORMATION, 0),  # 1 Contractor Information
    (
        Attribute.COS_AIR_CLEANING_INSTALLER_SETTINGS,
        0,
    ),  # 2 Air Cleaning Installer Variable
    (
        Attribute.COS_HUMIDITY_CONTROL_INSTALLER_SETTINGS,
        0,
    ),  # 3 Humidity Control Installer Settings
    (Attribute.COS_FRESH_AIR_INSTALLER_SETTINGS, 0),  # 4 Fresh Air Installer Settings
    (
        Attribute.COS_THERMOSTAT_SETPOINT_AND_MODE_SETTINGS,
        1,
    ),  # 5 Thermostat Setpoint & Mode Settings
    (Attribute.COS_DEHUMIDIFICATION_SETPOINT, 1),  # 6 Dehumidification Setpoint
    (Attribute.COS_HUMIDIFICATION_SETPOINT, 1),  # 7 Humidification Setpoint
    (Attribute.COS_FRESH_AIR_SETTING, 1),  # 8 Fresh Air Setting
    (Attribute.COS_AIR_CLEANING_SETTINGS, 1),  # 9 Air Cleaning Settings
    (Attribute.COS_THERMOSTAT_IAQ_AVAILABLE, 1),  # 10 Thermostat IAQ Available
    (Attribute.COS_SCHEDULE_SETTINGS, 1),  # 11 Schedule Settings
    (Attribute.COS_AWAY_SETTINGS, 0),  # 12 Away Settings
    (Attribute.COS_SCHEDULE_DAY, 0),  # 13 Schedule Day
    (Attribute.COS_SCHEDULE_HOLD, 1),  # 14 Schedule Hold
    (Attribute.COS_HEAT_BLAST, 0),  # 15 Heat Blast
    (Attribute.COS_SERVICE_REMINDERS_STATUS, 1),  # 16 Service Reminders Status
    (Attribute.COS_ALERTS_STATUS, 1),  # 17 Alerts Status
    (Attribute.COS_ALERTS_SETTINGS, 1),  # 18 Alerts Settings
    (Attribute.COS_BACKLIGHT_SETTINGS, 0),  # 19 Backlight Settings
    (Attribute.COS_THERMOSTAT_LOCATION_AND_NAME, 1),  # 20 Thermostat Location & Name
    (None, 0),  # 21 Reserved
    (Attribute.COS_CONTROLLING_SENSOR_VALUES, 1),  # 22 Controlling Sensor Values
    (
        Attribute.COS_OVER_THE_AIR_ODT_UPDATE_TIMEOUT,
        1,
    ),  # 23 Over the air ODT update timeout
    (Attribute.COS_THERMOSTAT_STATUS, 1),  # 24 Thermostat Status
    (Attribute.COS_IAQ_STATUS, 1),  # 25 IAQ Status
    (Attribute.COS_MODEL_AND_REVISION, 0),  # 26 Model & Revision
    (Attribute.COS_SUPPORT_MODULE, 0),  # 27 Support Module
    (Attribute.COS_LOCKOUTS, 0),  # 28 Lockouts
]

# The desired mask as a dict, for comparing against a read current mask and
# for seeding the `overrides` merge in `AprilaireClient.configure_cos`.
# Excludes byte 21 (Reserved has no Attribute) so it can never be looked up
# or overridden.
DEFAULT_COS_SUBSCRIPTIONS: dict[Attribute, int] = {
    attribute: value for attribute, value in COS_SUBSCRIPTIONS if attribute is not None
}

# Attributes whose support varies by thermostat model, paired with the
# attribute `AprilaireClient` reports their availability under. Not every
# model has RAT/LAT sensors (spec 5.1) or accepts a written outdoor
# temperature (spec 5.4); one that doesn't answers a read with a NACK rather
# than with data, so a consumer left waiting on the values alone can't tell
# an unsupported model from one that simply hasn't replied yet. See
# `AprilaireClient._set_availability`.
AVAILABILITY_ATTRIBUTES: dict[tuple[FunctionalDomain, int], Attribute] = {
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

        # Called once the socket is up and the send queue is running, so
        # the owning client can run whatever request sequence it wants on a
        # fresh connection (see AprilaireClient._update_status). The
        # counterpart to `reconnect_action`, which this class already fires
        # from `connection_lost`: deciding *which* requests a new
        # connection should make, and in what order, is client policy - all
        # this class knows is how to put a packet on the wire. `None` (as
        # for a caller that constructs this protocol directly, e.g. tests)
        # just means connecting only starts the queue loop.
        self.connected_action = connected_action

        self.transport: asyncio.Transport = None

        self.packet_queue = asyncio.Queue()

        self.sequence = 0

        # The most recently sent packet for each sequence number, paired
        # with how many times it has been retried in response to a NACK, so
        # that a NACK - which only carries the sequence number of the
        # request that caused it - can be attributed back to that request:
        # to retry it (spec section H.5; section F note 3 requires reusing
        # the original sequence number) and/or to know which
        # (functional_domain, attribute) key a terminal NACK should fail.
        # See `_handle_nack`.
        #
        # Bounded by sequence-number reuse: `_get_sequence` cycles sequence
        # numbers through 0-127, so sending a new request eventually
        # overwrites whatever was previously recorded here for that
        # sequence number, capping this dict at 128 entries. A successful
        # (non-NACK) response also pops its entry immediately, see
        # `data_received`.
        self._in_flight_requests: dict[int, tuple[Packet, int]] = {}

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

        # A reconnect must not inherit a partial frame left over from
        # whatever connection preceded this one.
        self._receive_buffer = bytearray()

        asyncio.ensure_future(self._queue_loop())

        if self.connected_action:
            asyncio.ensure_future(self.connected_action())

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
            # Whatever went wrong, it must not propagate out of this
            # callback: asyncio's transport treats any exception escaping
            # data_received as fatal and closes the connection (see
            # asyncio/selector_events.py's _read_ready__data_received).
            _LOGGER.exception("Failed to parse received data")
            return

        for packet in parsed_packets:
            if isinstance(packet, NackPacket):
                self._handle_nack(packet)
                continue

            # This packet is a genuine (non-NACK) response, so whatever
            # request shares its sequence number - if any - has succeeded.
            # See `_in_flight_requests`.
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

        `packet.status_code` is the raw STATUS CODE byte of the FUNCTIONAL
        DOMAIN / STATUS CODE field (spec section G). This is where it is
        turned into something meaningful: a `NackStatus`, used to decide
        whether to retry the request that caused it, and to fail that
        request's `wait_for_response` future promptly when it will not be
        retried (or when retries are exhausted) rather than leaving the
        caller to wait out its full timeout only to receive an unexplained
        `None`.
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

        # Fail the pending `wait_for_response` future (if any) for the
        # request this NACK terminally failed, rather than leaving it to
        # time out. `NackError` is only ever meant to reach
        # `AprilaireClient.data_received`, which recognizes it and calls
        # `future.set_exception` instead of `future.set_result` - it is
        # never handed to the user-supplied `data_received_callback` as if
        # it were response data.
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
        sequence number as the initial packet" - so `packet` (whose
        `.sequence` is already set from the original send) is re-queued
        as-is rather than going through `_send_packet`, which would
        allocate a new sequence number.
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

        # Don't let a frame that was only half-received on this connection
        # bleed into whatever gets received after a reconnect.
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

        `subscriptions` supplies the value for each of the 28 named
        channels; they are laid out in the wire order spec 7.1 defines
        (`COS_SUBSCRIPTIONS`). Byte 21 is Reserved - spec 7.1 defines no
        semantics for it - so it isn't part of `subscriptions` and is
        emitted as a structurally-required placeholder `0`.

        Whether a write is warranted at all is not this method's business;
        see `AprilaireClient.configure_cos`.
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

        `value` is degrees Celsius and may carry a half degree; it is passed
        through untouched, because `Packet._encode_temperature` is the single
        place that knows temperatures are quantized to half degrees. Rounding
        here as well would make this setter disagree with every other
        temperature write in the library about what, say, 21.3 means.

        Spec 5.4 requires the status byte of a write to be 0; the thermostat
        keeps reporting the real status on reads.
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
        reconnect_interval: int = None,
        retry_connection_interval: int = None,
    ) -> None:
        self.protocol: _AprilaireClientProtocol = None

        super().__init__(
            host,
            port,
            data_received_callback,
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

        # Attributes this thermostat has proved it doesn't implement, mapped
        # to the terminal NACK that proved it (see
        # `UNSUPPORTED_NACK_STATUSES`). Requesting one of these again can
        # only earn the same NACK, so the gated methods raise
        # `UnsupportedAttributeError` - built from the recorded NACK's own
        # status - instead of sending.
        #
        # This lives on the client rather than on the protocol because
        # `SocketClient._reconnect` builds a *new* protocol object for every
        # connection: a protocol-held cache would be discarded on each
        # hourly reconnect, which is precisely the repeated probing this
        # exists to stop. Which attributes a device supports is a property
        # of the device, so it outlives any one connection.
        self.unsupported_attributes: dict[tuple[FunctionalDomain, int], NackError] = {}

        # The last availability value reported through
        # `data_received_callback` for each key of `AVAILABILITY_ATTRIBUTES`,
        # so availability is pushed on a change rather than on every
        # response and COS for a supported attribute.
        self._reported_availability: dict[tuple[FunctionalDomain, int], bool] = {}

    async def _reconnect_with_delay(self):
        """Reconnect after a lost connection.

        Wired in as the protocol's `reconnect_action`, so this runs on every
        `connection_lost` - which is what makes it, rather than the protocol
        itself, the place that can tell a real disconnect from the periodic
        reconnect `SocketClient._auto_reconnect_loop` performs. Only the
        former is logged; the latter closes the transport on a timer while
        `auto_reconnecting` is set (it stays set for the whole reconnect,
        including the delay this call sleeps out), and a connect/disconnect
        pair logged every hour for a connection that was never down says
        nothing.
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

        The client-side counterpart to
        `_AprilaireClientProtocol.connection_made`, which fires this as its
        `connected_action` - the same pairing as the protocol's
        `data_received` and this class's. Everything a fresh connection
        should do hangs off here.
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

        # Both are model-dependent (see `AVAILABILITY_ATTRIBUTES`), so they
        # are asked for only until the thermostat says it doesn't have them.
        # Checking rather than catching keeps an unsupported model from
        # aborting the rest of this bootstrap.
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

        # A `NackError` means the request identified by `functional_domain`,
        # `attribute`, and `sequence` was terminally NACKed (see
        # `_AprilaireClientProtocol._handle_nack`) - it is only meant to
        # fail a matching `wait_for_response` future below, not to be
        # reported as response data to the user-supplied callback.
        is_nack_error = isinstance(data, NackError)

        if is_nack_error:
            # A NACK that proves the attribute unsupported fails this
            # request as `UnsupportedAttributeError` too, not just every
            # later one - otherwise the single call that discovers the
            # attribute is missing raises a different type from all the
            # calls after it, and a caller catching the subclass silently
            # misses the discovery.
            data = self._record_unsupported_attribute(
                functional_domain, attribute, data
            )
        else:
            # Anything at all coming back for one of these attributes - a
            # read response or an unsolicited COS - proves the thermostat
            # implements it.
            self._set_availability(functional_domain, attribute, True)

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
                if is_nack_error:
                    future.set_exception(data)
                else:
                    future.set_result(data)
            except asyncio.exceptions.InvalidStateError:
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
        the device; every other NACK is about this one request and leaves
        the attribute's support unknown, so it is logged by the protocol and
        otherwise ignored here.

        Returns the error that should fail this request's pending
        `wait_for_response`: `nack_error` unchanged, or an
        `UnsupportedAttributeError` carrying the same status when this NACK
        is the one that proved the attribute unsupported - so that the
        discovering call and every cached refusal after it raise the same
        type.
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

        Only the attributes named in `AVAILABILITY_ATTRIBUTES` are reported;
        for anything else this is a no-op. Nothing is reported until the
        thermostat has answered one way or the other, so a consumer that
        merges these dicts simply has no key yet while support is unknown -
        distinct from a definite `False`.
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

        `False` only once a terminal NACK has proved it isn't implemented
        (see `unsupported_attributes`); an attribute that has never been
        requested is optimistically `True`, since the only way to find out
        is to ask. Callers that would rather handle the failure than check
        first can just call the request method and catch
        `UnsupportedAttributeError`.
        """
        return (functional_domain, attribute) not in self.unsupported_attributes

    def _raise_if_unsupported(
        self, functional_domain: FunctionalDomain, attribute: int
    ) -> None:
        """Raise rather than send a request this device has already refused.

        The raised `UnsupportedAttributeError` carries the status of the
        NACK that originally proved the attribute unsupported, so a caller
        sees the same failure it would have seen from the device - just
        without the round trip.
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
            # The device only accepts one home automation connection at a
            # time (see the README), so this connection must be closed on
            # every exit path - a failed `start_listen_once`, a read
            # propagating an `AprilaireResponseError` (a NACK, or no
            # response before the timeout) out of `wait_for_response`, or
            # success - not just the success path. Otherwise this "test the
            # connection" helper would be exactly what leaks the single
            # connection slot. `stop_listen` tolerates being called when no
            # connection was ever established (`_disconnect` only closes a
            # transport that actually exists).
            self.stop_listen()

    async def wait_for_response(
        self,
        functional_domain: FunctionalDomain,
        attribute: int,
        timeout: int = None,
        sequence: int | None = None,
    ):
        """Wait for a response for a particular request.

        If `sequence` is given, this wait only resolves for a response (or
        NACK) carrying that exact sequence number - use this when the wait
        corresponds to a specific outgoing request (see
        `read_mac_address_and_wait` and its siblings, which pass the value
        their own send just returned; prefer those over calling this
        directly whenever there's a specific request to wait on). Passing
        a stale or otherwise wrong sequence number silently waits on the
        wrong request - there's no way for this method to detect that,
        since it has no way to tell "your" request apart from anyone
        else's.

        If `sequence` is omitted (the default, `None`), this resolves on
        the next response for `(functional_domain, attribute)` regardless
        of which request caused it - including an unsolicited COS (spec
        section H.4). Use this only when that's actually what's wanted
        (e.g. observing the next update to a value, not correlating a
        specific request's answer).

        Returns the response data, or raises `AprilaireResponseError` -
        `ResponseTimeoutError` if no response arrived within `timeout`,
        `NackError` if the request was terminally NACKed (a status code
        the spec doesn't call for retrying, per spec section H.5, or one
        that was retried and still NACKed after exhausting its retries).

        Both failures raise so that neither can be missed by a caller that
        forgets to check a return value: this method either produces
        response data or raises, and never hands back a value that isn't
        an answer. They stay separate types because the difference decides
        what a caller should do - a timeout may yet succeed on a retry,
        while a NACK will not - and share `AprilaireResponseError` for a
        caller that only cares that no data arrived.
        """

        loop = asyncio.get_event_loop()
        future = loop.create_future()

        future_key = (functional_domain, attribute)

        entry = (future, sequence)

        self.futures.setdefault(future_key, []).append(entry)

        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.exceptions.TimeoutError as exc:
            # Not logged: the raise reports the timeout to the caller with
            # the same detail a log line would carry, and only the caller
            # knows whether a missed response matters (a failed setup) or is
            # routine (a poll that will come round again). A `NackError`
            # isn't caught here at all - it propagates from the future
            # as-is. `_AprilaireClientProtocol._handle_nack` is what logs
            # that, and is its only record for the many requests this
            # library sends without waiting on a response.
            raise ResponseTimeoutError(functional_domain, attribute, timeout) from exc
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
        """Send a request for the controlling sensor values (spec 5.2)"""
        return await self.protocol.read_sensors()

    async def read_sensors_and_wait(self, timeout: int = None):
        """Send a request for the controlling sensor values (spec 5.2) and
        wait for the response"""
        sequence = await self.read_sensors()
        return await self.wait_for_response(
            FunctionalDomain.SENSORS, 2, timeout, sequence=sequence
        )

    async def read_sensor_values(self):
        """Send a request for the full sensor values array (spec 5.1).

        This is the only source for the sensors that aren't part of the
        controlling set - notably RAT and LAT - as well as the per-sensor
        status bytes saying which of them are installed at all.

        Spec 5.1 is not COS-capable, so the thermostat never volunteers an
        update: whatever cadence a consumer wants, it gets by calling this
        again. This library only reads it on connect.

        Raises `UnsupportedAttributeError` on a model that has already
        refused it; see `is_attribute_supported`.
        """
        self._raise_if_unsupported(FunctionalDomain.SENSORS, 1)

        return await self.protocol.read_sensor_values()

    async def read_sensor_values_and_wait(self, timeout: int = None):
        """Send a request for the full sensor values array (spec 5.1) and
        wait for the response"""
        sequence = await self.read_sensor_values()
        return await self.wait_for_response(
            FunctionalDomain.SENSORS, 1, timeout, sequence=sequence
        )

    async def read_written_outdoor_temperature(self):
        """Send a request for the written outdoor temperature value (spec 5.4).

        Worth reading on connect as well as after a write: the status byte
        is how the thermostat reports that a previously written value has
        gone stale, which a client that has just reconnected would otherwise
        have no way to notice.

        Raises `UnsupportedAttributeError` on a model that has already
        refused it; see `is_attribute_supported`.
        """
        self._raise_if_unsupported(FunctionalDomain.SENSORS, 4)

        return await self.protocol.read_written_outdoor_temperature()

    async def read_written_outdoor_temperature_and_wait(self, timeout: int = None):
        """Send a request for the written outdoor temperature value
        (spec 5.4) and wait for the response"""
        sequence = await self.read_written_outdoor_temperature()
        return await self.wait_for_response(
            FunctionalDomain.SENSORS, 4, timeout, sequence=sequence
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
        refused this attribute - in either direction, since the three
        statuses that get remembered (`UNSUPPORTED_NACK_STATUSES`) all mean
        the device has no such attribute at all rather than that it declined
        this particular request.

        The read-back is composed here rather than in the protocol - unlike
        `set_dehumidification_setpoint` and `set_humidification_setpoint`,
        which do it a layer down - so that it goes through
        `read_written_outdoor_temperature` and honours the same gate.
        """
        self._raise_if_unsupported(FunctionalDomain.SENSORS, 4)

        await self.protocol.set_written_outdoor_temperature_value(value)

        await self.read_written_outdoor_temperature()

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

    async def read_cos_subscriptions(self):
        """Send a request to read the current COS subscription settings (spec 7.1)"""
        return await self.protocol.read_cos_subscriptions()

    async def read_cos_subscriptions_and_wait(self, timeout: int = None):
        """Send a request to read the current COS subscription settings
        (spec 7.1) and wait for the response"""
        sequence = await self.read_cos_subscriptions()
        return await self.wait_for_response(
            FunctionalDomain.STATUS, 1, timeout, sequence=sequence
        )

    async def configure_cos(self, overrides: dict[Attribute, int] | None = None):
        """Configure which COS subscriptions (spec 7.1) the thermostat sends.

        Per spec Appendix J.1, the recommended sequence is: "Use the COS
        Subscriptions attribute to read the current COS subscription
        settings" and then, only "if it is desired to enable or [disable]
        specific COS messages", write the new settings. The mask is device
        configuration (spec 7.1 calls it read/write, not a one-shot
        command), so writing it unconditionally on every connect -
        including the hourly reconnect - means roughly 24 needless writes a
        day, and risks clobbering a mask some other tool set on purpose.
        This method reads first and only writes when the desired mask
        actually differs from what the thermostat reports.

        If the read times out, the current mask is unknown, so the desired
        one is written unconditionally rather than leaving the thermostat
        in a state this library can't work with.

        `overrides` lets a caller adjust individual channels away from this
        library's defaults (`DEFAULT_COS_SUBSCRIPTIONS`) - for example to
        enable a channel this library leaves off, or disable one it doesn't
        use to reduce network traffic, per spec Appendix J.1. Byte 21 is
        Reserved (spec 7.1 defines no semantics for it) and is never part
        of the desired mask, so it can't be set here.
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
            # Not an error here: with the current mask unknown, this falls
            # through to writing the desired one unconditionally, which is
            # the same thing it would do for a mask that doesn't match.
            current = None

        if current is not None and all(
            current.get(attribute) == value for attribute, value in desired.items()
        ):
            return

        await self.protocol.write_cos_subscriptions(desired)
