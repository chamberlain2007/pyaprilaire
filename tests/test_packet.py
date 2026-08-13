from pyaprilaire.const import Action, Attribute, FunctionalDomain
from pyaprilaire.packet import NackPacket, Packet, attribute_name, split_packets


def test_invalid_action():
    packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 7, 1, 1, 0]))

    assert len(packets) == 0


def test_invalid_functional_domain():
    packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 3, 17, 1, 0]))

    assert len(packets) == 0


def test_unmapped():
    packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 3, 13, 1, 0]))

    assert len(packets) == 0


def test_packet_empty_parse():
    packets = list(Packet.parse(b""))

    assert len(packets) == 0


def test_packet_single_parse():
    packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 2, 1, 1, 107]))

    assert len(packets) == 1


def test_packet_single_action():
    packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 2, 1, 1, 107]))

    packet = packets[0]

    assert packet.action == Action.READ_REQUEST


def test_packet_single_functional_domain():
    packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 2, 1, 1, 107]))

    packet = packets[0]

    assert packet.functional_domain == FunctionalDomain.SETUP


def test_packet_single_attribute():
    packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 2, 1, 1, 107]))

    packet = packets[0]

    assert packet.attribute == 1


def test_packet_single_extra_data():
    packets: list[Packet] = list(
        Packet.parse([1, 1, 0, 8, 3, 2, 1, 1, 1, 1, 1, 10, 146])
    )

    assert len(packets) == 1


def test_packet_multiple_parse():
    packets: list[Packet] = list(
        Packet.parse([1, 1, 0, 3, 2, 1, 1, 107, 1, 2, 0, 3, 3, 3, 4, 248])
    )

    assert len(packets) == 2


def test_packet_multiple_action():
    packets: list[Packet] = list(
        Packet.parse([1, 1, 0, 3, 2, 1, 1, 107, 1, 2, 0, 3, 3, 3, 4, 248])
    )

    packet = packets[1]

    assert packet.action == Action.READ_RESPONSE


def test_packet_multiple_functional_domain():
    packets: list[Packet] = list(
        Packet.parse([1, 1, 0, 3, 2, 1, 1, 107, 1, 2, 0, 3, 3, 3, 4, 248])
    )

    packet = packets[1]

    assert packet.functional_domain == FunctionalDomain.SCHEDULING


def test_packet_multiple_attribute():
    packets: list[Packet] = list(
        Packet.parse([1, 1, 0, 3, 2, 1, 1, 107, 1, 2, 0, 3, 3, 3, 4, 248])
    )

    packet = packets[1]

    assert packet.attribute == 4


def test_nack_parse():
    packets: list[Packet] = list(Packet.parse([1, 1, 0, 2, 6, 1, 0]))

    assert len(packets) == 1


def test_nack_and_packet_parse():
    packets: list[Packet] = list(
        Packet.parse(
            [
                0x01,
                0x04,
                0x00,
                0x02,
                0x06,
                0x03,
                0xCD,
                0x01,
                0x01,
                0x00,
                0x11,
                0x03,
                0x08,
                0x02,
                0xB4,
                0x82,
                0x55,
                0x50,
                0x93,
                0x6D,
                0x01,
                0x49,
                0x02,
                0x01,
                0x02,
                0x0D,
                0x04,
                0x0E,
                0x51,
            ]
        )
    )

    assert len(packets) == 2


def test_nack_packet_parse():
    packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 6, 1, 0]))

    assert isinstance(packets[0], NackPacket)


def test_control_1_parse():
    packets: list[Packet] = list(Packet.parse([1, 1, 0, 7, 3, 2, 1, 1, 2, 10, 20, 107]))

    packet = packets[0]

    assert packet.data == {
        Attribute.MODE: 1,
        Attribute.FAN_MODE: 2,
        Attribute.HEAT_SETPOINT: 10,
        Attribute.COOL_SETPOINT: 20,
    }


def test_scheduling_4_parse():
    packets: list[Packet] = list(
        Packet.parse([1, 1, 0, 13, 3, 3, 4, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 42])
    )

    packet = packets[0]

    assert packet.data == {
        Attribute.HOLD: 1,
    }


def test_sensor_2_parse():
    packets: list[Packet] = list(
        Packet.parse([1, 1, 0, 11, 3, 5, 2, 1, 10, 2, 20, 3, 50, 4, 60, 12])
    )

    packet = packets[0]

    assert packet.data == {
        Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS: 1,
        Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_VALUE: 10,
        Attribute.OUTDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS: 2,
        Attribute.OUTDOOR_TEMPERATURE_CONTROLLING_SENSOR_VALUE: 20,
        Attribute.INDOOR_HUMIDITY_CONTROLLING_SENSOR_STATUS: 3,
        Attribute.INDOOR_HUMIDITY_CONTROLLING_SENSOR_VALUE: 50,
        Attribute.OUTDOOR_HUMIDITY_CONTROLLING_SENSOR_STATUS: 4,
        Attribute.OUTDOOR_HUMIDITY_CONTROLLING_SENSOR_VALUE: 60,
    }


