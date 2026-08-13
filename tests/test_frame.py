from pyaprilaire.cli.frame import (
    attribute_name,
    describe_frame,
    describe_frames,
    format_decimal,
    format_hex,
    hexdump,
    split_frames,
)
from pyaprilaire.const import Action, Attribute, FunctionalDomain
from pyaprilaire.packet import NackPacket, Packet


def build_frame(
    action: Action,
    functional_domain: FunctionalDomain,
    attribute: int,
    payload: list[int] = None,
    sequence: int = 1,
) -> bytes:
    """Build a frame with a valid CRC, bypassing the packet mapping"""

    body = [int(action), int(functional_domain), attribute] + (payload or [])

    frame = [1, sequence, len(body) >> 8, len(body) & 0xFF] + body
    frame.append(Packet._generate_crc(frame))

    return bytes(frame)


def test_split_frames_single():
    frame = Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1).serialize()

    frames, remainder = split_frames(frame)

    assert frames == [frame]
    assert remainder == b""


def test_split_frames_multiple():
    first = Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1).serialize()
    second = Packet(Action.READ_REQUEST, FunctionalDomain.SENSORS, 2).serialize()

    frames, remainder = split_frames(first + second)

    assert frames == [first, second]
    assert remainder == b""


def test_split_frames_partial():
    frame = Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1).serialize()

    frames, remainder = split_frames(frame[:-2])

    assert frames == []
    assert remainder == frame[:-2]


def test_split_frames_partial_header():
    frames, remainder = split_frames(b"\x01\x02")

    assert frames == []
    assert remainder == b"\x01\x02"


def test_split_frames_completed_by_later_data():
    frame = Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1).serialize()

    _, remainder = split_frames(frame[:3])

    frames, remainder = split_frames(remainder + frame[3:])

    assert frames == [frame]
    assert remainder == b""


def test_split_frames_bogus_length():
    data = b"\x01\x02\xff\xff\x01\x02"

    frames, remainder = split_frames(data)

    assert frames == [data]
    assert remainder == b""


def test_describe_frame():
    packet = Packet(
        Action.READ_RESPONSE,
        FunctionalDomain.CONTROL,
        1,
        data={
            Attribute.MODE: 3,
            Attribute.FAN_MODE: 2,
            Attribute.HEAT_SETPOINT: 20,
            Attribute.COOL_SETPOINT: 25,
        },
    )

    description = describe_frame(packet.serialize())

    assert description.revision == 1
    assert description.count == 7
    assert description.action == Action.READ_RESPONSE
    assert description.action_name == "READ_RESPONSE"
    assert description.functional_domain == FunctionalDomain.CONTROL
    assert description.functional_domain_name == "CONTROL"
    assert description.attribute == 1
    assert description.crc_valid
    assert description.error is None
    assert description.payload == bytes([3, 2, 20, 25])
    assert description.summary == "READ_RESPONSE CONTROL attribute 1"
    assert dict(description.decoded) == {
        "mode": 3,
        "fan_mode": 2,
        "heat_setpoint": 20,
        "cool_setpoint": 25,
    }


def test_describe_frame_read_request_has_no_payload():
    description = describe_frame(
        Packet(Action.READ_REQUEST, FunctionalDomain.SENSORS, 2).serialize()
    )

    assert description.payload == b""
    assert description.decoded == []
    assert description.crc_valid


def test_describe_frame_nack():
    description = describe_frame(NackPacket(7).serialize())

    assert description.action == Action.NACK
    assert description.nack_attribute == 7
    assert description.functional_domain is None
    assert description.summary == "NACK attribute 7"
    assert description.decoded == [("nack_attribute", 7)]


def test_describe_frame_invalid_crc():
    frame = bytearray(
        Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1).serialize()
    )
    frame[-1] ^= 0xFF

    description = describe_frame(bytes(frame))

    assert not description.crc_valid
    # A frame that fails its checksum is still described, just not decoded
    assert description.action == Action.READ_REQUEST
    assert description.packets == []


def test_describe_frame_unknown_attribute():
    frame = build_frame(Action.READ_RESPONSE, FunctionalDomain.CONTROL, 99, [1, 2, 3])

    description = describe_frame(frame)

    assert description.crc_valid
    assert description.attribute == 99
    assert description.payload == bytes([1, 2, 3])
    assert description.packets == []
    assert description.summary == "READ_RESPONSE CONTROL attribute 99"


def test_describe_frame_unknown_action():
    frame = build_frame(99, 88, 1, [1])

    description = describe_frame(frame)

    assert description.action_name == "UNKNOWN(99)"
    assert description.functional_domain_name == "UNKNOWN(88)"
    assert description.summary == "UNKNOWN(99) UNKNOWN(88) attribute 1"


def test_describe_frame_too_short():
    description = describe_frame(b"\x01\x02")

    assert description.error == "Frame is too short to contain a header and CRC"
    assert description.action is None
    assert description.summary == "empty frame"


def test_describe_frame_length_mismatch():
    frame = bytearray(
        Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1).serialize()
    )
    frame[3] = 9

    description = describe_frame(bytes(frame))

    assert "Length mismatch" in description.error


def test_describe_frames():
    first = Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1).serialize()
    second = Packet(Action.READ_REQUEST, FunctionalDomain.SENSORS, 2).serialize()

    descriptions, remainder = describe_frames(first + second + b"\x01")

    assert [description.summary for description in descriptions] == [
        "READ_REQUEST CONTROL attribute 1",
        "READ_REQUEST SENSORS attribute 2",
    ]
    assert remainder == b"\x01"


def test_format_hex():
    assert format_hex(b"\x01\x0a\xff") == "01 0a ff"
    assert format_hex(b"") == ""


def test_format_decimal():
    assert format_decimal(b"\x01\x0a\xff") == "1 10 255"


def test_hexdump():
    lines = hexdump(bytes(range(20)))

    assert len(lines) == 2
    assert lines[0].startswith("0000  00 01 02")
    assert lines[1].startswith("0010  10 11 12 13")


def test_attribute_name():
    assert attribute_name(Attribute.MODE) == "mode"
    assert attribute_name("mode") == "mode"


def test_describe_frame_that_cannot_be_decoded():
    # The header claims an empty body, so there is nothing for the packet
    # parser to read
    frame = bytes([1, 1, 0, 0, 0])

    description = describe_frame(frame)

    assert description.count == 0
    assert description.action is None
    assert description.packets == []
    assert description.error.startswith("Unable to decode packet:")


def test_describe_frame_nack_without_an_attribute():
    frame = bytearray([1, 1, 0, 1, int(Action.NACK)])
    frame.append(Packet._generate_crc(list(frame)))

    description = describe_frame(bytes(frame))

    assert description.crc_valid
    assert description.nack_attribute is None
    assert description.summary == "NACK attribute None"
