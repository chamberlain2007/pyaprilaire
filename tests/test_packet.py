import pytest

from pyaprilaire.const import (
    Action,
    AirCleaningStatus,
    Attribute,
    CoolingEquipmentStatus,
    DehumidificationStatus,
    FanMode,
    FanStatus,
    FunctionalDomain,
    HeatingEquipmentStatus,
    HoldType,
    HumidificationStatus,
    HvacMode,
    SensorStatus,
    SimpleStatus,
    TemperatureScale,
    ThermostatError,
    VentilationStatus,
    get_simple_status,
)
from pyaprilaire.packet import MAPPING, NackPacket, Packet

# All 17 non-reserved status codes from spec section H.5. 0x00, 0x02 (Generic
# group) and the bare 0xFF marker's own value are technically "Reserved" /
# "Extended", but 0xFF is included here as a status code value like the
# others per the H.5 table; 0x00 and 0x02 are omitted as genuinely reserved.
NACK_STATUS_CODES = [
    0x01,  # Generic Error
    0x03,  # Buffer Full or Device Busy
    0x04,  # Unsupported protocol revision
    0x05,  # Unknown Action
    0x06,  # Unknown Functional Domain
    0x07,  # Unknown Attribute
    0x08,  # Cannot accept writes in current application mode
    0x09,  # Timed out waiting for response
    0x0A,  # Unsupported Model
    0x10,  # Value out of range
    0x11,  # Attribute Read Only
    0x12,  # Attribute not writeable in current configuration
    0x13,  # Incorrect number of data bytes (write)
    0x20,  # Attribute not readable (write only)
    0x21,  # Attribute not available - try later
    0x22,  # Incorrect number of data bytes (read)
    0xFF,  # Extended
]


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


def test_count_decoded_high_byte_first():
    # Regression test for a CNT decoded with the wrong shift (packet.py count
    # calculation). Spec section F, note 4: CNT is sent high byte first, so a
    # payload of 300 bytes must be encoded as CNT = 0x01, 0x2C. A payload this
    # large only exists in a currently-mapped attribute (Control/1) if we pad
    # it with trailing bytes past the mapped fields, which real devices do
    # (see the trailing bytes in test_nack_and_packet_parse).
    header = [1, 1, 1, 44]  # REV, SEQ, CNT high (1), CNT low (44) -> count=300
    payload = [3, 2, 1, 1, 2, 10, 20] + [0] * 293  # ACTION, FD, ATTR, data..., padding
    assert len(payload) == 300

    frame = header + payload
    frame.append(Packet._generate_crc(frame))

    packets: list[Packet] = list(Packet.parse(frame))

    assert len(packets) == 1
    assert packets[0].data == {
        Attribute.MODE: 1,
        Attribute.FAN_MODE: 2,
        Attribute.HEAT_SETPOINT: 10,
        Attribute.COOL_SETPOINT: 20,
    }


def test_nack_parse():
    packets: list[Packet] = list(Packet.parse([1, 1, 0, 2, 6, 1, 0x63]))

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
    packets: list[Packet] = list(Packet.parse([1, 1, 0, 2, 6, 1, 0x63]))

    assert isinstance(packets[0], NackPacket)


def test_nack_carries_sequence():
    # Regression test for failure mode 3: NackPacket used to drop the
    # parsed sequence number entirely (always defaulting to 0), so a NACK
    # could never be attributed back to the request that caused it. Spec
    # section F notes 2-3: retries (and the responses they produce) reuse
    # the initiating request's sequence number, so that number must survive
    # parsing.
    frame = [1, 42, 0, 2, 6, 1]
    frame.append(Packet._generate_crc(frame))

    packets: list[Packet] = list(Packet.parse(frame))

    assert len(packets) == 1
    assert isinstance(packets[0], NackPacket)
    assert packets[0].sequence == 42


def test_nack_invalid_crc_rejected():
    # Regression test: NACK frames used to bypass CRC verification entirely,
    # so line noise could be misparsed as a spurious NACK. Real CRC for this
    # frame is 0x71, not the 0x00 given here.
    packets: list[Packet] = list(
        Packet.parse([0x01, 0x80, 0x00, 0x02, 0x06, 0x10, 0x00])
    )

    assert packets == []


def test_nack_invalid_crc_and_mismatched_attribute_rejected():
    packets: list[Packet] = list(
        Packet.parse(
            [0x01, 0x80, 0x00, 0x07, 0x03, 0x07, 0x06, 0x02, 0x00, 0x01, 0x01, 0x00]
        )
    )

    assert packets == []


@pytest.mark.parametrize("status_code", NACK_STATUS_CODES)
def test_nack_status_code_parse(status_code):
    # Regression test: byte 5 of a NACK payload (spec section G, "FUNCTIONAL
    # DOMAIN / STATUS CODE") used to be coerced through FunctionalDomain
    # before the NACK branch was reached. FunctionalDomain only defines a
    # subset of 0x00-0xFF, so any status code outside that set (e.g. 0x11,
    # a Write-rejection code) raised ValueError and the whole frame was
    # silently discarded. Every status code in spec section H.5 must yield
    # a NackPacket carrying that exact code.
    frame = [0x01, 0x80, 0x00, 0x02, 0x06, status_code]
    frame.append(Packet._generate_crc(frame))

    packets: list[Packet] = list(Packet.parse(frame))

    assert len(packets) == 1
    assert isinstance(packets[0], NackPacket)
    assert packets[0].status_code == status_code


