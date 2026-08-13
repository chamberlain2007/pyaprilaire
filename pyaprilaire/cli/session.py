"""Interactive session with a device

Everything that the interactive tools do to a device, and everything they
learn from it, goes through :class:`DebugSession`. It is deliberately free of
any user interface concerns so that the full screen and line based front ends
share exactly the same behavior.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..client import AprilaireClient, _AprilaireClientProtocol
from ..packet import Packet, attribute_name, split_packets
from .commands import ClientCommand, discover_client_commands, find_command
from .format import format_decimal, format_hex, hexdump

SENT = "sent"
RECEIVED = "received"
INFO = "info"
ERROR = "error"

DEFAULT_PORT = 7001


class SessionError(Exception):
    """An interactive command could not be carried out"""


@dataclass
class LogEntry:
    """Something that happened during the session"""

    kind: str
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    raw: bytes = None
    packets: list[Packet] = field(default_factory=list)
    remainder: bytes = b""

    @property
    def time_text(self) -> str:
        """The time of the entry, to millisecond precision"""
        return self.timestamp.strftime("%H:%M:%S.%f")[:-3]

    def to_dict(self) -> dict[str, Any]:
        """Convert the entry into a JSON serializable structure"""

        entry = {
            "timestamp": self.timestamp.isoformat(timespec="milliseconds"),
            "kind": self.kind,
            "message": self.message,
        }

        if self.raw is not None:
            entry["raw"] = format_hex(self.raw)

        if self.packets:
            entry["packets"] = [packet_to_dict(packet) for packet in self.packets]

        if self.remainder:
            entry["remainder"] = format_hex(self.remainder)

        return entry

    def to_json(self) -> str:
        """Convert the entry into a single line of JSON"""
        return json.dumps(self.to_dict(), default=str)


def _describe_packets(data: bytes) -> tuple[list[Packet], bytes]:
    """Describe every complete packet in a byte stream

    Nothing is discarded: a packet that the library can't act on, such as one
    for an undocumented attribute or with a bad checksum, is described as far
    as it can be. Whatever is left of an incomplete packet is returned so that
    it can be held until the rest of it arrives.
    """

    raw_packets, remainder = split_packets(data)

    packets = [
        packet for raw in raw_packets for packet in Packet.parse(raw, strict=False)
    ]

    return packets, remainder


def packet_to_dict(packet: Packet) -> dict[str, Any]:
    """Convert a packet into a JSON serializable structure"""

    return {
        "raw": format_hex(packet.raw),
        "revision": packet.revision,
        "sequence": packet.sequence,
        "count": packet.count,
        "action": packet.action,
        "action_name": packet.action_name,
        "functional_domain": packet.functional_domain,
        "functional_domain_name": packet.functional_domain_name,
        "attribute": packet.attribute,
        "nack_attribute": packet.nack_attribute,
        "payload": format_hex(packet.payload),
        "crc": packet.crc,
        "crc_valid": packet.crc_valid,
        "summary": packet.summary,
        "decoded": dict(packet.decoded),
        "error": packet.error,
    }


def format_entry_lines(entry: LogEntry, detail: bool = False) -> list[str]:
    """Render an entry as plain text lines

    The first line is a summary of the entry, and the remaining lines are
    indented details of each packet it contains.
    """

    prefix = {SENT: "-->", RECEIVED: "<--", ERROR: "!!!"}.get(entry.kind, "---")

    lines = [f"{entry.time_text} {prefix} {entry.message}"]

    for packet in entry.packets:
        lines.extend(f"      {line}" for line in format_packet_lines(packet, detail))

    if entry.remainder:
        lines.append(f"      incomplete packet: {format_hex(entry.remainder)}")

    return lines


def format_packet_lines(packet: Packet, detail: bool = False) -> list[str]:
    """Render a packet as plain text lines, in both hex and decoded form"""

    lines = [packet.summary]

    if detail:
        lines.extend(hexdump(packet.raw))
    else:
        lines.append(format_hex(packet.raw))

    crc_text = "?" if packet.crc is None else f"0x{packet.crc:02x}"

    lines.append(
        f"revision={packet.revision} sequence={packet.sequence}"
        f" length={packet.count} crc={crc_text}"
        f" ({'valid' if packet.crc_valid else 'INVALID'})"
    )

    if packet.error:
        lines.append(packet.error)

    decoded = packet.decoded

    for name, value in decoded:
        lines.append(f"{name} = {value}")

    if packet.payload and (detail or not decoded):
        lines.append(f"payload: {format_hex(packet.payload)}")
        lines.append(f"payload (decimal): {format_decimal(packet.payload)}")

    if not decoded and not packet.payload:
        lines.append("no payload")

    return lines


class _RecordingTransport:
    """A transport that reports everything written to it before writing

    Wrapping the transport means that every outgoing byte is captured on a
    single path, whether it came from a queued packet or was written raw.
    """

    def __init__(
        self, transport: asyncio.Transport, on_write: Callable[[bytes], None]
    ) -> None:
        self._transport = transport
        self._on_write = on_write

    def write(self, data: bytes) -> None:
        """Report and write data to the underlying transport"""
        self._on_write(bytes(data))
        self._transport.write(data)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._transport, name)


class _DebugProtocol(_AprilaireClientProtocol):
    """Protocol that reports raw traffic and can skip the startup requests"""

    def __init__(
        self,
        session: DebugSession,
        data_received_callback,
        reconnect_action,
        logger: logging.Logger,
        auto_status: bool = True,
    ) -> None:
        super().__init__(data_received_callback, reconnect_action, logger)

        self.session = session
        self.auto_status = auto_status

    async def _update_status(self):
        if self.auto_status:
            await super()._update_status()

    def connection_made(self, transport: asyncio.Transport):
        super().connection_made(
            _RecordingTransport(transport, self.session.record_sent)
        )

    def data_received(self, data: bytes) -> None:
        self.session.record_received(data)

        try:
            super().data_received(data)
        except Exception as exc:
            self.session.log(ERROR, f"Error handling received data: {exc!r}")

    def connection_lost(self, exc: Exception | None) -> None:
        if self.session.stopping:
            # Closing the transport is what disconnects, so without this the
            # client would immediately reconnect after a requested disconnect
            self.reconnect_action = None

        super().connection_lost(exc)


class _DebugClient(AprilaireClient):
    """Client that creates a protocol reporting back to the session"""

    def __init__(
        self,
        session: DebugSession,
        host: str,
        port: int,
        data_received_callback,
        logger: logging.Logger,
        reconnect_interval: int = None,
        retry_connection_interval: int = None,
        auto_status: bool = True,
    ) -> None:
        self.session = session
        self.auto_status = auto_status

        super().__init__(
            host,
            port,
            data_received_callback,
            logger,
            reconnect_interval,
            retry_connection_interval,
        )

    def create_protocol(self):
        return _DebugProtocol(
            self.session,
            self.data_received,
            self._reconnect_with_delay,
            self.logger,
            self.auto_status,
        )


class DebugSession:
    """An interactive session with a device"""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        logger: logging.Logger = None,
        auto_status: bool = True,
        reconnect: bool = False,
        max_entries: int = 2000,
    ) -> None:
        self.host = host
        self.port = port
        self.logger = logger or logging.getLogger(__name__)
        self.auto_status = auto_status
        self.reconnect = reconnect

        self.entries: deque[LogEntry] = deque(maxlen=max_entries)
        self.state: dict[str, Any] = {}
        self.commands: list[ClientCommand] = discover_client_commands()

        self.entry_listeners: list[Callable[[LogEntry], None]] = []
        self.state_listeners: list[Callable[[dict[str, Any]], None]] = []

        self.stopping = False

        self._receive_buffer = b""

        self.client = _DebugClient(
            self,
            host,
            port,
            self._data_received,
            self.logger,
            retry_connection_interval=10 if reconnect else None,
            auto_status=auto_status,
        )

    @property
    def connected(self) -> bool:
        """Whether the session is currently connected to a device"""
        return bool(self.client.connected and self.client.protocol)

    @property
    def status_text(self) -> str:
        """A short description of the state of the connection"""

        if self.connected:
            return "connected"

        if self.client.reconnecting:
            return "connecting"

        return "disconnected"

    def add_entry_listener(self, listener: Callable[[LogEntry], None]) -> None:
        """Add a listener that is called with each new entry"""
        self.entry_listeners.append(listener)

    def add_state_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        """Add a listener that is called when the device state changes"""
        self.state_listeners.append(listener)

    def log(
        self,
        kind: str,
        message: str,
        raw: bytes = None,
        packets: list[Packet] = None,
        remainder: bytes = b"",
    ) -> LogEntry:
        """Record an entry and notify listeners"""

        entry = LogEntry(
            kind=kind,
            message=message,
            raw=raw,
            packets=packets or [],
            remainder=remainder,
        )

        self.entries.append(entry)

        for listener in list(self.entry_listeners):
            try:
                listener(entry)
            except Exception:
                self.logger.exception("Entry listener failed")

        return entry

    def clear(self) -> None:
        """Remove all recorded entries"""
        self.entries.clear()

    def _data_received(self, data: dict[str, Any]) -> None:
        """Handle decoded data from the client"""

        self.state.update({attribute_name(key): value for key, value in data.items()})

        for listener in list(self.state_listeners):
            try:
                listener(self.state)
            except Exception:
                self.logger.exception("State listener failed")

    def _describe(self, kind: str, data: bytes, packets, remainder: bytes) -> LogEntry:
        """Record traffic in a single direction"""

        if packets:
            summary = "; ".join(packet.summary for packet in packets)
        else:
            summary = "no complete packet"

        return self.log(
            kind,
            f"{len(data)} byte(s): {summary}",
            raw=data,
            packets=packets,
            remainder=remainder,
        )

    def record_sent(self, data: bytes) -> LogEntry:
        """Record data written to the device"""

        # Each write contains whole packets, so nothing is carried over
        packets, remainder = _describe_packets(data)

        return self._describe(SENT, data, packets, remainder)

    def record_received(self, data: bytes) -> LogEntry:
        """Record data received from the device

        A read can end part way through a packet, so anything left over is
        held until the rest of it arrives.
        """

        packets, self._receive_buffer = _describe_packets(self._receive_buffer + data)

        return self._describe(RECEIVED, data, packets, self._receive_buffer)

    async def connect(self) -> None:
        """Connect to the device

        Raises:
            SessionError: the session is already connected
            OSError: the connection could not be established
        """

        if self.connected:
            raise SessionError("Already connected")

        self.stopping = False

        self.log(INFO, f"Connecting to {self.host}:{self.port}")

        try:
            if self.reconnect:
                await self.client.start_listen()
            else:
                await self.client.start_listen_once()
        except Exception:
            # A failed connection leaves the client marked as connecting, so
            # the session would keep reporting that it was connecting
            self.client.reconnecting = False
            self.client.stopped = True

            raise

        self.log(
            INFO,
            "Connected"
            + ("" if self.auto_status else " (startup requests suppressed)"),
        )

    def disconnect(self) -> None:
        """Disconnect from the device"""

        if not self.client.connected and self.client.stopped:
            raise SessionError("Not connected")

        self.stopping = True

        self.client.stop_listen()

        self.log(INFO, "Disconnected")

    def _require_connection(self) -> _DebugProtocol:
        """Get the protocol, or fail if there is no usable connection"""

        protocol = self.client.protocol

        if not self.connected or not protocol or not protocol.transport:
            raise SessionError("Not connected to a device")

        return protocol

    async def run_command(
        self, command: ClientCommand | str, arguments: list[Any] = None
    ) -> LogEntry:
        """Run one of the functions exposed by the client

        Raises:
            SessionError: there is no connection, or no such command
        """

        if isinstance(command, str):
            found = find_command(command, self.commands)

            if not found:
                raise SessionError(f"There is no command named '{command}'")

            command = found

        self._require_connection()

        arguments = list(arguments or [])

        await getattr(self.client, command.name)(*arguments)

        call = f"{command.name}({', '.join(str(argument) for argument in arguments)})"

        return self.log(INFO, f"Queued {call}")

    async def send_packet(self, packet: Packet) -> LogEntry:
        """Send a packet, with the sequence number and CRC filled in

        Raises:
            SessionError: there is no connection, or the packet is not valid
        """

        protocol = self._require_connection()

        try:
            packet.serialize()
        except Exception as exc:
            raise SessionError(f"Unable to build the packet: {exc}") from exc

        await protocol._send_packet(packet)

        return self.log(
            INFO,
            f"Queued {packet.action.name} {packet.functional_domain.name}"
            f" attribute {packet.attribute}",
        )

    def send_raw(self, data: bytes, append_crc: bool = False) -> LogEntry:
        """Write bytes to the device exactly as given

        Nothing is added or corrected, so the sequence number and CRC are
        whatever was provided. This allows deliberately malformed packets to
        be sent to see how a device responds.

        Raises:
            SessionError: there is no connection, or no bytes were given
        """

        protocol = self._require_connection()

        if not data:
            raise SessionError("No bytes to send")

        if append_crc:
            data = bytes(data) + bytes([Packet._generate_crc(list(data))])

        entry = self.log(INFO, f"Writing {len(data)} raw byte(s)")

        protocol.transport.write(data)

        return entry

    async def close(self) -> None:
        """Shut the session down"""

        self.stopping = True

        if self.client.connected or not self.client.stopped:
            self.client.stop_listen()

        # Give the transport a moment to close before the loop stops
        await asyncio.sleep(0)


async def check_connection(session: DebugSession, timeout: float = 5.0) -> bool:
    """Connect to a device, ask it for something and see whether it answers

    Every message is recorded as it would be in an interactive session, so
    what happened can be read on screen or in a capture file.

    Returns:
        Whether the device answered
    """

    try:
        await session.connect()
    except (OSError, SessionError) as exc:
        session.log(ERROR, f"Unable to connect: {exc}")
        return False

    try:
        await session.run_command("read_mac_address")
    except SessionError as exc:
        session.log(ERROR, str(exc))
        return False

    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        mac_address = session.state.get("mac_address")

        if mac_address:
            session.log(
                INFO,
                f"Connected to {session.host}:{session.port}"
                f" with MAC address {mac_address}",
            )

            return True

        await asyncio.sleep(0.05)

    session.log(
        ERROR,
        f"No response from {session.host}:{session.port} within {timeout:g} second(s)",
    )

    return False


class EntryWriter:
    """Writes entries to a file, as either text or newline delimited JSON"""

    def __init__(self, path: str, as_json: bool = False, detail: bool = False) -> None:
        self.path = path
        self.as_json = as_json
        self.detail = detail

        # The file stays open for the life of the writer
        self._file = open(path, "a", encoding="utf-8")

    def __call__(self, entry: LogEntry) -> None:
        """Write a single entry"""

        if self.as_json:
            self._file.write(f"{entry.to_json()}\n")
        else:
            for line in format_entry_lines(entry, self.detail):
                self._file.write(f"{line}\n")

        self._file.flush()

    def close(self) -> None:
        """Close the underlying file"""
        self._file.close()
