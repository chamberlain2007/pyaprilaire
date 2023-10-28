import asyncio
import logging
import tracemalloc
from unittest.mock import AsyncMock, Mock, patch

import pytest

from pyaprilaire.client import AprilaireClient, _AprilaireClientProtocol
from pyaprilaire.const import Action, Attribute, FunctionalDomain
from pyaprilaire.packet import Packet

tracemalloc.start()


@pytest.fixture
def logger():
    logger = logging.getLogger()
    logger.propagate = False

    return logger


@pytest.fixture
def protocol(event_loop, logger):
    data_received_callback = AsyncMock()
    reconnect_action = AsyncMock()

    return _AprilaireClientProtocol(data_received_callback, reconnect_action, logger)


@pytest.fixture
def client(event_loop, logger, protocol):
    data_received_callback = Mock()

    client = AprilaireClient(None, None, data_received_callback, logger, 10, 10)

    client.protocol = protocol

    return client


def test_protocol_connection_made(protocol: _AprilaireClientProtocol):
    protocol._queue_loop = AsyncMock()
    protocol._update_status = AsyncMock()

    protocol.connection_made(None)

    assert protocol._queue_loop.call_count == 1
    assert protocol._update_status.call_count == 1


async def test_protocol_update_status(protocol: _AprilaireClientProtocol):
    sleep_mock = AsyncMock()

    with patch("asyncio.sleep", new=sleep_mock):
        await protocol._update_status()

    assert protocol.packet_queue.qsize() == 9
    assert sleep_mock.call_count == 1


async def test_protocol_queue_loop(protocol: _AprilaireClientProtocol):
    await protocol.read_control()
    await protocol.read_scheduling()

    sleep_mock = AsyncMock()
    protocol.transport = Mock(asyncio.Transport)

    with patch("asyncio.sleep", new=sleep_mock):
        await protocol._queue_loop(loop_count=1)

    assert sleep_mock.call_count == 1
    assert protocol.transport.write.call_count == 2


def test_protocol_data_received(protocol: _AprilaireClientProtocol):
    protocol.data_received(bytes([1, 1, 0, 7, 3, 2, 1, 1, 2, 10, 20, 107]))

    assert protocol.data_received_callback.call_count == 1

    (functional_domain, attribute, data) = protocol.data_received_callback.call_args[0]

    assert functional_domain == FunctionalDomain.CONTROL
    assert attribute == 1
    assert data == {
        Attribute.MODE: 1,
        Attribute.FAN_MODE: 2,
        Attribute.HEAT_SETPOINT: 10,
        Attribute.COOL_SETPOINT: 20,
    }


def test_protocol_data_received_nack(protocol: _AprilaireClientProtocol):
    protocol.data_received(bytes([1, 1, 0, 2, 6, 1, 0]))

    assert protocol.data_received_callback.call_count == 0


def test_protocol_data_received_error(protocol: _AprilaireClientProtocol):
    protocol.data_received(bytes([1, 1, 0, 4, 3, 7, 8, 2, 149]))

    assert protocol.data_received_callback.call_count == 1

    (functional_domain, attribute, data) = protocol.data_received_callback.call_args[0]

    assert functional_domain == FunctionalDomain.STATUS
    assert attribute == 8
    assert data == {
        "error": 2,
    }


def test_protocol_mode_re_read(protocol: _AprilaireClientProtocol):
    protocol.read_control = AsyncMock()

    protocol.data_received(bytes([1, 1, 0, 7, 5, 2, 1, 1, 2, 10, 20, 127]))

    assert protocol.read_control.call_count == 1


def test_protocol_connection_lost(protocol: _AprilaireClientProtocol):
    protocol.connection_lost(None)

    assert protocol.data_received_callback.call_count == 1

    (functional_domain, attribute, data) = protocol.data_received_callback.call_args[0]

    assert functional_domain == FunctionalDomain.NONE
    assert attribute == 0
    assert data == {
        "available": False,
    }


def test_protocol_get_sequence(protocol: _AprilaireClientProtocol):
    sequence = protocol._get_sequence()
    assert sequence == 1

    sequence = protocol._get_sequence()
    assert sequence == 2

    protocol.sequence = 127
    sequence = protocol._get_sequence()
    assert sequence == 0

    sequence = protocol._get_sequence()
    assert sequence == 1