def test_nack_status_code_outside_functional_domain_range_invalid_crc_rejected():
    # A status code that falls outside FunctionalDomain's defined values
    # (0x11 - Attribute Read Only) must still be rejected when the CRC is
    # wrong, proving the fix does not simply accept the byte unconditionally.
    frame = [0x01, 0x80, 0x00, 0x02, 0x06, 0x11, 0x00]

    assert Packet._generate_crc(frame[:-1]) != frame[-1]

    packets: list[Packet] = list(Packet.parse(frame))

    assert packets == []


def test_nack_status_code_outside_functional_domain_range_no_desync():
    # A NACK carrying a status code outside FunctionalDomain's range
    # (previously dropped entirely) must not desynchronize the stream: a
    # valid frame immediately following it must still be parsed.
    nack_frame = [0x01, 0x80, 0x00, 0x02, 0x06, 0x11]
    nack_frame.append(Packet._generate_crc(nack_frame))

    valid_frame = [1, 1, 0, 3, 2, 1, 1, 107]

    packets: list[Packet] = list(Packet.parse(nack_frame + valid_frame))

    assert len(packets) == 2
    assert isinstance(packets[0], NackPacket)
    assert packets[0].status_code == 0x11
    assert packets[1].action == Action.READ_REQUEST
    assert packets[1].functional_domain == FunctionalDomain.SETUP
    assert packets[1].attribute == 1


def test_unknown_non_nack_functional_domain_still_skipped():
    # Regression guard: splitting the single Action/FunctionalDomain try
    # block into two (so NACK status codes bypass FunctionalDomain
    # coercion) must not change behavior for non-NACK actions - an unknown
    # functional domain must still cause the frame to be skipped via the
    # count + 5 resync, not crash or otherwise be treated as a NACK.
    packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 3, 17, 1, 0]))

    assert packets == []


def test_unknown_action_still_skipped():
    # Regression guard: an unrecognized action byte must still be skipped
    # via the count + 5 resync, not crash.
    packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 7, 1, 1, 0]))

    assert packets == []


def test_short_mac_frame_does_not_desync_following_frame():
    # Regression test: MAC_ADDRESS consumed 6 bytes unconditionally, without
    # checking whether the frame's declared count left room for them. A
    # short MAC frame would overshoot into the CRC byte (and beyond, into
    # the next frame), corrupting the parse position for everything after
    # it. Here the first frame declares only 4 bytes of MAC data (count=7,
    # so only 1 byte for a required 6), and is followed by a fully valid
    # Status/6 frame that must still be parsed correctly.
    packets: list[Packet] = list(
        Packet.parse(
            [
                # Frame 1: truncated MAC address (Identification/2) - malformed
                0x01,
                0x80,
                0x00,
                0x07,
                0x03,
                0x08,
                0x02,
                0xB4,
                0x82,
                0x55,
                0x01,
                0x53,
                # Frame 2: valid Status/6 frame
                0x01,
                0x81,
                0x00,
                0x07,
                0x03,
                0x07,
                0x06,
                0x02,
                0x00,
                0x00,
                0x01,
                0x31,
            ]
        )
    )

    assert len(packets) == 1
    assert packets[0].functional_domain == FunctionalDomain.STATUS
    assert packets[0].attribute == 6
    assert packets[0].data == {
        Attribute.HEATING_EQUIPMENT_STATUS: 2,
        Attribute.COOLING_EQUIPMENT_STATUS: 0,
        Attribute.PROGRESSIVE_RECOVERY: 0,
        Attribute.FAN_STATUS: 1,
    }


def test_short_text_frame_does_not_desync_following_frame():
    # Regression test: TEXT consumed text_length bytes unconditionally,
    # without checking whether the frame's declared count left room for
    # them. A short TEXT frame would overshoot into the CRC byte (and
    # beyond, into the next frame), corrupting the parse position for
    # everything after it. Here the first frame declares only 2 bytes of
    # data for Identification/4 (Location, which needs 7), and is
    # followed by a fully valid Status/6 frame that must still be parsed
    # correctly.
    packets: list[Packet] = list(
        Packet.parse(
            [
                # Frame 1: truncated text (Identification/4) - malformed
                0x01,
                0x80,
                0x00,
                0x05,
                0x03,
                0x08,
                0x04,
                0x41,
                0x42,
                0x00,
                # Frame 2: valid Status/6 frame
                0x01,
                0x81,
                0x00,
                0x07,
                0x03,
                0x07,
                0x06,
                0x02,
                0x00,
                0x00,
                0x01,
                0x31,
            ]
        )
    )

    assert len(packets) == 1
    assert packets[0].functional_domain == FunctionalDomain.STATUS
    assert packets[0].attribute == 6
    assert packets[0].data == {
        Attribute.HEATING_EQUIPMENT_STATUS: 2,
        Attribute.COOLING_EQUIPMENT_STATUS: 0,
        Attribute.PROGRESSIVE_RECOVERY: 0,
        Attribute.FAN_STATUS: 1,
    }


