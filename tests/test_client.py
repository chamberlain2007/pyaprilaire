from pyaprilaire.client import _AprilaireClientProtocol, AprilaireClient
from pyaprilaire.const import Action, FunctionalDomain
from pyaprilaire.packet import Packet

import asyncio
import logging

import unittest
from unittest.mock import patch, AsyncMock, Mock


class Test_Protocol(unittest.IsolatedAsyncioTestCase):
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

        self.assertEqual(self.protocol.packet_queue.qsize(), 9)
        self.assertEqual(sleep_mock.call_count, 1)

    async def test_queue_loop(self):
        await self.protocol.read_control()
        await self.protocol.read_scheduling()

        sleep_mock = AsyncMock()
        self.protocol.transport = Mock(asyncio.Transport)

        with patch("asyncio.sleep", new=sleep_mock):
            await self.protocol._queue_loop(loop_count=1)

        self.assertEqual(sleep_mock.call_count, 1)
        self.assertEqual(self.protocol.transport.write.call_count, 2)

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
        with self.assertLogs(self.logger, level="ERROR") as cm:
            self.protocol.data_received(bytes([1, 1, 0, 2, 6, 1, 0]))

        self.assertEqual(cm.output, ["ERROR:root:Received NACK for attribute 1"])

        self.assertEqual(self.data_received_mock.call_count, 0)

    def test_data_received_error(self):
        with self.assertLogs(self.logger, level="ERROR") as cm:
            self.protocol.data_received(bytes([1, 1, 0, 4, 3, 7, 8, 2, 149]))

        self.assertEqual(cm.output, ["ERROR:root:Thermostat error: 2"])

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