async def test_protocol_send_packet(protocol: _AprilaireClientProtocol):
    protocol.packet_queue.put = AsyncMock()
    protocol.packet_queue.put_nowait = Mock()

    original_packet = Packet(
        Action.WRITE,
        FunctionalDomain.CONTROL,
        1,
        data={
            Attribute.MODE: 1,
            Attribute.FAN_MODE: 0,
            Attribute.HEAT_SETPOINT: 0,
            Attribute.COOL_SETPOINT: 0,
        },
    )

    await protocol._send_packet(original_packet)

    assert protocol.packet_queue.put.call_count == 1

    (sent_packet) = protocol.packet_queue.put.call_args[0][0]

    assert original_packet == sent_packet


def assertPacketQueueContains(protocol: _AprilaireClientProtocol, packet: Packet):
    queue_items = list(protocol.packet_queue._queue)

    assert any(qp == packet for qp in queue_items) == True


async def test_protocol_read_sensors(protocol: _AprilaireClientProtocol):
    await protocol.read_sensors()

    assertPacketQueueContains(
        protocol, Packet(Action.READ_REQUEST, FunctionalDomain.SENSORS, 2)
    )


async def test_protocol_read_control(protocol: _AprilaireClientProtocol):
    await protocol.read_control()

    assertPacketQueueContains(
        protocol, Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1)
    )


async def test_protocol_read_scheduling(protocol: _AprilaireClientProtocol):
    await protocol.read_scheduling()

    assertPacketQueueContains(
        protocol, Packet(Action.READ_REQUEST, FunctionalDomain.SCHEDULING, 4)
    )


async def test_protocol_update_mode(protocol: _AprilaireClientProtocol):
    await protocol.update_mode(1)

    assertPacketQueueContains(
        protocol,
        Packet(
            Action.WRITE,
            FunctionalDomain.CONTROL,
            1,
            data={
                Attribute.MODE: 1,
                Attribute.FAN_MODE: 0,
                Attribute.HEAT_SETPOINT: 0,
                Attribute.COOL_SETPOINT: 0,
            },
        ),
    )


async def test_protocol_update_fan_mode(protocol: _AprilaireClientProtocol):
    await protocol.update_fan_mode(1)

    assertPacketQueueContains(
        protocol,
        Packet(
            Action.WRITE,
            FunctionalDomain.CONTROL,
            1,
            data={
                Attribute.MODE: 0,
                Attribute.FAN_MODE: 1,
                Attribute.HEAT_SETPOINT: 0,
                Attribute.COOL_SETPOINT: 0,
            },
        ),
    )


async def test_protocol_update_setpoint(protocol: _AprilaireClientProtocol):
    await protocol.update_setpoint(10, 20)

    assertPacketQueueContains(
        protocol,
        Packet(
            Action.WRITE,
            FunctionalDomain.CONTROL,
            1,
            data={
                Attribute.MODE: 0,
                Attribute.FAN_MODE: 0,
                Attribute.HEAT_SETPOINT: 20,
                Attribute.COOL_SETPOINT: 10,
            },
        ),
    )


async def test_protocol_set_hold(protocol: _AprilaireClientProtocol):
    await protocol.set_hold(1)

    assertPacketQueueContains(
        protocol,
        Packet(
            Action.WRITE,
            FunctionalDomain.SCHEDULING,
            4,
            data={
                Attribute.HOLD: 1,
            },
        ),
    )


async def test_protocol_sync(protocol: _AprilaireClientProtocol):
    await protocol.sync()

    assertPacketQueueContains(
        protocol,
        Packet(
            Action.WRITE,
            FunctionalDomain.STATUS,
            2,
            data={
                Attribute.SYNCED: 1,
            },
        ),
    )


async def test_protocol_configure_cos(protocol: _AprilaireClientProtocol):
    pass


async def test_protocol_read_mac_address(protocol: _AprilaireClientProtocol):
    await protocol.read_mac_address()

    assertPacketQueueContains(
        protocol,
        Packet(
            Action.READ_REQUEST,
            FunctionalDomain.IDENTIFICATION,
            2,
        ),
    )


async def test_protocol_read_thermostat_status(protocol: _AprilaireClientProtocol):
    await protocol.read_thermostat_status()

    assertPacketQueueContains(
        protocol,
        Packet(
            Action.READ_REQUEST,
            FunctionalDomain.CONTROL,
            7,
        ),
    )