def test_parse_truncated_buffer_does_not_raise():
    # Regression test: parse used to index into the buffer with no bounds
    # checks, so a partial frame raised IndexError (and, via
    # _AprilaireClientProtocol.data_received, killed the connection). Every
    # prefix of a valid frame - including the empty prefix - must parse
    # without raising and simply yield nothing, since none of them contain a
    # complete frame.
    frame = [1, 1, 0, 7, 3, 2, 1, 1, 2, 10, 20, 107]

    for prefix_length in range(len(frame)):
        packets: list[Packet] = list(Packet.parse(frame[:prefix_length]))

        assert packets == []


def test_parse_truncated_buffer_byte_at_a_time_reassembly():
    # A truncated buffer yields nothing, but once the full frame is
    # available (as it would be after a caller re-invokes parse with more
    # buffered data appended) it parses normally.
    frame = [1, 1, 0, 7, 3, 2, 1, 1, 2, 10, 20, 107]

    for prefix_length in range(len(frame)):
        assert list(Packet.parse(frame[:prefix_length])) == []

    packets: list[Packet] = list(Packet.parse(frame))

    assert len(packets) == 1
    assert packets[0].data == {
        Attribute.MODE: 1,
        Attribute.FAN_MODE: 2,
        Attribute.HEAT_SETPOINT: 10,
        Attribute.COOL_SETPOINT: 20,
    }


def test_parse_truncated_nack_does_not_raise():
    nack_frame = [1, 1, 0, 2, 6, 1, 0x63]

    for prefix_length in range(len(nack_frame)):
        assert list(Packet.parse(nack_frame[:prefix_length])) == []


def test_get_parseable_length_empty():
    assert Packet.get_parseable_length(b"") == 0


def test_get_parseable_length_partial_header():
    # Fewer than 4 bytes - can't even read CNT yet.
    assert Packet.get_parseable_length(bytes([1, 1, 0])) == 0


def test_get_parseable_length_partial_frame():
    frame = bytes([1, 1, 0, 7, 3, 2, 1, 1, 2, 10, 20, 107])

    for prefix_length in range(len(frame)):
        assert Packet.get_parseable_length(frame[:prefix_length]) == 0

    assert Packet.get_parseable_length(frame) == len(frame)


def test_get_parseable_length_two_frames_one_partial():
    frame = bytes([1, 1, 0, 7, 3, 2, 1, 1, 2, 10, 20, 107])

    assert Packet.get_parseable_length(frame + frame[:5]) == len(frame)


def test_get_parseable_length_two_complete_frames():
    frame = bytes([1, 1, 0, 7, 3, 2, 1, 1, 2, 10, 20, 107])

    assert Packet.get_parseable_length(frame + frame) == len(frame) * 2


def test_two_frames_coalesced_in_one_chunk_both_parsed():
    frame = [1, 1, 0, 7, 3, 2, 1, 1, 2, 10, 20, 107]

    packets: list[Packet] = list(Packet.parse(frame + frame))

    assert len(packets) == 2


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
        Attribute.HOLD_FAN_MODE: 2,
        Attribute.HOLD_HEAT_SETPOINT: 3,
        Attribute.HOLD_COOL_SETPOINT: 4,
        Attribute.HOLD_DEHUMIDIFICATION_SETPOINT: 5,
        Attribute.HOLD_END_MINUTE: 6,
        Attribute.HOLD_END_HOUR: 7,
        Attribute.HOLD_END_DATE: 8,
        Attribute.HOLD_END_MONTH: 9,
        Attribute.HOLD_END_YEAR: 10,
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

    assert packet.data == {Attribute.MAC_ADDRESS: "01:02:03:04:05:06"}


def test_identification_2_parse_zero_padded_octets():
    # Regression test: MAC octets under 0x10 used to be formatted without
    # zero-padding (e.g. "1a" -> "1a" is fine, but 0x00 -> "0" and 0x05 ->
    # "5"), so the text form of the address depended on its own octet
    # values. Spec section 8.2 defines these as fixed-width octet values.
    packets: list[Packet] = list(
        Packet.parse([1, 1, 0, 9, 3, 8, 2, 0xB4, 0x82, 0x55, 0x00, 0x1A, 0x05, 0x37])
    )

    packet = packets[0]

    assert packet.data == {Attribute.MAC_ADDRESS: "b4:82:55:00:1a:05"}


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


def test_status_2_sync_parse():
    # Regression test: the Sync attribute (spec section 7.2) has two bytes -
    # Sync and a Reserved byte - but MAPPING only had one entry, so the
    # emitted frame declared a payload count of 4 instead of the required 5
    # (3 header bytes + 2 data bytes). Verify the fixed 5-byte payload
    # parses correctly and the reserved byte is consumed without error.
    packets: list[Packet] = list(Packet.parse([1, 0, 0, 5, 1, 7, 2, 1, 0, 0xB6]))

    packet = packets[0]

    assert packet.functional_domain == FunctionalDomain.STATUS
    assert packet.attribute == 2
    assert packet.data == {Attribute.SYNCED: 1}