class Test_Client(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = logging.getLogger()
        self.logger.propagate = False

        self.data_received_mock = Mock()

        self.client = AprilaireClient(
            None, None, self.data_received_mock, self.logger, 10, 10
        )
        self.client.protocol = _AprilaireClientProtocol(Mock(), Mock(), self.logger)

    def test_create_protocol(self):
        protocol = self.client.create_protocol()

        self.assertIsInstance(protocol, _AprilaireClientProtocol)

    async def test_data_received(self):
        functional_domain = FunctionalDomain.CONTROL
        attribute = 1
        data = {"testKey": "testValue"}

        loop = asyncio.get_event_loop()
        future = loop.create_future()

        future_key = (functional_domain, attribute)

        if future_key not in self.client.futures:
            self.client.futures[future_key] = []

        self.client.futures[future_key].append(future)

        await self.client.data_received(functional_domain, attribute, data)

        self.assertEqual(self.data_received_mock.call_count, 1)
        self.assertEqual(self.data_received_mock.call_args[0][0], data)

        self.assertEqual(future.result(), data)

    async def test_data_received_empty(self):
        await self.client.data_received(None, None, None)

    async def test_data_received_state_error(self):
        functional_domain = FunctionalDomain.CONTROL
        attribute = 1

        loop = asyncio.get_event_loop()
        future = loop.create_future()

        future_key = (functional_domain, attribute)

        if future_key not in self.client.futures:
            self.client.futures[future_key] = []

        self.client.futures[future_key].append(future)

        future.set_result({})

        await self.client.data_received(functional_domain, attribute, {})

    def test_state_changed(self):
        self.client.connected = True
        self.client.stopped = True
        self.client.reconnecting = True

        self.client.state_changed()

        self.assertEqual(self.data_received_mock.call_count, 1)
        self.assertEqual(
            self.data_received_mock.call_args[0][0],
            {"connected": True, "stopped": True, "reconnecting": True},
        )

    def assertPacketQueueContains(self, packet: Packet):
        queue_items = list(self.client.protocol.packet_queue._queue)

        self.assertEqual(any(qp == packet for qp in queue_items), True)

    async def test_read_sensors(self):
        await self.client.read_sensors()

        self.assertPacketQueueContains(
            Packet(Action.READ_REQUEST, FunctionalDomain.SENSORS, 2)
        )

    async def test_read_control(self):
        await self.client.read_control()

        self.assertPacketQueueContains(
            Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1)
        )

    async def test_read_scheduling(self):
        await self.client.read_scheduling()

        self.assertPacketQueueContains(
            Packet(Action.READ_REQUEST, FunctionalDomain.SCHEDULING, 4)
        )

    async def test_update_mode(self):
        await self.client.update_mode(1)

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
        await self.client.update_fan_mode(1)

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
        await self.client.update_setpoint(10, 20)

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
        await self.client.set_hold(1)

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

    async def test_set_dehumidification_setpoint(self):
        await self.client.set_dehumidification_setpoint(50)

        self.assertPacketQueueContains(
            Packet(
                Action.WRITE,
                FunctionalDomain.CONTROL,
                3,
                data={
                    "dehumidification_setpoint": 50,
                },
            )
        )

    async def test_set_humidification_setpoint(self):
        await self.client.set_humidification_setpoint(50)

        self.assertPacketQueueContains(
            Packet(
                Action.WRITE,
                FunctionalDomain.CONTROL,
                4,
                data={
                    "humidification_setpoint": 50,
                },
            )
        )

    async def test_set_fresh_air(self):
        await self.client.set_fresh_air(1, 3)

        self.assertPacketQueueContains(
            Packet(
                Action.WRITE,
                FunctionalDomain.CONTROL,
                5,
                data={
                    "fresh_air_mode": 1,
                    "fresh_air_event": 3,
                },
            )
        )

    async def test_set_air_cleaning(self):
        await self.client.set_air_cleaning(1, 3)

        self.assertPacketQueueContains(
            Packet(
                Action.WRITE,
                FunctionalDomain.CONTROL,
                6,
                data={
                    "air_cleaning_mode": 1,
                    "air_cleaning_event": 3,
                },
            )
        )

    async def test_sync(self):
        await self.client.sync()

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
        await self.client.read_mac_address()

        self.assertPacketQueueContains(
            Packet(
                Action.READ_REQUEST,
                FunctionalDomain.IDENTIFICATION,
                2,
            )
        )

    async def test_read_thermostat_status(self):
        await self.client.read_thermostat_status()

        self.assertPacketQueueContains(
            Packet(
                Action.READ_REQUEST,
                FunctionalDomain.CONTROL,
                7,
            )
        )

    async def test_read_thermostat_name(self):
        await self.client.read_thermostat_name()

        self.assertPacketQueueContains(
            Packet(
                Action.READ_REQUEST,
                FunctionalDomain.IDENTIFICATION,
                5,
            )
        )

    async def test_wait_for_response_success(self):
        wait_for_mock = AsyncMock(return_value=True)

        with patch("asyncio.wait_for", new=wait_for_mock):
            wait_for_response_result = await self.client.wait_for_response(
                FunctionalDomain.CONTROL, 1, 1
            )

        self.assertEqual(wait_for_response_result, True)

    async def test_wait_for_response_timeout(self):
        wait_for_mock = AsyncMock(side_effect=asyncio.exceptions.TimeoutError)

        with (
            patch("asyncio.wait_for", new=wait_for_mock),
            self.assertLogs(self.logger, level="ERROR") as cm,
        ):
            wait_for_response_result = await self.client.wait_for_response(
                FunctionalDomain.CONTROL, 1, 1
            )

        self.assertEqual(cm.output, ["ERROR:root:Hit timeout of 1 waiting for 2, 1"])

        self.assertEqual(wait_for_response_result, None)

    async def test_reconnect_with_delay(self):
        reconnect_mock = AsyncMock()

        with patch(
            "pyaprilaire.socket_client.SocketClient._reconnect", new=reconnect_mock
        ):
            await self.client._reconnect_with_delay()

            self.assertEqual(reconnect_mock.call_count, 1)
            self.assertEqual(
                reconnect_mock.call_args[0][0],
                self.client.retry_connection_interval,
            )
