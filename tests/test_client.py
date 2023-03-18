from pyaprilaire.client import _AprilaireClientProtocol
from pyaprilaire.const import Action, FunctionalDomain
from pyaprilaire.packet import Packet

import asyncio
import logging

import unittest
from unittest.mock import patch, AsyncMock, Mock


class Test_Protocol(unittest.IsolatedAsyncioTestCase):
    def patch_socket(func):
        async def wrapper(*args, **kwargs):
            state_changed_mock = Mock()
            create_connection_mock = AsyncMock()
            create_protocol_mock = Mock(spec=Protocol)

            with (
                patch(
                    "asyncio.BaseEventLoop.create_connection",
                    new=create_connection_mock,
                ),
                patch(
                    "pyaprilaire.socket_client.SocketClient.state_changed",
                    new=state_changed_mock,
                ),
                patch(
                    "pyaprilaire.socket_client.SocketClient.create_protocol",
                    new=create_protocol_mock,
                ),
            ):
                await func(*args, **kwargs)

        return wrapper

    def setUp(self):
        self.logger = logging.getLogger()
        self.logger.propagate = False

        self.data_received_mock = AsyncMock()
        self.reconnect_action_mock = AsyncMock()

        self.protocol = _AprilaireClientProtocol(
            self.data_received_mock, self.reconnect_action_mock, self.logger
        )

    def test_connection_made(self):
        self.protocol._queue_loop = AsyncMock()
        self.protocol._update_status = AsyncMock()

        self.protocol.connection_made(None)

        self.assertEqual(self.protocol._queue_loop.call_count, 1)
        self.assertEqual(self.protocol._update_status.call_count, 1)

    async def test_update_status(self):
        sleep_mock = AsyncMock()

        with patch("asyncio.sleep", new=sleep_mock):
            await self.protocol._update_status()

        self.assertEqual(self.protocol.packet_queue.qsize(), 7)
        self.assertEqual(sleep_mock.call_count, 1)

    def test_data_received(self):
        self.protocol.data_received(bytes([1, 1, 0, 7, 3, 2, 1, 1, 2, 10, 20, 107]))

        self.assertEqual(self.data_received_mock.call_count, 1)

        (functional_domain, attribute, data) = self.data_received_mock.call_args[0]

        self.assertEqual(functional_domain, FunctionalDomain.CONTROL)
        self.assertEqual(attribute, 1)
        self.assertDictEqual(
            data,
            {
                "mode": 1,
                "fan_mode": 2,
                "heat_setpoint": 10,
                "cool_setpoint": 20,
            },
        )

    def test_data_received_nack(self):
        self.protocol.data_received(bytes([1, 1, 0, 2, 6, 1, 0]))

        self.assertEqual(self.data_received_mock.call_count, 0)

    def test_data_received_error(self):
        crc = Packet._generate_crc([1, 1, 0, 4, 3, 7, 8, 2])
        self.protocol.data_received(bytes([1, 1, 0, 4, 3, 7, 8, 2, 149]))

        self.assertEqual(self.data_received_mock.call_count, 1)

        (functional_domain, attribute, data) = self.data_received_mock.call_args[0]

        self.assertEqual(functional_domain, FunctionalDomain.STATUS)
        self.assertEqual(attribute, 8)
        self.assertDictEqual(
            data,
            {
                "error": 2,
            },
        )

    def test_mode_re_read(self):
        self.protocol.read_control = AsyncMock()

        self.protocol.data_received(bytes([1, 1, 0, 7, 5, 2, 1, 1, 2, 10, 20, 127]))

        self.assertEqual(self.protocol.read_control.call_count, 1)

    def test_connection_lost(self):
        self.protocol.connection_lost(None)

        self.assertEqual(self.data_received_mock.call_count, 1)

        (functional_domain, attribute, data) = self.data_received_mock.call_args[0]

        self.assertEqual(functional_domain, FunctionalDomain.NONE)
        self.assertEqual(attribute, 0)
        self.assertDictEqual(
            data,
            {
                "available": False,
            },
        )

    def test_get_sequence(self):
        sequence = self.protocol._get_sequence()
        self.assertEqual(sequence, 1)

        sequence = self.protocol._get_sequence()
        self.assertEqual(sequence, 2)

        self.protocol.sequence = 127
        sequence = self.protocol._get_sequence()
        self.assertEqual(sequence, 0)

        sequence = self.protocol._get_sequence()
        self.assertEqual(sequence, 1)

    async def test_send_packet(self):
        self.protocol.packet_queue.put = AsyncMock()
        self.protocol.packet_queue.put_nowait = Mock()

        original_packet = Packet(
            Action.WRITE,
            FunctionalDomain.CONTROL,
            1,
            data={
                "mode": 1,
                "fan_mode": 0,
                "heat_setpoint": 0,
                "cool_setpoint": 0,
            },
        )

        await self.protocol._send_packet(original_packet)

        self.assertEqual(self.protocol.packet_queue.put.call_count, 1)

        (sent_packet) = self.protocol.packet_queue.put.call_args[0][0]

        self.assertEqual(original_packet, sent_packet)

    def assertPacketQueueContains(self, packet: Packet):
        queue_items = list(self.protocol.packet_queue._queue)

        self.assertEqual(any(qp == packet for qp in queue_items), True)

    async def test_read_sensors(self):
        await self.protocol.read_sensors()

        self.assertPacketQueueContains(
            Packet(Action.READ_REQUEST, FunctionalDomain.SENSORS, 2)
        )

    async def test_read_control(self):
        await self.protocol.read_control()

        self.assertPacketQueueContains(
            Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1)
        )

    async def test_read_scheduling(self):
        await self.protocol.read_scheduling()

        self.assertPacketQueueContains(
            Packet(Action.READ_REQUEST, FunctionalDomain.SCHEDULING, 4)
        )

    async def test_update_mode(self):
        await self.protocol.update_mode(1)

        self.assertPacketQueueContains(
            Packet(
                Action.WRITE,
                FunctionalDomain.CONTROL,
                1,
                data={
                    "mode": 1,
                    "fan_mode": 0,
                    "heat_setpoint": 0,
                    "cool_setpoint": 0,
                },
            )
        )

    async def test_update_fan_mode(self):
        await self.protocol.update_fan_mode(1)

        self.assertPacketQueueContains(
            Packet(
                Action.WRITE,
                FunctionalDomain.CONTROL,
                1,
                data={
                    "mode": 0,
                    "fan_mode": 1,
                    "heat_setpoint": 0,
                    "cool_setpoint": 0,
                },
            )
        )

    async def test_update_setpoint(self):
        await self.protocol.update_setpoint(10, 20)

        self.assertPacketQueueContains(
            Packet(
                Action.WRITE,
                FunctionalDomain.CONTROL,
                1,
                data={
                    "mode": 0,
                    "fan_mode": 0,
                    "heat_setpoint": 20,
                    "cool_setpoint": 10,
                },
            )
        )

    async def test_set_hold(self):
        await self.protocol.set_hold(1)

        self.assertPacketQueueContains(
            Packet(
                Action.WRITE,
                FunctionalDomain.SCHEDULING,
                4,
                data={
                    "hold": 1,
                },
            )
        )

    async def test_sync(self):
        await self.protocol.sync()

        self.assertPacketQueueContains(
            Packet(
                Action.WRITE,
                FunctionalDomain.STATUS,
                2,
                data={
                    "synced": 1,
                },
            )
        )

    async def test_configure_cos(self):
        pass

    async def test_read_mac_address(self):
        await self.protocol.read_mac_address()

        self.assertPacketQueueContains(
            Packet(
                Action.READ_REQUEST,
                FunctionalDomain.IDENTIFICATION,
                2,
            )
        )

    async def test_read_thermostat_status(self):
        await self.protocol.read_thermostat_status()

        self.assertPacketQueueContains(
            Packet(
                Action.READ_REQUEST,
                FunctionalDomain.CONTROL,
                7,
            )
        )

    async def test_read_thermostat_name(self):
        await self.protocol.read_thermostat_name()

        self.assertPacketQueueContains(
            Packet(
                Action.READ_REQUEST,
                FunctionalDomain.IDENTIFICATION,
                5,
            )
        )

    def test_empty_packet_queue(self):
        self.protocol.packet_queue.put_nowait({})
        self.protocol.packet_queue.put_nowait({})

        self.assertEqual(self.protocol.packet_queue.qsize(), 2)

        self.protocol._empty_packet_queue()

        self.assertEqual(self.protocol.packet_queue.qsize(), 0)

    def test_empty_packet_queue_error(self):
        self.protocol.packet_queue.get_nowait = Mock(side_effect=Exception)

        self.protocol.packet_queue.put_nowait({})
        self.protocol.packet_queue.put_nowait({})

        self.assertEqual(self.protocol.packet_queue.qsize(), 2)

        self.protocol._empty_packet_queue()

        self.assertEqual(self.protocol.packet_queue.qsize(), 2)