def test_status_2_sync_serialize():
    serialized = Packet(
        Action.WRITE,
        FunctionalDomain.STATUS,
        2,
        1,
        0,
        data={Attribute.SYNCED: 1},
    ).serialize()

    assert serialized == bytes([1, 0, 0, 5, 1, 7, 2, 1, 0, 0xB6])


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


def test_spec_section_g_write_example_serialize():
    # The worked example from spec section G: writing Fan=ON, Heat
    # Setpoint=21.0C (70F), Cool Setpoint=26.5C (80F), leaving Mode
    # unwritten (0x00 / null).
    serialized = Packet(
        Action.WRITE,
        FunctionalDomain.CONTROL,
        1,
        1,
        0,
        data={
            Attribute.MODE: 0,
            Attribute.FAN_MODE: 1,
            Attribute.HEAT_SETPOINT: 21.0,
            Attribute.COOL_SETPOINT: 26.5,
        },
    ).serialize()

    assert serialized == bytes(
        [0x01, 0x00, 0x00, 0x07, 0x01, 0x02, 0x01, 0x00, 0x01, 0x15, 0x5A, 0x46]
    )


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
            Attribute.HOLD_FAN_MODE: 2,
            Attribute.HOLD_HEAT_SETPOINT: 3,
            Attribute.HOLD_COOL_SETPOINT: 4,
            Attribute.HOLD_DEHUMIDIFICATION_SETPOINT: 5,
            Attribute.HOLD_END_MINUTE: 6,
            Attribute.HOLD_END_HOUR: 7,
            Attribute.HOLD_END_DATE: 8,
            Attribute.HOLD_END_MONTH: 9,
            Attribute.HOLD_END_YEAR: 10,
        },
    ).serialize()

    assert serialized == bytes(
        [1, 1, 0, 13, 3, 3, 4, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 42]
    )


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
        data={
            Attribute.MAC_ADDRESS: [1, 2, 3, 4, 5, 6],
            Attribute.FORCE_CONNECTION: 1,
            Attribute.CONNECTION_TYPE: 2,
        },
    ).serialize()

    assert serialized == bytes([1, 1, 0, 11, 3, 8, 2, 1, 2, 3, 4, 5, 6, 1, 2, 201])


def test_serialize_partial_write_null_defaults_other_fields():
    # Regression test: serialize() had no null path, so a mapped field
    # absent from `data` fell straight into arithmetic/bytes() as None and
    # raised TypeError - Packet(WRITE, CONTROL, 1,
    # data={HEAT_SETPOINT: 21.0}).serialize() used to raise "'<' not
    # supported between instances of 'NoneType' and 'int'" out of
    # _encode_temperature. Spec section G: writing NULL (0x00) for a field
    # leaves it unmodified - that's exactly what must happen here for MODE,
    # FAN_MODE, and COOL_SETPOINT.
    serialized = Packet(
        Action.WRITE,
        FunctionalDomain.CONTROL,
        1,
        1,
        0,
        data={Attribute.HEAT_SETPOINT: 21.0},
    ).serialize()

    assert serialized == bytes(
        [0x01, 0x00, 0x00, 0x07, 0x01, 0x02, 0x01, 0x00, 0x00, 0x15, 0x00, 0xA5]
    )
    assert len(serialized) == 12


def test_serialize_empty_data_all_fields_null():
    # Regression test: Packet(_, CONTROL, 3, data={}).serialize() used to
    # raise "'NoneType' object cannot be interpreted as an integer" from
    # bytes(payload), since HUMIDITY had no null handling either. Uses COS
    # rather than WRITE: an all-null WRITE is now rejected outright as a
    # no-op (see test_serialize_write_with_no_populated_fields_raises) -
    # this test is about the HUMIDITY null-padding itself, not about WRITE
    # specifically, and COS/READ_RESPONSE share the same serialization path.
    serialized = Packet(
        Action.COS,
        FunctionalDomain.CONTROL,
        3,
        1,
        0,
        data={},
    ).serialize()

    assert serialized == bytes([0x01, 0x00, 0x00, 0x04, 0x05, 0x02, 0x03, 0x00, 0x62])
    assert len(serialized) == 9


def test_serialize_write_with_no_populated_fields_raises():
    # A WRITE where every mapped field is absent would serialize as an
    # all-NULL payload - per spec section G that changes nothing on the
    # device, so it's a no-op write. That's never a deliberate call; it's
    # far more likely an empty `data` dict reaching here by mistake, so
    # this fails loudly instead of silently sending a packet that does
    # nothing.
    with pytest.raises(ValueError, match="no populated fields"):
        Packet(
            Action.WRITE,
            FunctionalDomain.CONTROL,
            3,
            1,
            0,
            data={},
        ).serialize()


def test_serialize_write_with_one_populated_field_does_not_raise():
    # A partial write - at least one mapped field set, the rest left to
    # null-pad - is the legitimate case this must not reject.
    serialized = Packet(
        Action.WRITE,
        FunctionalDomain.CONTROL,
        1,
        1,
        0,
        data={Attribute.HEAT_SETPOINT: 21.0},
    ).serialize()

    assert len(serialized) == 12


