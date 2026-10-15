"""Interactive session with a device

Everything the interactive tools do to a device, and everything they learn
from it, goes through `DebugSession`, so the full screen and line based front
ends behave the same.
"""

import asyncio
import json
import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..client import AprilaireClient, AprilaireResponseError, _AprilaireClientProtocol
from ..const import Action, Attribute, FunctionalDomain, NackStatus
from ..packet import NackPacket, Packet
from .commands import ClientCommand, discover_client_commands, find_command

SENT = "sent"
RECEIVED = "received"
INFO = "info"
ERROR = "error"

DEFAULT_PORT = 7001

_LOGGER = logging.getLogger(__name__)


class SessionError(Exception):
    """An interactive command could not be carried out"""


@dataclass
class LogEntry:
    """Something that happened during the session"""

    kind: str
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    raw: bytes | None = None
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


def format_hex(data: bytes) -> str:
    """Format bytes as space separated hex"""
    return bytes(data).hex(" ")


def hexdump(data: bytes, width: int = 16) -> list[str]:
    """Format bytes as offset, hex and ASCII lines"""

    lines: list[str] = []

    for offset in range(0, len(data), width):
        chunk = data[offset : offset + width]

        hex_part = chunk.hex(" ").ljust(width * 3 - 1)
        ascii_part = "".join(
            chr(value) if 32 <= value < 127 else "." for value in chunk
        )

        lines.append(f"{offset:04x}  {hex_part}  |{ascii_part}|")

    return lines


def _parse_frames(data: bytes) -> tuple[list[Packet], bytes]:
    """Parse every complete frame in a byte stream, including those the client
    would discard, returning them and the bytes of a trailing partial frame"""

    parseable_length = Packet.get_parseable_length(data)

    return list(Packet.parse(data, strict=False)), bytes(data[parseable_length:])


def _enum_name(enum_class, value: int | None) -> str:
    """The name of an enum member, or a placeholder for a value that isn't one"""

    if value is None:
        return "?"

    try:
        return enum_class(value).name
    except ValueError:
        return f"UNKNOWN({value})"


def packet_summary(packet: Packet) -> str:
    """A one line description of what a packet addresses"""

    if isinstance(packet, NackPacket):
        return f"NACK {_enum_name(NackStatus, packet.status_code)}"

    if packet.action is None:
        return "empty packet"

    return (
        f"{_enum_name(Action, packet.action)}"
        f" {_enum_name(FunctionalDomain, packet.functional_domain)}"
        f" attribute {packet.attribute}"
    )


def decoded_values(packet: Packet) -> dict[str, Any]:
    """The values a packet carries, by name"""

    if isinstance(packet, NackPacket):
        return {"status_code": packet.status_code}

    return {str(name): value for name, value in packet.data.items()}


def packet_to_dict(packet: Packet) -> dict[str, Any]:
    """Convert a parsed packet into a JSON serializable structure"""

    return {
        "raw": format_hex(packet.raw),
        "revision": packet.revision,
        "sequence": packet.sequence,
        "count": packet.count,
        "action": packet.action,
        "action_name": _enum_name(Action, packet.action),
        "functional_domain": packet.functional_domain,
        "functional_domain_name": _enum_name(
            FunctionalDomain, packet.functional_domain
        ),
        "attribute": packet.attribute,
        "payload": format_hex(packet.payload),
        "crc": packet.raw[-1],
        "crc_valid": packet.crc_valid,
        "summary": packet_summary(packet),
        "decoded": decoded_values(packet),
        "error": packet.error,
    }


def format_entry_lines(entry: LogEntry, detail: bool = False) -> list[str]:
    """Render an entry as a summary line followed by indented packet details"""

    prefix = {SENT: "-->", RECEIVED: "<--", ERROR: "!!!"}.get(entry.kind, "---")

    lines = [f"{entry.time_text} {prefix} {entry.message}"]

    for packet in entry.packets:
        lines.extend(f"      {line}" for line in format_packet_lines(packet, detail))

    if entry.remainder:
        lines.append(f"      incomplete packet: {format_hex(entry.remainder)}")

    return lines


def format_packet_lines(packet: Packet, detail: bool = False) -> list[str]:
    """Render a parsed packet as plain text lines, in both hex and decoded form"""

    lines = [packet_summary(packet)]

    lines.extend(hexdump(packet.raw) if detail else [format_hex(packet.raw)])

    crc_state = "valid" if packet.crc_valid else "INVALID"

    lines.append(
        f"revision={packet.revision} sequence={packet.sequence}"
        f" length={packet.count} crc=0x{packet.raw[-1]:02x} ({crc_state})"
    )

    if packet.error:
        lines.append(packet.error)

    decoded = decoded_values(packet)

    lines.extend(f"{name} = {value}" for name, value in decoded.items())

    if packet.payload and (detail or not decoded):
        decimal = " ".join(str(value) for value in packet.payload)

        lines.append(f"payload: {format_hex(packet.payload)}")
        lines.append(f"payload (decimal): {decimal}")

    if not decoded and not packet.payload:
        lines.append("no payload")

    return lines


class _RecordingTransport:
    """A transport that reports everything written to it, so outgoing bytes
    are captured whether they came from the packet queue or were written raw"""

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
    """Protocol that reports every byte sent and received to the session"""

    def __init__(self, session: DebugSession, *args) -> None:
        super().__init__(*args)

        self.session = session

    def connection_made(self, transport: asyncio.Transport):
        super().connection_made(
            _RecordingTransport(transport, self.session.record_sent)
        )

    def data_received(self, data: bytes) -> None:
        self.session.record_received(data)

        super().data_received(data)