async def test_protocol_read_thermostat_name(protocol: _AprilaireClientProtocol):
    await protocol.read_thermostat_name()

    assertPacketQueueContains(
        protocol,
        Packet(
            Action.READ_REQUEST,
            FunctionalDomain.IDENTIFICATION,
            5,
        ),
    )


def test_protocol_empty_packet_queue(protocol: _AprilaireClientProtocol):
    protocol.packet_queue.put_nowait({})
    protocol.packet_queue.put_nowait({})

    assert protocol.packet_queue.qsize() == 2

    protocol._empty_packet_queue()

    assert protocol.packet_queue.qsize() == 0


def test_protocol_empty_packet_queue_error(protocol: _AprilaireClientProtocol):
    protocol.packet_queue.get_nowait = Mock(side_effect=Exception)

    protocol.packet_queue.put_nowait({})
    protocol.packet_queue.put_nowait({})

    assert protocol.packet_queue.qsize() == 2

    protocol._empty_packet_queue()

    assert protocol.packet_queue.qsize() == 2


def test_client_create_protocol(client: AprilaireClient):
    protocol = client.create_protocol()

    assert isinstance(protocol, _AprilaireClientProtocol)


async def test_client_data_received(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    functional_domain = FunctionalDomain.CONTROL
    attribute = 1
    data = {"testKey": "testValue"}

    loop = asyncio.get_event_loop()
    future = loop.create_future()

    future_key = (functional_domain, attribute)

    if future_key not in client.futures:
        client.futures[future_key] = []

    client.futures[future_key].append(future)

    await client.data_received(functional_domain, attribute, data)

    assert client.data_received_callback.call_count == 1
    assert client.data_received_callback.call_args[0][0] == data

    assert future.result() == data


async def test_client_data_received_empty(client: AprilaireClient):
    await client.data_received(None, None, None)


async def test_client_data_received_state_error(client: AprilaireClient):
    functional_domain = FunctionalDomain.CONTROL
    attribute = 1

    loop = asyncio.get_event_loop()
    future = loop.create_future()

    future_key = (functional_domain, attribute)

    if future_key not in client.futures:
        client.futures[future_key] = []

    client.futures[future_key].append(future)

    future.set_result({})

    await client.data_received(functional_domain, attribute, {})


def test_client_state_changed(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    client.connected = True
    client.stopped = True
    client.reconnecting = True

    client.state_changed()

    assert client.data_received_callback.call_count == 1
    assert client.data_received_callback.call_args[0][0] == {
        Attribute.CONNECTED: True,
        Attribute.STOPPED: True,
        Attribute.RECONNECTING: True,
    }


def assertPacketQueueContains(protocol: _AprilaireClientProtocol, packet: Packet):
    queue_items = list(protocol.packet_queue._queue)

    assert any(qp == packet for qp in queue_items) == True


async def test_client_read_sensors(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    await client.read_sensors()

    assertPacketQueueContains(
        protocol, Packet(Action.READ_REQUEST, FunctionalDomain.SENSORS, 2)
    )


async def test_client_read_control(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    await client.read_control()

    assertPacketQueueContains(
        protocol, Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1)
    )


async def test_client_read_scheduling(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    await client.read_scheduling()

    assertPacketQueueContains(
        protocol, Packet(Action.READ_REQUEST, FunctionalDomain.SCHEDULING, 4)
    )


async def test_client_update_mode(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    await client.update_mode(1)

    assertPacketQueueContains(
        protocol,
        Packet(
            Action.WRITE,
            FunctionalDomain.CONTROL,
            1,
            data={
                Attribute.MODE: 1,
                Attribute.FAN_MODE: 0,
                Attribute.HEAT_SETPOINT: 0,
                Attribute.COOL_SETPOINT: 0,
            },
        ),
    )


async def test_client_update_fan_mode(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    await client.update_fan_mode(1)

    assertPacketQueueContains(
        protocol,
        Packet(
            Action.WRITE,
            FunctionalDomain.CONTROL,
            1,
            data={
                Attribute.MODE: 0,
                Attribute.FAN_MODE: 1,
                Attribute.HEAT_SETPOINT: 0,
                Attribute.COOL_SETPOINT: 0,
            },
        ),
    )


async def test_client_update_setpoint(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    await client.update_setpoint(10, 20)

    assertPacketQueueContains(
        protocol,
        Packet(
            Action.WRITE,
            FunctionalDomain.CONTROL,
            1,
            data={
                Attribute.MODE: 0,
                Attribute.FAN_MODE: 0,
                Attribute.HEAT_SETPOINT: 20,
                Attribute.COOL_SETPOINT: 10,
            },
        ),
    )


async def test_client_set_hold(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    await client.set_hold(1)

    assertPacketQueueContains(
        protocol,
        Packet(
            Action.WRITE,
            FunctionalDomain.SCHEDULING,
            4,
            data={
                Attribute.HOLD: 1,
            },
        ),
    )


async def test_client_set_dehumidification_setpoint(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    await client.set_dehumidification_setpoint(50)

    assertPacketQueueContains(
        protocol,
        Packet(
            Action.WRITE,
            FunctionalDomain.CONTROL,
            3,
            data={
                Attribute.DEHUMIDIFICATION_SETPOINT: 50,
            },
        ),
    )


async def test_client_set_humidification_setpoint(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    await client.set_humidification_setpoint(50)

    assertPacketQueueContains(
        protocol,
        Packet(
            Action.WRITE,
            FunctionalDomain.CONTROL,
            4,
            data={
                Attribute.HUMIDIFICATION_SETPOINT: 50,
            },
        ),
    )


async def test_client_set_fresh_air(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    await client.set_fresh_air(1, 3)

    assertPacketQueueContains(
        protocol,
        Packet(
            Action.WRITE,
            FunctionalDomain.CONTROL,
            5,
            data={
                Attribute.FRESH_AIR_MODE: 1,
                Attribute.FRESH_AIR_EVENT: 3,
            },
        ),
    )


async def test_client_set_air_cleaning(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    await client.set_air_cleaning(1, 3)

    assertPacketQueueContains(
        protocol,
        Packet(
            Action.WRITE,
            FunctionalDomain.CONTROL,
            6,
            data={
                Attribute.AIR_CLEANING_MODE: 1,
                Attribute.AIR_CLEANING_EVENT: 3,
            },
        ),
    )


async def test_client_sync(client: AprilaireClient, protocol: _AprilaireClientProtocol):
    await client.sync()

    assertPacketQueueContains(
        protocol,
        Packet(
            Action.WRITE,
            FunctionalDomain.STATUS,
            2,
            data={
                Attribute.SYNCED: 1,
            },
        ),
    )


async def test_client_configure_cos(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    pass


async def test_client_read_mac_address(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    await client.read_mac_address()

    assertPacketQueueContains(
        protocol,
        Packet(
            Action.READ_REQUEST,
            FunctionalDomain.IDENTIFICATION,
            2,
        ),
    )


async def test_client_read_thermostat_status(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    await client.read_thermostat_status()

    assertPacketQueueContains(
        protocol,
        Packet(
            Action.READ_REQUEST,
            FunctionalDomain.CONTROL,
            7,
        ),
    )


async def test_client_read_thermostat_name(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    await client.read_thermostat_name()

    assertPacketQueueContains(
        protocol,
        Packet(
            Action.READ_REQUEST,
            FunctionalDomain.IDENTIFICATION,
            5,
        ),
    )


async def test_client_wait_for_response_success(client: AprilaireClient):
    wait_for_mock = AsyncMock(return_value=True)

    with patch("asyncio.wait_for", new=wait_for_mock):
        wait_for_response_result = await client.wait_for_response(
            FunctionalDomain.CONTROL, 1, 1
        )

    assert wait_for_response_result == True


async def test_client_wait_for_response_timeout(client: AprilaireClient):
    wait_for_mock = AsyncMock(side_effect=asyncio.exceptions.TimeoutError)

    with patch("asyncio.wait_for", new=wait_for_mock):
        wait_for_response_result = await client.wait_for_response(
            FunctionalDomain.CONTROL, 1, 1
        )

    assert wait_for_response_result == None


async def test_client_reconnect_with_delay(client: AprilaireClient):
    reconnect_mock = AsyncMock()

    with patch("pyaprilaire.socket_client.SocketClient._reconnect", new=reconnect_mock):
        await client._reconnect_with_delay()

        assert reconnect_mock.call_count == 1
        assert reconnect_mock.call_args[0][0] == client.retry_connection_interval