def test_serialize_text_null_field_occupies_full_length():
    # Regression test: Packet(WRITE, IDENTIFICATION, 5,
    # data={NAME: "TSTAT"}).serialize() used to raise "object of type
    # 'NoneType' has no len()" because LOCATION (absent from data) fell
    # through to len(None) in the TEXT branch. A null TEXT field must still
    # occupy length + 1 bytes (all zero) so the payload length stays
    # correct - a null LOCATION (length 7) must emit 8 bytes.
    serialized = Packet(
        Action.WRITE,
        FunctionalDomain.IDENTIFICATION,
        5,
        1,
        0,
        data={Attribute.NAME: "TSTAT"},
    ).serialize()

    # header(4) + action/fd/attr(3) + LOCATION null(8) + NAME(16) + crc(1)
    assert len(serialized) == 32
    payload = serialized[4:-1]
    location_bytes = payload[3:11]
    name_bytes = payload[11:27]

    assert location_bytes == bytes([0] * 8)
    assert name_bytes == b"TSTAT" + bytes([0] * 11)


def test_serialize_scheduling_4_hold_only_null_padding():
    # Concretely quoted in the defect report: once #82's newly-named bytes
    # land on top of this fix, a partially-populated Scheduling/4 write must
    # not crash and must still emit the full 10-byte payload (1 named HOLD
    # byte + 9 null-padded bytes).
    serialized = Packet(
        Action.COS,
        FunctionalDomain.SCHEDULING,
        4,
        1,
        0,
        data={Attribute.HOLD: 1},
    ).serialize()

    payload = serialized[4:-1]

    assert len(payload) == 13  # action, fd, attr + 10 data bytes
    assert payload[3:] == bytes([1] + [0] * 9)


def test_serialize_setup_1_away_available_only_null_padding():
    # Concretely quoted in the defect report: a partially-populated Setup/1
    # write must not crash and must still emit the full 44-byte payload.
    serialized = Packet(
        Action.COS,
        FunctionalDomain.SETUP,
        1,
        1,
        0,
        data={Attribute.AWAY_AVAILABLE: 1},
    ).serialize()

    payload = serialized[4:-1]

    assert len(payload) == 47  # action, fd, attr + 44 data bytes
    expected_data = [0] * 44
    expected_data[26] = 1
    assert list(payload[3:]) == expected_data


def test_serialize_identification_2_mac_address_only_no_null_needed():
    # Identification/2 maps MAC_ADDRESS plus FORCE_CONNECTION and
    # CONNECTION_TYPE (each a single null-padded byte when absent). A
    # write that only populates MAC_ADDRESS must keep working unchanged
    # and null-pad the other two.
    serialized = Packet(
        Action.READ_RESPONSE,
        FunctionalDomain.IDENTIFICATION,
        2,
        1,
        0,
        data={Attribute.MAC_ADDRESS: [1, 2, 3, 4, 5, 6]},
    ).serialize()

    payload = serialized[4:-1]

    assert len(payload) == 11  # action, fd, attr + 6 MAC bytes + 2 null
    assert list(payload[3:]) == [1, 2, 3, 4, 5, 6, 0, 0]


def test_serialize_mac_address_null_occupies_six_bytes():
    # A null MAC_ADDRESS (absent from data) must still occupy all 6 bytes,
    # not be skipped or raise, alongside the two other null-padded fields.
    serialized = Packet(
        Action.READ_RESPONSE,
        FunctionalDomain.IDENTIFICATION,
        2,
        1,
        0,
        data={},
    ).serialize()

    payload = serialized[4:-1]

    assert len(payload) == 11
    assert list(payload[3:]) == [0] * 8


def test_serialize_spec_section_g_worked_example_unchanged():
    # The exact worked example from spec section G must be byte-for-byte
    # unchanged by the null-serialization fix.
    serialized = Packet(
        Action.WRITE,
        FunctionalDomain.CONTROL,
        1,
        1,
        0,
        data={
            Attribute.MODE: 0,
            Attribute.FAN_MODE: 1,
            Attribute.HEAT_SETPOINT: 21.0,
            Attribute.COOL_SETPOINT: 26.5,
        },
    ).serialize()

    assert serialized == bytes(
        [0x01, 0x00, 0x00, 0x07, 0x01, 0x02, 0x01, 0x00, 0x01, 0x15, 0x5A, 0x46]
    )


def test_serialize_control_1_fully_populated_unchanged():
    # Fully-populated Control/1 writes (no nulls involved) must be unchanged
    # by the null-serialization fix.
    serialized = Packet(
        Action.WRITE,
        FunctionalDomain.CONTROL,
        1,
        data={
            Attribute.MODE: 0,
            Attribute.FAN_MODE: 1,
            Attribute.HEAT_SETPOINT: 21.0,
            Attribute.COOL_SETPOINT: 26.5,
        },
    ).serialize()

    assert serialized == bytes(
        [0x01, 0x00, 0x00, 0x07, 0x01, 0x02, 0x01, 0x00, 0x01, 0x15, 0x5A, 0x46]
    )


