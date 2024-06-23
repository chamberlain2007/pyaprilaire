from pyaprilaire.const import Action, Attribute, FunctionalDomain
from pyaprilaire.packet import NackPacket, Packet


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
    packets = list(Packet.parse(bytes()))

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

    assert humidity == None


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