class _DebugClient(AprilaireClient):
    """Client whose protocol reports to the session, and which can skip the
    requests it normally sends on connecting"""

    def __init__(self, session: DebugSession, auto_status: bool, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.session = session
        self.auto_status = auto_status

    def create_protocol(self):
        return _DebugProtocol(
            self.session,
            self.data_received,
            self._reconnect_with_delay,
            self.connection_made,
        )

    async def _update_status(self):
        if self.auto_status:
            await super()._update_status()


class DebugSession:
    """An interactive session with a device"""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        auto_status: bool = True,
        reconnect: bool = False,
        max_entries: int = 2000,
    ) -> None:
        self.host = host
        self.port = port
        self.auto_status = auto_status
        self.reconnect = reconnect

        self.entries: deque[LogEntry] = deque(maxlen=max_entries)
        self.state: dict[str, Any] = {}
        self.commands: list[ClientCommand] = discover_client_commands()

        self.entry_listeners: list[Callable[[LogEntry], None]] = []
        self.state_listeners: list[Callable[[dict[str, Any]], None]] = []

        self._receive_buffer = b""

        self.client = _DebugClient(
            self,
            auto_status,
            host,
            port,
            self._data_received,
            retry_connection_interval=10 if reconnect else None,
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
        raw: bytes | None = None,
        packets: list[Packet] | None = None,
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
                _LOGGER.exception("Entry listener failed")

        return entry

    def clear(self) -> None:
        """Remove all recorded entries"""
        self.entries.clear()

    def _data_received(self, data: dict[str, Any]) -> None:
        """Handle decoded data from the client"""

        self.state.update({str(key): value for key, value in data.items()})

        for listener in list(self.state_listeners):
            try:
                listener(self.state)
            except Exception:
                _LOGGER.exception("State listener failed")

    def _record(
        self, kind: str, data: bytes, packets: list[Packet], remainder: bytes
    ) -> LogEntry:
        """Record traffic in a single direction"""

        if packets:
            summary = "; ".join(packet_summary(packet) for packet in packets)
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

        packets, remainder = _parse_frames(data)

        return self._record(SENT, data, packets, remainder)

    def record_received(self, data: bytes) -> LogEntry:
        """Record data received from the device, holding back a trailing
        partial frame until the rest of it arrives"""

        packets, self._receive_buffer = _parse_frames(self._receive_buffer + data)

        return self._record(RECEIVED, data, packets, self._receive_buffer)

    async def connect(self) -> None:
        """Connect to the device

        Raises:
            SessionError: the session is already connected
            OSError: the connection could not be established
        """

        if self.connected:
            raise SessionError("Already connected")

        self.log(INFO, f"Connecting to {self.host}:{self.port}")

        try:
            if self.reconnect:
                await self.client.start_listen()
            else:
                await self.client.start_listen_once()
        except Exception:
            # A failed connection leaves the client marked as reconnecting
            self.client.reconnecting = False
            self.client.stopped = True

            raise

        self.log(
            INFO,
            "Connected"
            + ("" if self.auto_status else " (startup requests suppressed)"),
        )

    def disconnect(self) -> None:
        """Disconnect from the device

        Raises:
            SessionError: the session is not connected
        """

        if not self.client.connected and self.client.stopped:
            raise SessionError("Not connected")

        self.client.stop_listen()

        self.log(INFO, "Disconnected")

    def _require_connection(self) -> _DebugProtocol:
        """Get the protocol, or fail if there is no usable connection"""

        protocol = self.client.protocol

        if not self.connected or not protocol.transport:
            raise SessionError("Not connected to a device")

        return protocol

    async def run_command(
        self, command: ClientCommand | str, arguments: list[Any] | None = None
    ) -> LogEntry:
        """Run one of the functions exposed by the client

        Raises:
            SessionError: there is no connection, no such command, or the
                command failed
        """

        if isinstance(command, str):
            found = find_command(command, self.commands)

            if not found:
                raise SessionError(f"There is no command named '{command}'")

            command = found

        self._require_connection()

        arguments = list(arguments or [])

        call = f"{command.name}({', '.join(str(argument) for argument in arguments)})"

        entry = self.log(INFO, f"Calling {call}")

        try:
            await getattr(self.client, command.name)(*arguments)
        except Exception as exc:
            raise SessionError(f"{call} failed: {exc}") from exc

        return entry

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

        return self.log(INFO, f"Queued {packet_summary(packet)}")

    def send_raw(self, data: bytes, append_crc: bool = False) -> LogEntry:
        """Write bytes to the device exactly as given, so deliberately
        malformed packets can be sent

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

        if self.client.connected or not self.client.stopped:
            self.client.stop_listen()

        # Give the transport a moment to close before the loop stops
        await asyncio.sleep(0)


async def check_connection(session: DebugSession, timeout: float = 5.0) -> bool:
    """Connect to a device and ask for its MAC address, recording the exchange
    as any other session would

    Returns:
        Whether the device answered
    """

    try:
        await session.connect()
    except (OSError, SessionError) as exc:
        session.log(ERROR, f"Unable to connect: {exc}")
        return False

    try:
        data = await session.client.read_mac_address_and_wait(timeout)
    except AprilaireResponseError as exc:
        session.log(ERROR, f"No answer from {session.host}:{session.port}: {exc}")
        return False

    session.log(
        INFO,
        f"Connected to {session.host}:{session.port}"
        f" with MAC address {data.get(Attribute.MAC_ADDRESS)}",
    )

    return True


class EntryWriter:
    """Writes entries to a file, as either text or newline delimited JSON"""

    def __init__(self, path: str, as_json: bool = False, detail: bool = False) -> None:
        self.as_json = as_json
        self.detail = detail

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