def test_serialize_wrong_type_still_raises():
    # Only absent/None means null - a genuinely wrong-typed value (e.g. a
    # string where a temperature float belongs) must still fail loudly
    # rather than being silently treated as null.
    with pytest.raises(TypeError):
        Packet(
            Action.WRITE,
            FunctionalDomain.CONTROL,
            1,
            data={Attribute.HEAT_SETPOINT: "hot"},
        ).serialize()


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


def _build_frame(action: int, functional_domain: int, attribute: int, data: list[int]):
    """Build a well-formed frame (with a correct CRC) for the given payload."""
    payload = [action, functional_domain, attribute] + data
    header = [1, 0, (len(payload) >> 8) & 0xFF, len(payload) & 0xFF]
    frame = header + payload
    frame.append(Packet._generate_crc(frame))
    return bytes(frame)


# --- Byte-alignment proof -------------------------------------------------
#
# For each newly-populated MAPPING list, build a synthetic payload where byte
# N == N (skipping MAC_ADDRESS's own N..N+5 sub-range), parse it, and assert
# that every named attribute reads back its own spec byte offset. This guards
# against an off-by-one silently mis-mapping a field to the wrong byte.


def test_setup_1_list_length_matches_spec():
    # Spec 1.1: Thermostat Installer Settings is 44 bytes (byte 0 - byte 43).
    assert len(MAPPING[Action.READ_RESPONSE][FunctionalDomain.SETUP][1]) == 44


def test_scheduling_4_list_length_matches_spec():
    # Spec 3.4: Schedule Hold is 10 bytes (byte 0 - byte 9).
    assert len(MAPPING[Action.READ_RESPONSE][FunctionalDomain.SCHEDULING][4]) == 10


def test_identification_2_list_length_matches_spec():
    # Spec 8.2: MAC Address is 8 bytes (byte 0 - byte 7), but the MAC address
    # itself is a single mapping entry spanning bytes 0-5.
    assert len(MAPPING[Action.READ_RESPONSE][FunctionalDomain.IDENTIFICATION][2]) == 3


def test_status_1_list_length_matches_spec():
    # Spec 7.1: COS Subscriptions is 29 bytes (byte 0 - byte 28).
    assert len(MAPPING[Action.READ_RESPONSE][FunctionalDomain.STATUS][1]) == 29


def test_setup_1_byte_alignment():
    packets: list[Packet] = list(Packet.parse(_build_frame(3, 1, 1, list(range(44)))))

    packet = packets[0]

    assert packet.data == {
        Attribute.TEMPERATURE_SCALE: 2,
        Attribute.CONTROL_SETUP: 4,
        Attribute.AUTO_CHANGEOVER: 12,
        Attribute.DEADBAND: 13,
        Attribute.WIRED_REMOTE_TEMPERATURE_SENSOR_INSTALLED: 14,
        Attribute.OUTDOOR_SENSOR_INSTALLED: 15,
        Attribute.RETURN_AIR_SENSOR_INSTALLED: 17,
        Attribute.AWAY_AVAILABLE: 26,
        Attribute.HEAT_BLAST_AVAILABLE: 27,
        Attribute.PROGRESSIVE_RECOVERY_AVAILABLE: 30,
        Attribute.PROGRAM_FORMAT: 33,
    }


def test_scheduling_4_byte_alignment():
    packets: list[Packet] = list(Packet.parse(_build_frame(3, 3, 4, list(range(10)))))

    packet = packets[0]

    assert packet.data == {
        Attribute.HOLD: 0,
        Attribute.HOLD_FAN_MODE: 1,
        Attribute.HOLD_HEAT_SETPOINT: 2,
        Attribute.HOLD_COOL_SETPOINT: 3,
        Attribute.HOLD_DEHUMIDIFICATION_SETPOINT: 4,
        Attribute.HOLD_END_MINUTE: 5,
        Attribute.HOLD_END_HOUR: 6,
        Attribute.HOLD_END_DATE: 7,
        Attribute.HOLD_END_MONTH: 8,
        Attribute.HOLD_END_YEAR: 9,
    }


def test_identification_2_byte_alignment():
    packets: list[Packet] = list(Packet.parse(_build_frame(3, 8, 2, list(range(8)))))

    packet = packets[0]

    assert packet.data == {
        Attribute.MAC_ADDRESS: "00:01:02:03:04:05",
        Attribute.FORCE_CONNECTION: 6,
        Attribute.CONNECTION_TYPE: 7,
    }