def test_identification_2_parse():
    packets: list[Packet] = list(
        Packet.parse([1, 1, 0, 9, 3, 8, 2, 1, 2, 3, 4, 5, 6, 176])
    )

    packet = packets[0]

    assert packet.data == {Attribute.MAC_ADDRESS: "1:2:3:4:5:6"}


def test_identification_4_parse():
    packets: list[Packet] = list(
        Packet.parse(
            [
                1,
                1,
                0,
                27,
                3,
                8,
                4,
                49,
                50,
                51,
                52,
                53,
                0,
                0,
                0,
                84,
                101,
                115,
                116,
                32,
                78,
                97,
                109,
                101,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                180,
            ]
        )
    )

    packet = packets[0]

    assert packet.data == {Attribute.LOCATION: "12345", Attribute.NAME: "Test Name"}


def test_decode_temperature():
    temperature = Packet._decode_temperature(0x15)

    assert temperature == 21


def test_decode_temperature_negative():
    temperature = Packet._decode_temperature(0x95)

    assert temperature == -21


def test_decode_temperature_decimal():
    temperature = Packet._decode_temperature(0x5A)

    assert temperature == 26.5


def test_decode_temperature_negative_decimal():
    temperature = Packet._decode_temperature(0xDA)

    assert temperature == -26.5


def test_decode_humidity_zero():
    humidity = Packet._decode_humidity(0)

    assert humidity == 0


def test_decode_humidity_1():
    humidity = Packet._decode_humidity(1)

    assert humidity == 1


def test_decode_humidity_99():
    humidity = Packet._decode_humidity(99)

    assert humidity == 99


def test_decode_humidity_100():
    humidity = Packet._decode_humidity(100)

    assert humidity == 100


def test_decode_humidity_nonzero():
    humidity = Packet._decode_humidity(50)

    assert humidity == 50


def test_decode_humidity_negative():
    humidity = Packet._decode_humidity(-50)

    assert humidity is None


def test_encode_temperature():
    encoded_temperature = Packet._encode_temperature(21)

    assert encoded_temperature == 0x15


def test_encode_temperature_fraction():
    encoded_temperature = Packet._encode_temperature(26.5)

    assert encoded_temperature == 0x5A


def test_encode_temperature_negative():
    encoded_temperature = Packet._encode_temperature(-21)

    assert encoded_temperature == 0x95


def test_encode_temperature_negative_fraction():
    encoded_temperature = Packet._encode_temperature(-26.5)

    assert encoded_temperature == 0xDA


def test_serialize_nack():
    serialized = NackPacket(2).serialize()

    assert serialized == bytes([1, 0, 0, 2, 6, 2, 227])


def test_serialize_raw():
    serialized = Packet(
        Action.READ_REQUEST, FunctionalDomain.CONTROL, 1, 1, 1, raw_data=[1, 2, 3]
    ).serialize()

    assert serialized == bytes([1, 1, 0, 6, 2, 2, 1, 1, 2, 3, 133])


def test_serialize_single_packet_no_data():
    serialized = Packet(
        Action.READ_REQUEST,
        FunctionalDomain.CONTROL,
        1,
        1,
        1,
    ).serialize()

    assert serialized == bytes([1, 1, 0, 3, 2, 2, 1, 70])


def test_control_1_serialize():
    serialized = Packet(
        Action.READ_RESPONSE,
        FunctionalDomain.CONTROL,
        1,
        1,
        1,
        data={
            Attribute.MODE: 1,
            Attribute.FAN_MODE: 2,
            Attribute.HEAT_SETPOINT: 10,
            Attribute.COOL_SETPOINT: 20,
        },
    ).serialize()

    assert serialized == bytes([1, 1, 0, 7, 3, 2, 1, 1, 2, 10, 20, 107])


def test_scheduling_4_serialize():
    serialized = Packet(
        Action.READ_RESPONSE,
        FunctionalDomain.SCHEDULING,
        4,
        1,
        1,
        data={
            Attribute.HOLD: 1,
        },
    ).serialize()

    assert serialized == bytes([1, 1, 0, 13, 3, 3, 4, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 55])


