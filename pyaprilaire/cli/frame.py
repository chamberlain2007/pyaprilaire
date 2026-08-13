"""Utilities for splitting and describing raw protocol frames.

The rest of the library works with :class:`~pyaprilaire.packet.Packet`, which
intentionally discards anything it doesn't understand. Tools that debug a
device need the opposite: every byte that was on the wire, decoded as far as
possible and shown verbatim otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..const import Action, FunctionalDomain
from ..packet import NackPacket, Packet, crc_calculator

HEADER_SIZE = 4
CRC_SIZE = 1
MIN_FRAME_SIZE = HEADER_SIZE + CRC_SIZE

# A payload longer than this is assumed to be a corrupt length rather than a
# frame that hasn't fully arrived yet
MAX_PAYLOAD_SIZE = 512


def split_frames(data: bytes) -> tuple[list[bytes], bytes]:
    """Split a byte stream into complete frames and a trailing remainder

    The remainder is whatever is left of an incomplete frame, and should be
    prepended to the next chunk of data received.
    """

    frames: list[bytes] = []
    index = 0

    while index < len(data):
        remaining = len(data) - index

        if remaining < HEADER_SIZE:
            break

        count = data[index + 2] << 8 | data[index + 3]

        if count > MAX_PAYLOAD_SIZE:
            # The length is nonsense, so there is no reliable way to find the
            # start of the next frame. Surface the rest as a single frame so
            # that the bytes aren't silently dropped.
            frames.append(bytes(data[index:]))
            index = len(data)
            break

        frame_size = HEADER_SIZE + count + CRC_SIZE

        if remaining < frame_size:
            break

        frames.append(bytes(data[index : index + frame_size]))
        index += frame_size

    return frames, bytes(data[index:])


@dataclass
class FrameDescription:
    """A frame broken into its parts, decoded as far as possible"""

    raw: bytes
    revision: int = None
    sequence: int = None
    count: int = None
    action: int = None
    functional_domain: int = None
    attribute: int = None
    nack_attribute: int = None
    payload: bytes = b""
    crc: int = None
    crc_valid: bool = False
    packets: list[Packet] = field(default_factory=list)
    error: str = None

    @property
    def action_name(self) -> str:
        """The name of the action, or a placeholder if it is unknown"""
        return _enum_name(Action, self.action)

    @property
    def functional_domain_name(self) -> str:
        """The name of the functional domain, or a placeholder if unknown"""
        return _enum_name(FunctionalDomain, self.functional_domain)

    @property
    def summary(self) -> str:
        """A one line description of what the frame addresses"""

        if self.action is None:
            return "empty frame"

        if self.action == Action.NACK:
            return f"NACK attribute {self.nack_attribute}"

        return (
            f"{self.action_name} {self.functional_domain_name}"
            f" attribute {self.attribute}"
        )

    @property
    def decoded(self) -> list[tuple[str, Any]]:
        """The decoded attribute values from every packet in the frame"""

        values: list[tuple[str, Any]] = []

        for packet in self.packets:
            if isinstance(packet, NackPacket):
                values.append(("nack_attribute", packet.nack_attribute))

            values.extend(
                (attribute_name(key), value) for key, value in packet.data.items()
            )

        return values


def attribute_name(attribute) -> str:
    """Get the name of a decoded attribute

    The attribute is normally an :class:`~pyaprilaire.const.Attribute`, which
    is a string enum, but the name is taken defensively so that the display
    doesn't depend on how the enum renders itself.
    """

    return getattr(attribute, "value", None) or str(attribute)


def _enum_name(enum_class, value: int) -> str:
    """Get the name of an enum value, falling back to the raw value"""

    if value is None:
        return "?"

    try:
        return enum_class(value).name
    except ValueError:
        return f"UNKNOWN({value})"


def describe_frame(frame: bytes) -> FrameDescription:
    """Break a single frame into its parts"""

    description = FrameDescription(raw=bytes(frame))

    if len(frame) < MIN_FRAME_SIZE:
        description.error = "Frame is too short to contain a header and CRC"
        return description

    description.revision = frame[0]
    description.sequence = frame[1]
    description.count = frame[2] << 8 | frame[3]
    description.crc = frame[-1]
    description.crc_valid = crc_calculator.verify(bytes(frame[:-1]), frame[-1])

    body = frame[HEADER_SIZE:-1]

    if len(body) != description.count:
        description.error = (
            f"Length mismatch: header declares {description.count} byte(s),"
            f" frame contains {len(body)}"
        )

    if body:
        description.action = body[0]

    if description.action == Action.NACK:
        # A NACK carries the rejected attribute where the functional domain
        # would normally be
        if len(body) > 1:
            description.nack_attribute = body[1]

        description.payload = bytes(body[2:])
    else:
        if len(body) > 1:
            description.functional_domain = body[1]

        if len(body) > 2:
            description.attribute = body[2]

        description.payload = bytes(body[3:])

    try:
        description.packets = list(Packet.parse(frame))
    except Exception as exc:  # pylint: disable=broad-except
        description.packets = []

        if description.error is None:
            description.error = f"Unable to decode packet: {exc!r}"

    return description


def describe_frames(data: bytes) -> tuple[list[FrameDescription], bytes]:
    """Split a byte stream into frames and describe each of them"""

    frames, remainder = split_frames(data)

    return [describe_frame(frame) for frame in frames], remainder


def format_hex(data: bytes) -> str:
    """Format bytes as space separated hex"""
    return bytes(data).hex(" ") if data else ""


def format_decimal(data: bytes) -> str:
    """Format bytes as space separated decimal values"""
    return " ".join(str(value) for value in data)


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