def test_status_1_byte_alignment():
    packets: list[Packet] = list(Packet.parse(_build_frame(3, 7, 1, list(range(29)))))

    packet = packets[0]

    assert packet.data == {
        Attribute.COS_INSTALLER_THERMOSTAT_SETTINGS: 0,
        Attribute.COS_CONTRACTOR_INFORMATION: 1,
        Attribute.COS_AIR_CLEANING_INSTALLER_SETTINGS: 2,
        Attribute.COS_HUMIDITY_CONTROL_INSTALLER_SETTINGS: 3,
        Attribute.COS_FRESH_AIR_INSTALLER_SETTINGS: 4,
        Attribute.COS_THERMOSTAT_SETPOINT_AND_MODE_SETTINGS: 5,
        Attribute.COS_DEHUMIDIFICATION_SETPOINT: 6,
        Attribute.COS_HUMIDIFICATION_SETPOINT: 7,
        Attribute.COS_FRESH_AIR_SETTING: 8,
        Attribute.COS_AIR_CLEANING_SETTINGS: 9,
        Attribute.COS_THERMOSTAT_IAQ_AVAILABLE: 10,
        Attribute.COS_SCHEDULE_SETTINGS: 11,
        Attribute.COS_AWAY_SETTINGS: 12,
        Attribute.COS_SCHEDULE_DAY: 13,
        Attribute.COS_SCHEDULE_HOLD: 14,
        Attribute.COS_HEAT_BLAST: 15,
        Attribute.COS_SERVICE_REMINDERS_STATUS: 16,
        Attribute.COS_ALERTS_STATUS: 17,
        Attribute.COS_ALERTS_SETTINGS: 18,
        Attribute.COS_BACKLIGHT_SETTINGS: 19,
        Attribute.COS_THERMOSTAT_LOCATION_AND_NAME: 20,
        # byte 21 is Reserved and intentionally absent
        Attribute.COS_CONTROLLING_SENSOR_VALUES: 22,
        Attribute.COS_OVER_THE_AIR_ODT_UPDATE_TIMEOUT: 23,
        Attribute.COS_THERMOSTAT_STATUS: 24,
        Attribute.COS_IAQ_STATUS: 25,
        Attribute.COS_MODEL_AND_REVISION: 26,
        Attribute.COS_SUPPORT_MODULE: 27,
        Attribute.COS_LOCKOUTS: 28,
    }


# --- Round-trip serialize/parse tests for newly-named fields --------------


def test_setup_1_round_trip():
    data = {
        Attribute.TEMPERATURE_SCALE: 1,
        Attribute.CONTROL_SETUP: 0,
        Attribute.AUTO_CHANGEOVER: 1,
        Attribute.DEADBAND: 2,
        Attribute.WIRED_REMOTE_TEMPERATURE_SENSOR_INSTALLED: 0,
        Attribute.OUTDOOR_SENSOR_INSTALLED: 2,
        Attribute.RETURN_AIR_SENSOR_INSTALLED: 0,
        Attribute.AWAY_AVAILABLE: 1,
        Attribute.HEAT_BLAST_AVAILABLE: 1,
        Attribute.PROGRESSIVE_RECOVERY_AVAILABLE: 0,
        Attribute.PROGRAM_FORMAT: 0,
    }

    serialized = Packet(
        Action.READ_RESPONSE, FunctionalDomain.SETUP, 1, 1, 1, data=data
    ).serialize()

    packets: list[Packet] = list(Packet.parse(serialized))

    assert packets[0].data == data


def test_scheduling_4_round_trip():
    data = {
        Attribute.HOLD: 1,
        Attribute.HOLD_FAN_MODE: 2,
        Attribute.HOLD_HEAT_SETPOINT: 21,
        Attribute.HOLD_COOL_SETPOINT: 26,
        Attribute.HOLD_DEHUMIDIFICATION_SETPOINT: 55,
        Attribute.HOLD_END_MINUTE: 30,
        Attribute.HOLD_END_HOUR: 17,
        Attribute.HOLD_END_DATE: 15,
        Attribute.HOLD_END_MONTH: 6,
        Attribute.HOLD_END_YEAR: 26,
    }

    serialized = Packet(
        Action.WRITE, FunctionalDomain.SCHEDULING, 4, 1, 1, data=data
    ).serialize()

    packets: list[Packet] = list(Packet.parse(serialized))

    assert packets[0].data == data


def test_identification_2_round_trip_with_force_connection_and_connection_type():
    data = {
        Attribute.MAC_ADDRESS: [0xB4, 0x82, 0x55, 0x01, 0x02, 0x03],
        Attribute.FORCE_CONNECTION: 1,
        Attribute.CONNECTION_TYPE: 1,
    }

    serialized = Packet(
        Action.READ_RESPONSE, FunctionalDomain.IDENTIFICATION, 2, 1, 1, data=data
    ).serialize()

    packets: list[Packet] = list(Packet.parse(serialized))

    assert packets[0].data == {
        Attribute.MAC_ADDRESS: "b4:82:55:01:02:03",
        Attribute.FORCE_CONNECTION: 1,
        Attribute.CONNECTION_TYPE: 1,
    }