def test_sensor_2_serialize():
    serialized = Packet(
        Action.READ_RESPONSE,
        FunctionalDomain.SENSORS,
        2,
        1,
        1,
        data={
            Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS: 1,
            Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_VALUE: 10,
            Attribute.OUTDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS: 2,
            Attribute.OUTDOOR_TEMPERATURE_CONTROLLING_SENSOR_VALUE: 20,
            Attribute.INDOOR_HUMIDITY_CONTROLLING_SENSOR_STATUS: 3,
            Attribute.INDOOR_HUMIDITY_CONTROLLING_SENSOR_VALUE: 50,
            Attribute.OUTDOOR_HUMIDITY_CONTROLLING_SENSOR_STATUS: 4,
            Attribute.OUTDOOR_HUMIDITY_CONTROLLING_SENSOR_VALUE: 60,
        },
    ).serialize()

    assert serialized == bytes([1, 1, 0, 11, 3, 5, 2, 1, 10, 2, 20, 3, 50, 4, 60, 12])


def test_identification_2_serialize():
    serialized = Packet(
        Action.READ_RESPONSE,
        FunctionalDomain.IDENTIFICATION,
        2,
        1,
        1,
        data={Attribute.MAC_ADDRESS: [1, 2, 3, 4, 5, 6]},
    ).serialize()

    assert serialized == bytes([1, 1, 0, 9, 3, 8, 2, 1, 2, 3, 4, 5, 6, 176])


def test_identification_4_serialize():
    serialized = Packet(
        Action.READ_RESPONSE,
        FunctionalDomain.IDENTIFICATION,
        4,
        1,
        1,
        data={Attribute.LOCATION: "12345", Attribute.NAME: "Test Name"},
    ).serialize()

    assert serialized == bytes(
        [
            1,
            1,
            0,
            27,
            3,
            8,
            4,
            49,
            50,
            51,
            52,
            53,
            0,
            0,
            0,
            84,
            101,
            115,
            116,
            32,
            78,
            97,
            109,
            101,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            180,
        ]
    )


def build_packet_bytes(
    action: Action,
    functional_domain: FunctionalDomain,
    attribute: int,
    payload: list[int] = None,
    sequence: int = 1,
) -> bytes:
    """Build a packet with a valid checksum, bypassing the mapping"""

    body = [int(action), int(functional_domain), attribute] + (payload or [])

    raw = [1, sequence, len(body) >> 8, len(body) & 0xFF] + body
    raw.append(Packet._generate_crc(raw))

    return bytes(raw)


def test_split_packets_single():
    raw = Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1).serialize()

    packets, remainder = split_packets(raw)

    assert packets == [raw]
    assert remainder == b""


def test_split_packets_multiple():
    first = Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1).serialize()
    second = Packet(Action.READ_REQUEST, FunctionalDomain.SENSORS, 2).serialize()

    packets, remainder = split_packets(first + second)

    assert packets == [first, second]
    assert remainder == b""


def test_split_packets_partial():
    raw = Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1).serialize()

    packets, remainder = split_packets(raw[:-2])

    assert packets == []
    assert remainder == raw[:-2]


def test_split_packets_partial_header():
    packets, remainder = split_packets(b"\x01\x02")

    assert packets == []
    assert remainder == b"\x01\x02"


def test_split_packets_completed_by_later_data():
    raw = Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1).serialize()

    _, remainder = split_packets(raw[:3])

    packets, remainder = split_packets(remainder + raw[3:])

    assert packets == [raw]
    assert remainder == b""


def test_split_packets_bogus_length():
    data = b"\x01\x02\xff\xff\x01\x02"

    packets, remainder = split_packets(data)

    assert packets == [data]
    assert remainder == b""


def parse_one(data: bytes) -> Packet:
    """Parse a single packet, including one that can't be acted on"""

    packets = list(Packet.parse(data, strict=False))

    assert len(packets) == 1

    return packets[0]


def test_parse_describes_a_packet():
    raw = Packet(
        Action.READ_RESPONSE,
        FunctionalDomain.CONTROL,
        1,
        data={
            Attribute.MODE: 3,
            Attribute.FAN_MODE: 2,
            Attribute.HEAT_SETPOINT: 20,
            Attribute.COOL_SETPOINT: 25,
        },
    ).serialize()

    packet = parse_one(raw)

    assert packet.raw == raw
    assert packet.revision == 1
    assert packet.count == 7
    assert packet.action == Action.READ_RESPONSE
    assert packet.action_name == "READ_RESPONSE"
    assert packet.functional_domain == FunctionalDomain.CONTROL
    assert packet.functional_domain_name == "CONTROL"
    assert packet.attribute == 1
    assert packet.crc_valid
    assert packet.error is None
    assert packet.payload == bytes([3, 2, 20, 25])
    assert packet.summary == "READ_RESPONSE CONTROL attribute 1"
    assert dict(packet.decoded) == {
        "mode": 3,
        "fan_mode": 2,
        "heat_setpoint": 20,
        "cool_setpoint": 25,
    }


