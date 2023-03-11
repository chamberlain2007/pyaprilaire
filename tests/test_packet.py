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
        packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 2, 1, 1, 0]))

        self.assertEqual(len(packets), 1)

    def test_packet_single_action(self):
        packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 2, 1, 1, 0]))

        packet = packets[0]

        self.assertEqual(packet.action, Action.READ_REQUEST)

    def test_packet_single_functional_domain(self):
        packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 2, 1, 1, 0]))

        packet = packets[0]

        self.assertEqual(packet.functional_domain, FunctionalDomain.SETUP)

    def test_packet_single_attribute(self):
        packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 2, 1, 1, 0]))

        packet = packets[0]

        self.assertEqual(packet.attribute, 1)

    def test_packet_multiple_parse(self):
        packets: list[Packet] = list(
            Packet.parse([1, 1, 0, 3, 2, 1, 1, 0, 1, 2, 0, 3, 3, 3, 4, 0])
        )

        self.assertEqual(len(packets), 2)

    def test_packet_multiple_action(self):
        packets: list[Packet] = list(
            Packet.parse([1, 1, 0, 3, 2, 1, 1, 0, 1, 2, 0, 3, 3, 3, 4, 0])
        )

        packet = packets[1]

        self.assertEqual(packet.action, Action.READ_RESPONSE)

    def test_packet_multiple_functional_domain(self):
        packets: list[Packet] = list(
            Packet.parse([1, 1, 0, 3, 2, 1, 1, 0, 1, 2, 0, 3, 3, 3, 4, 0])
        )

        packet = packets[1]

        self.assertEqual(packet.functional_domain, FunctionalDomain.SCHEDULING)

    def test_packet_multiple_attribute(self):
        packets: list[Packet] = list(
            Packet.parse([1, 1, 0, 3, 2, 1, 1, 0, 1, 2, 0, 3, 3, 3, 4, 0])
        )

        packet = packets[1]

        self.assertEqual(packet.attribute, 4)

    def test_nack_parse(self):
        packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 6, 1, 0]))

        self.assertEqual(len(packets), 1)

    def test_nack_packet(self):
        packets: list[Packet] = list(Packet.parse([1, 1, 0, 3, 6, 1, 0]))

        self.assertIsInstance(packets[0], NackPacket)

    def test_control_1_parse(self):
        packets: list[Packet] = list(
            Packet.parse([1, 1, 0, 7, 3, 2, 1, 1, 2, 10, 20, 0])
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
            Packet.parse([1, 1, 0, 13, 3, 3, 4, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 0])
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
            Packet.parse([1, 1, 0, 11, 3, 5, 2, 1, 10, 2, 20, 3, 50, 4, 60, 0])
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
            Packet.parse([1, 1, 0, 9, 3, 8, 2, 1, 2, 3, 4, 5, 6, 0])
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
                    0,
                ]
            )
        )

        packet = packets[0]

        self.assertDictEqual(
            packet.data,
            {"location": "12345", "name": "Test Name"},
        )

    def test_serialize_nack(self):
        serialized = NackPacket(2).serialize()

        self.assertSequenceEqual(serialized, [1, 0, 0, 2, 6, 2, 227])
