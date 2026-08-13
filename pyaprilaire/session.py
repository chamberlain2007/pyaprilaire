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
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .client import AprilaireClient, _AprilaireClientProtocol
from .commands import ClientCommand, discover_client_commands, find_command
from .frame import (
    FrameDescription,
    attribute_name,
    describe_frames,
    format_decimal,
    format_hex,
    hexdump,
)
from .packet import Packet

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
    frames: list[FrameDescription] = field(default_factory=list)
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

        if self.frames:
            entry["frames"] = [frame_to_dict(frame) for frame in self.frames]

        if self.remainder:
            entry["remainder"] = format_hex(self.remainder)

        return entry

    def to_json(self) -> str:
        """Convert the entry into a single line of JSON"""
        return json.dumps(self.to_dict(), default=str)


def frame_to_dict(frame: FrameDescription) -> dict[str, Any]:
    """Convert a frame description into a JSON serializable structure"""

    return {
        "raw": format_hex(frame.raw),
        "revision": frame.revision,
        "sequence": frame.sequence,
        "count": frame.count,
        "action": frame.action,
        "action_name": frame.action_name,
        "functional_domain": frame.functional_domain,
        "functional_domain_name": frame.functional_domain_name,
        "attribute": frame.attribute,
        "nack_attribute": frame.nack_attribute,
        "payload": format_hex(frame.payload),
        "crc": frame.crc,
        "crc_valid": frame.crc_valid,
        "summary": frame.summary,
        "decoded": dict(frame.decoded),
        "error": frame.error,
    }


def format_entry_lines(entry: LogEntry, detail: bool = False) -> list[str]:
    """Render an entry as plain text lines

    The first line is a summary of the entry, and the remaining lines are
    indented details of each frame it contains.
    """

    prefix = {SENT: "-->", RECEIVED: "<--", ERROR: "!!!"}.get(entry.kind, "---")

    lines = [f"{entry.time_text} {prefix} {entry.message}"]

    for frame in entry.frames:
        lines.extend(f"      {line}" for line in format_frame_lines(frame, detail))

    if entry.remainder:
        lines.append(f"      incomplete frame: {format_hex(entry.remainder)}")

    return lines


def format_frame_lines(frame: FrameDescription, detail: bool = False) -> list[str]:
    """Render a frame as plain text lines, in both hex and decoded form"""

    lines = [frame.summary]

    if detail:
        lines.extend(hexdump(frame.raw))
    else:
        lines.append(format_hex(frame.raw))

    crc_text = "?" if frame.crc is None else f"0x{frame.crc:02x}"

    lines.append(
        f"revision={frame.revision} sequence={frame.sequence}"
        f" length={frame.count} crc={crc_text}"
        f" ({'valid' if frame.crc_valid else 'INVALID'})"
    )

    if frame.error:
        lines.append(frame.error)

    decoded = frame.decoded

    for name, value in decoded:
        lines.append(f"{name} = {value}")

    if frame.payload and (detail or not decoded):
        lines.append(f"payload: {format_hex(frame.payload)}")
        lines.append(f"payload (decimal): {format_decimal(frame.payload)}")

    if not decoded and not frame.payload:
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
        except Exception as exc:  # pylint: disable=broad-except
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
        frames: list[FrameDescription] = None,
        remainder: bytes = b"",
    ) -> LogEntry:
        """Record an entry and notify listeners"""

        entry = LogEntry(
            kind=kind,
            message=message,
            raw=raw,
            frames=frames or [],
            remainder=remainder,
        )

        self.entries.append(entry)

        for listener in list(self.entry_listeners):
            try:
                listener(entry)
            except Exception:  # pylint: disable=broad-except
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
            except Exception:  # pylint: disable=broad-except
                self.logger.exception("State listener failed")

    def _describe(self, kind: str, data: bytes, frames, remainder: bytes) -> LogEntry:
        """Record traffic in a single direction"""

        if frames:
            summary = "; ".join(frame.summary for frame in frames)
        else:
            summary = "no complete frame"

        return self.log(
            kind,
            f"{len(data)} byte(s): {summary}",
            raw=data,
            frames=frames,
            remainder=remainder,
        )

    def record_sent(self, data: bytes) -> LogEntry:
        """Record data written to the device"""

        # Each write contains whole frames, so nothing is carried over
        frames, remainder = describe_frames(data)

        return self._describe(SENT, data, frames, remainder)

    def record_received(self, data: bytes) -> LogEntry:
        """Record data received from the device

        A read can end part way through a frame, so anything left over is
        held until the rest of it arrives.
        """

        frames, self._receive_buffer = describe_frames(self._receive_buffer + data)

        return self._describe(RECEIVED, data, frames, self._receive_buffer)

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
        except Exception as exc:  # pylint: disable=broad-except
            raise SessionError(f"Unable to build the packet: {exc}") from exc

        await protocol._send_packet(packet)  # pylint: disable=protected-access

        return self.log(
            INFO,
            f"Queued {packet.action.name} {packet.functional_domain.name}"
            f" attribute {packet.attribute}",
        )

    def send_raw(self, data: bytes, append_crc: bool = False) -> LogEntry:
        """Write bytes to the device exactly as given

        Nothing is added or corrected, so the sequence number and CRC are
        whatever was provided. This allows deliberately malformed frames to be
        sent to see how a device responds.

        Raises:
            SessionError: there is no connection, or no bytes were given
        """

        protocol = self._require_connection()

        if not data:
            raise SessionError("No bytes to send")

        if append_crc:
            data = bytes(data) + bytes(
                [Packet._generate_crc(list(data))]  # pylint: disable=protected-access
            )

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


class EntryWriter:
    """Writes entries to a file, as either text or newline delimited JSON"""

    def __init__(self, path: str, as_json: bool = False, detail: bool = False) -> None:
        self.path = path
        self.as_json = as_json
        self.detail = detail

        self._file = open(
            path, "a", encoding="utf-8"
        )  # pylint: disable=consider-using-with

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