def test_status_1_round_trip():
    data = {
        Attribute.COS_INSTALLER_THERMOSTAT_SETTINGS: 1,
        Attribute.COS_CONTRACTOR_INFORMATION: 0,
        Attribute.COS_AIR_CLEANING_INSTALLER_SETTINGS: 1,
        Attribute.COS_HUMIDITY_CONTROL_INSTALLER_SETTINGS: 1,
        Attribute.COS_FRESH_AIR_INSTALLER_SETTINGS: 0,
        Attribute.COS_THERMOSTAT_SETPOINT_AND_MODE_SETTINGS: 1,
        Attribute.COS_DEHUMIDIFICATION_SETPOINT: 1,
        Attribute.COS_HUMIDIFICATION_SETPOINT: 1,
        Attribute.COS_FRESH_AIR_SETTING: 0,
        Attribute.COS_AIR_CLEANING_SETTINGS: 1,
        Attribute.COS_THERMOSTAT_IAQ_AVAILABLE: 0,
        Attribute.COS_SCHEDULE_SETTINGS: 1,
        Attribute.COS_AWAY_SETTINGS: 1,
        Attribute.COS_SCHEDULE_DAY: 1,
        Attribute.COS_SCHEDULE_HOLD: 1,
        Attribute.COS_HEAT_BLAST: 0,
        Attribute.COS_SERVICE_REMINDERS_STATUS: 1,
        Attribute.COS_ALERTS_STATUS: 1,
        Attribute.COS_ALERTS_SETTINGS: 1,
        Attribute.COS_BACKLIGHT_SETTINGS: 0,
        Attribute.COS_THERMOSTAT_LOCATION_AND_NAME: 1,
        Attribute.COS_CONTROLLING_SENSOR_VALUES: 1,
        Attribute.COS_OVER_THE_AIR_ODT_UPDATE_TIMEOUT: 0,
        Attribute.COS_THERMOSTAT_STATUS: 1,
        Attribute.COS_IAQ_STATUS: 1,
        Attribute.COS_MODEL_AND_REVISION: 1,
        Attribute.COS_SUPPORT_MODULE: 0,
        Attribute.COS_LOCKOUTS: 1,
    }

    serialized = Packet(
        Action.READ_RESPONSE, FunctionalDomain.STATUS, 1, 1, 1, data=data
    ).serialize()

    packets: list[Packet] = list(Packet.parse(serialized))

    assert packets[0].data == data


# --- Value enums (const.py) -------------------------------------------------


def test_value_enums_are_int_compatible():
    # Existing callers passing raw ints must keep working.
    assert HvacMode.HEAT == 2
    assert FanMode.AUTO == 2
    assert HoldType.VACATION == 4
    assert SensorStatus.SHORT == 5
    assert HeatingEquipmentStatus.AUX_HEAT_1 == 7
    assert CoolingEquipmentStatus.COMP_1_AND_2 == 6
    assert FanStatus.ACTIVE == 1
    assert DehumidificationStatus.OVERCOOLING_TO_DEHUMIDIFY == 3
    assert HumidificationStatus.OFF == 3
    assert VentilationStatus.HIGH_RH_LOCKOUT == 5
    assert AirCleaningStatus.ACTIVE == 2
    assert ThermostatError.E5_ECM_COMMUNICATION_LOST == 5
    assert TemperatureScale.CELSIUS == 1

    # Values decoded off the wire as bare ints still round-trip through the
    # enum, e.g. a MAPPING-decoded Attribute.HEATING_EQUIPMENT_STATUS value.
    assert HeatingEquipmentStatus(7) == HeatingEquipmentStatus.AUX_HEAT_1


def test_get_simple_status_heating():
    assert get_simple_status(HeatingEquipmentStatus.NOT_ACTIVE) == SimpleStatus.IDLE
    assert get_simple_status(HeatingEquipmentStatus.EQUIPMENT_WAIT) == SimpleStatus.WAIT
    assert get_simple_status(HeatingEquipmentStatus.AUX_HEAT_1) == SimpleStatus.ON


def test_get_simple_status_cooling():
    assert get_simple_status(CoolingEquipmentStatus.NOT_ACTIVE) == SimpleStatus.IDLE
    assert get_simple_status(CoolingEquipmentStatus.STAGE_1) == SimpleStatus.ON


def test_get_simple_status_fan():
    assert get_simple_status(FanStatus.NOT_ACTIVE) == SimpleStatus.OFF
    assert get_simple_status(FanStatus.ACTIVE) == SimpleStatus.ON


def test_get_simple_status_dehumidification():
    assert (
        get_simple_status(DehumidificationStatus.WHOLE_HOME_ACTIVE) == SimpleStatus.ON
    )
    assert get_simple_status(DehumidificationStatus.OFF) == SimpleStatus.OFF


def test_get_simple_status_ventilation():
    assert get_simple_status(VentilationStatus.ACTIVE) == SimpleStatus.ON
    assert (
        get_simple_status(VentilationStatus.HIGH_TEMPERATURE_LOCKOUT)
        == SimpleStatus.IDLE
    )
    assert get_simple_status(VentilationStatus.OFF) == SimpleStatus.OFF


def test_get_simple_status_does_not_collide_across_enums():
    # Different status enums that share the same raw int value (e.g. 0 for
    # "not active") must not collide in the simple-status lookup, since
    # IntEnum members compare/hash equal to plain ints of the same value
    # across unrelated enum classes.
    assert get_simple_status(HeatingEquipmentStatus.NOT_ACTIVE) == SimpleStatus.IDLE
    assert get_simple_status(FanStatus.NOT_ACTIVE) == SimpleStatus.OFF
    assert get_simple_status(DehumidificationStatus.NOT_ACTIVE) == SimpleStatus.IDLE
