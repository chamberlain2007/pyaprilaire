from pyaprilaire.const import Action, FunctionalDomain
from pyaprilaire.packet import NackPacket, Packet

import unittest


class Test_Packet(unittest.TestCase):
    def test_invalid_action(self):
        packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 7, 1, 1, 0]))

        self.assertEqual(len(packets), 0)

    def test_invalid_functional_domain(self):
        packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 3, 17, 1, 0]))

        self.assertEqual(len(packets), 0)

    def test_unmapped(self):
        packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 3, 13, 1, 0]))

        self.assertEqual(len(packets), 0)

    def test_packet_empty_parse(self):
        packets = list(Packet.parse(bytes()))

        self.assertEqual(len(packets), 0)

    def test_packet_single_parse(self):
        packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 2, 1, 1, 107]))

        self.assertEqual(len(packets), 1)

    def test_packet_single_action(self):
        packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 2, 1, 1, 107]))

        packet = packets[0]

        self.assertEqual(packet.action, Action.READ_REQUEST)

    def test_packet_single_functional_domain(self):
        packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 2, 1, 1, 107]))

        packet = packets[0]

        self.assertEqual(packet.functional_domain, FunctionalDomain.SETUP)

    def test_packet_single_attribute(self):
        packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 2, 1, 1, 107]))

        packet = packets[0]

        self.assertEqual(packet.attribute, 1)

    def test_packet_single_extra_data(self):
        packets: list[Packet] = list(
            Packet.parse([1, 1, 0, 8, 3, 2, 1, 1, 1, 1, 1, 10, 146])
        )

        self.assertEqual(len(packets), 1)

    def test_packet_multiple_parse(self):
        packets: list[Packet] = list(
            Packet.parse([1, 1, 0, 3, 2, 1, 1, 107, 1, 2, 0, 3, 3, 3, 4, 248])
        )

        self.assertEqual(len(packets), 2)

    def test_packet_multiple_action(self):
        packets: list[Packet] = list(
            Packet.parse([1, 1, 0, 3, 2, 1, 1, 107, 1, 2, 0, 3, 3, 3, 4, 248])
        )

        packet = packets[1]

        self.assertEqual(packet.action, Action.READ_RESPONSE)

    def test_packet_multiple_functional_domain(self):
        packets: list[Packet] = list(
            Packet.parse([1, 1, 0, 3, 2, 1, 1, 107, 1, 2, 0, 3, 3, 3, 4, 248])
        )

        packet = packets[1]

        self.assertEqual(packet.functional_domain, FunctionalDomain.SCHEDULING)

    def test_packet_multiple_attribute(self):
        packets: list[Packet] = list(
            Packet.parse([1, 1, 0, 3, 2, 1, 1, 107, 1, 2, 0, 3, 3, 3, 4, 248])
        )

        packet = packets[1]

        self.assertEqual(packet.attribute, 4)

    def test_nack_parse(self):
        packets: list[Packet] = list(Packet.parse([1, 1, 0, 2, 6, 1, 0]))

        self.assertEqual(len(packets), 1)

    def test_nack_and_packet_parse(self):
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

        self.assertEqual(len(packets), 2)

    def test_nack_packet_parse(self):
        packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 6, 1, 0]))

        self.assertIsInstance(packets[0], NackPacket)

    def test_control_1_parse(self):
        packets: list[Packet] = list(
            Packet.parse([1, 1, 0, 7, 3, 2, 1, 1, 2, 10, 20, 107])
        )

        packet = packets[0]

        self.assertDictEqual(
            packet.data,
            {
                "mode": 1,
                "fan_mode": 2,
                "heat_setpoint": 10,
                "cool_setpoint": 20,
            },
        )

    def test_scheduling_4_parse(self):
        packets: list[Packet] = list(
            Packet.parse([1, 1, 0, 13, 3, 3, 4, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 42])
        )

        packet = packets[0]

        self.assertDictEqual(
            packet.data,
            {
                "hold": 1,
            },
        )

    def test_sensor_2_parse(self):
        packets: list[Packet] = list(
            Packet.parse([1, 1, 0, 11, 3, 5, 2, 1, 10, 2, 20, 3, 50, 4, 60, 12])
        )

        packet = packets[0]

        self.assertDictEqual(
            packet.data,
            {
                "indoor_temperature_controlling_sensor_status": 1,
                "indoor_temperature_controlling_sensor_value": 10,
                "outdoor_temperature_controlling_sensor_status": 2,
                "outdoor_temperature_controlling_sensor_value": 20,
                "indoor_humidity_controlling_sensor_status": 3,
                "indoor_humidity_controlling_sensor_value": 50,
                "outdoor_humidity_controlling_sensor_status": 4,
                "outdoor_humidity_controlling_sensor_value": 60,
            },
        )

    def test_identification_2_parse(self):
        packets: list[Packet] = list(
            Packet.parse([1, 1, 0, 9, 3, 8, 2, 1, 2, 3, 4, 5, 6, 176])
        )

        packet = packets[0]

        self.assertDictEqual(
            packet.data,
            {"mac_address": "1:2:3:4:5:6"},
        )

    def test_identification_4_parse(self):
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

        self.assertDictEqual(
            packet.data,
            {"location": "12345", "name": "Test Name"},
        )

    def test_decode_temperature(self):
        temperature = Packet._decode_temperature(0x15)

        self.assertEqual(temperature, 21)

    def test_decode_temperature_negative(self):
        temperature = Packet._decode_temperature(0x95)

        self.assertEqual(temperature, -21)

    def test_decode_temperature_decimal(self):
        temperature = Packet._decode_temperature(0x5A)

        self.assertEqual(temperature, 26.5)

    def test_decode_temperature_negative_decimal(self):
        temperature = Packet._decode_temperature(0xDA)

        self.assertEqual(temperature, -26.5)

    def test_decode_humidity_zero(self):
        humidity = Packet._decode_humidity(0)

        self.assertEqual(humidity, None)

    def test_decode_humidity_1(self):
        humidity = Packet._decode_humidity(1)

        self.assertEqual(humidity, 1)

    def test_decode_humidity_99(self):
        humidity = Packet._decode_humidity(99)

        self.assertEqual(humidity, 99)

    def test_decode_humidity_100(self):
        humidity = Packet._decode_humidity(100)

        self.assertEqual(humidity, None)

    def test_decode_humidity_nonzero(self):
        humidity = Packet._decode_humidity(50)

        self.assertEqual(humidity, 50)

    def test_decode_humidity_negative(self):
        humidity = Packet._decode_humidity(-50)

        self.assertEqual(humidity, None)

    def test_encode_temperature(self):
        encoded_temperature = Packet._encode_temperature(21)

        self.assertEqual(encoded_temperature, 0x15)

    def test_encode_temperature_fraction(self):
        encoded_temperature = Packet._encode_temperature(26.5)

        self.assertEqual(encoded_temperature, 0x5A)

    def test_encode_temperature_negative(self):
        encoded_temperature = Packet._encode_temperature(-21)

        self.assertEqual(encoded_temperature, 0x95)

    def test_encode_temperature_negative_fraction(self):
        encoded_temperature = Packet._encode_temperature(-26.5)

        self.assertEqual(encoded_temperature, 0xDA)

    def test_serialize_nack(self):
        serialized = NackPacket(2).serialize()

        self.assertSequenceEqual(
            serialized,
            [1, 0, 0, 2, 6, 2, 227],
        )

    def test_serialize_raw(self):
        serialized = Packet(
            Action.READ_REQUEST, FunctionalDomain.CONTROL, 1, 1, 1, raw_data=[1, 2, 3]
        ).serialize()

        self.assertSequenceEqual(
            serialized,
            [1, 1, 0, 6, 2, 2, 1, 1, 2, 3, 133],
        )

    def test_serialize_single_packet_no_data(self):
        serialized = Packet(
            Action.READ_REQUEST,
            FunctionalDomain.CONTROL,
            1,
            1,
            1,
        ).serialize()

        self.assertSequenceEqual(
            serialized,
            [1, 1, 0, 3, 2, 2, 1, 70],
        )

    def test_serialize_single_packet_no_data(self):
        serialized = Packet(
            Action.READ_REQUEST,
            FunctionalDomain.CONTROL,
            1,
            1,
            1,
        ).serialize()

        self.assertSequenceEqual(
            serialized,
            [1, 1, 0, 3, 2, 2, 1, 70],
        )

    def test_control_1_serialize(self):
        serialized = Packet(
            Action.READ_RESPONSE,
            FunctionalDomain.CONTROL,
            1,
            1,
            1,
            data={
                "mode": 1,
                "fan_mode": 2,
                "heat_setpoint": 10,
                "cool_setpoint": 20,
            },
        ).serialize()

        self.assertSequenceEqual(serialized, [1, 1, 0, 7, 3, 2, 1, 1, 2, 10, 20, 107])

    def test_scheduling_4_serialize(self):
        serialized = Packet(
            Action.READ_RESPONSE,
            FunctionalDomain.SCHEDULING,
            4,
            1,
            1,
            data={
                "hold": 1,
            },
        ).serialize()

        self.assertSequenceEqual(
            serialized, [1, 1, 0, 13, 3, 3, 4, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 55]
        )

    def test_sensor_2_serialize(self):
        serialized = Packet(
            Action.READ_RESPONSE,
            FunctionalDomain.SENSORS,
            2,
            1,
            1,
            data={
                "indoor_temperature_controlling_sensor_status": 1,
                "indoor_temperature_controlling_sensor_value": 10,
                "outdoor_temperature_controlling_sensor_status": 2,
                "outdoor_temperature_controlling_sensor_value": 20,
                "indoor_humidity_controlling_sensor_status": 3,
                "indoor_humidity_controlling_sensor_value": 50,
                "outdoor_humidity_controlling_sensor_status": 4,
                "outdoor_humidity_controlling_sensor_value": 60,
            },
        ).serialize()

        self.assertSequenceEqual(
            serialized, [1, 1, 0, 11, 3, 5, 2, 1, 10, 2, 20, 3, 50, 4, 60, 12]
        )

    def test_identification_2_serialize(self):
        serialized = Packet(
            Action.READ_RESPONSE,
            FunctionalDomain.IDENTIFICATION,
            2,
            1,
            1,
            data={"mac_address": [1, 2, 3, 4, 5, 6]},
        ).serialize()

        self.assertSequenceEqual(
            serialized, [1, 1, 0, 9, 3, 8, 2, 1, 2, 3, 4, 5, 6, 176]
        )

    def test_identification_4_serialize(self):
        serialized = Packet(
            Action.READ_RESPONSE,
            FunctionalDomain.IDENTIFICATION,
            4,
            1,
            1,
            data={"location": "12345", "name": "Test Name"},
        ).serialize()

        self.assertSequenceEqual(
            serialized,
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
            ],
        )