def test_parse_describes_a_packet_without_a_payload():
    packet = parse_one(
        Packet(Action.READ_REQUEST, FunctionalDomain.SENSORS, 2).serialize()
    )

    assert packet.payload == b""
    assert packet.decoded == []
    assert packet.crc_valid


def test_parse_describes_a_nack():
    packet = parse_one(NackPacket(7).serialize())

    assert packet.action == Action.NACK
    assert packet.nack_attribute == 7
    assert packet.summary == "NACK attribute 7"
    assert packet.decoded == [("nack_attribute", 7)]


def test_parse_describes_an_invalid_checksum():
    raw = bytearray(
        Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1).serialize()
    )
    raw[-1] ^= 0xFF

    packet = parse_one(bytes(raw))

    assert not packet.crc_valid
    # A packet that fails its checksum is still described, just not acted on
    assert packet.action == Action.READ_REQUEST
    assert list(Packet.parse(bytes(raw))) == []


def test_parse_describes_an_unknown_attribute():
    raw = build_packet_bytes(
        Action.READ_RESPONSE, FunctionalDomain.CONTROL, 99, [1, 2, 3]
    )

    packet = parse_one(raw)

    assert packet.crc_valid
    assert packet.attribute == 99
    assert packet.payload == bytes([1, 2, 3])
    assert packet.raw_data == [1, 2, 3]
    assert packet.decoded == []
    assert packet.summary == "READ_RESPONSE CONTROL attribute 99"


def test_parse_describes_an_unknown_action():
    packet = parse_one(build_packet_bytes(99, 88, 1, [1]))

    assert packet.action_name == "UNKNOWN(99)"
    assert packet.functional_domain_name == "UNKNOWN(88)"
    assert packet.summary == "UNKNOWN(99) UNKNOWN(88) attribute 1"
    assert packet.payload == bytes([1])


def test_parse_describes_bytes_that_are_too_short():
    packet = parse_one(b"\x01\x02")

    assert packet.error == "Packet is too short to contain a header and a checksum"
    assert packet.action is None
    assert packet.summary == "empty packet"


def test_parse_describes_a_length_mismatch():
    raw = bytearray(
        Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1).serialize()
    )
    raw[3] = 9

    packet = parse_one(bytes(raw))

    assert "Length mismatch" in packet.error


def test_parse_describes_a_packet_with_no_action():
    packet = parse_one(bytes([1, 1, 0, 0, 0]))

    assert packet.count == 0
    assert packet.action is None
    assert packet.error == "Packet has no action"
    assert packet.summary == "empty packet"


def test_parse_describes_a_nack_without_an_attribute():
    raw = bytearray([1, 1, 0, 1, int(Action.NACK)])
    raw.append(Packet._generate_crc(list(raw)))

    packet = parse_one(bytes(raw))

    assert packet.crc_valid
    assert packet.nack_attribute is None
    assert packet.summary == "NACK attribute None"


def test_parse_describes_a_truncated_payload():
    raw = bytearray(
        Packet(
            Action.READ_RESPONSE,
            FunctionalDomain.IDENTIFICATION,
            2,
            data={Attribute.MAC_ADDRESS: [1, 2, 3, 4, 5, 6]},
        ).serialize()
    )

    packet = parse_one(bytes(raw[:-3]))

    assert (
        packet.error == "Length mismatch: header declares 9 byte(s), packet contains 6"
    )
    # Nothing can be done with it, so it is not returned to the client
    assert list(Packet.parse(bytes(raw[:-3]))) == []


def test_parse_describes_a_payload_that_ends_early():
    # The length is what the packet says it is, but the attribute it carries
    # needs more bytes than are there
    raw = build_packet_bytes(
        Action.READ_RESPONSE, FunctionalDomain.IDENTIFICATION, 2, [1]
    )

    packet = parse_one(raw)

    assert "Unable to decode the payload" in packet.error
    assert list(Packet.parse(raw)) == []


def test_parse_skips_everything_it_cannot_use():
    assert list(Packet.parse(b"\x01\x02")) == []
    assert list(Packet.parse(bytes([1, 1, 0, 0, 0]))) == []
    assert list(Packet.parse(build_packet_bytes(99, 88, 1, [1]))) == []


def test_attribute_name():
    assert attribute_name(Attribute.MODE) == "mode"
    assert attribute_name("mode") == "mode"


def test_parse_keeps_the_header_of_an_unknown_packet():
    packet = parse_one(build_packet_bytes(99, 88, 1, [1], sequence=9))

    assert packet.revision == 1
    assert packet.sequence == 9
    assert packet.count == 4
