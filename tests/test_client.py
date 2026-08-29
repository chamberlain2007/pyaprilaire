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


async def test_protocol_queue_loop_continues_after_serialize_error(
    protocol: _AprilaireClientProtocol,
):
    """A packet that fails to serialize should be dropped, not kill the loop"""

    # A wrong-typed value makes serialize() raise a TypeError. Note this
    # deliberately does not use a *missing* value: an absent field is a
    # legal partial write per spec section G ("when NULL is written the
    # corresponding value will not be modified"), and is serialized as a
    # null byte rather than raising. Only a genuinely malformed value
    # exercises the failure path this test is about.
    bad_packet = Packet(
        Action.WRITE,
        FunctionalDomain.CONTROL,
        3,
        data={Attribute.DEHUMIDIFICATION_SETPOINT: "not-an-integer"},
    )

    await protocol._send_packet(bad_packet)

    sleep_mock = AsyncMock()
    protocol.transport = Mock(asyncio.Transport)

    with patch("asyncio.sleep", new=sleep_mock):
        await protocol._queue_loop(loop_count=1)

    # The loop kept running (no exception escaped) and the bad packet was
    # dropped rather than written
    assert sleep_mock.call_count == 1
    assert protocol.transport.write.call_count == 0

    # A subsequently queued, valid packet is still sent on a later tick
    await protocol.set_hold(0)

    with patch("asyncio.sleep", new=sleep_mock):
        await protocol._queue_loop(loop_count=1)

    assert sleep_mock.call_count == 2
    assert protocol.transport.write.call_count == 1


def test_protocol_data_received(protocol: _AprilaireClientProtocol):
    protocol.data_received(bytes([1, 1, 0, 7, 3, 2, 1, 1, 2, 10, 20, 107]))

    assert protocol.data_received_callback.call_count == 1

    functional_domain, attribute, data = protocol.data_received_callback.call_args[0]

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

    functional_domain, attribute, data = protocol.data_received_callback.call_args[0]

    assert functional_domain == FunctionalDomain.STATUS
    assert attribute == 8
    assert data == {
        "error": 2,
    }


def test_protocol_data_received_byte_at_a_time(protocol: _AprilaireClientProtocol):
    # Regression test: a partial frame used to raise IndexError out of
    # Packet.parse, which asyncio's transport treats as fatal and closes the
    # connection. Feeding the frame in one-byte chunks - the worst case for
    # TCP segmentation - must still parse it correctly with no exception.
    frame = bytes([1, 1, 0, 7, 3, 2, 1, 1, 2, 10, 20, 107])

    for byte in frame[:-1]:
        protocol.data_received(bytes([byte]))

    assert protocol.data_received_callback.call_count == 0

    protocol.data_received(bytes([frame[-1]]))

    assert protocol.data_received_callback.call_count == 1

    functional_domain, attribute, data = protocol.data_received_callback.call_args[0]

    assert functional_domain == FunctionalDomain.CONTROL
    assert attribute == 1
    assert data == {
        Attribute.MODE: 1,
        Attribute.FAN_MODE: 2,
        Attribute.HEAT_SETPOINT: 10,
        Attribute.COOL_SETPOINT: 20,
    }


@pytest.mark.parametrize("split_index", range(1, 12))
def test_protocol_data_received_split_at_every_boundary(
    protocol: _AprilaireClientProtocol, split_index: int
):
    frame = bytes([1, 1, 0, 7, 3, 2, 1, 1, 2, 10, 20, 107])

    protocol.data_received(frame[:split_index])

    assert protocol.data_received_callback.call_count == 0

    protocol.data_received(frame[split_index:])

    assert protocol.data_received_callback.call_count == 1

    functional_domain, attribute, data = protocol.data_received_callback.call_args[0]

    assert functional_domain == FunctionalDomain.CONTROL
    assert attribute == 1
    assert data == {
        Attribute.MODE: 1,
        Attribute.FAN_MODE: 2,
        Attribute.HEAT_SETPOINT: 10,
        Attribute.COOL_SETPOINT: 20,
    }


def test_protocol_data_received_two_frames_coalesced(
    protocol: _AprilaireClientProtocol,
):
    # One TCP read can carry several frames - this already worked before the
    # reassembly buffer was added, and must keep working.
    frame = bytes([1, 1, 0, 7, 3, 2, 1, 1, 2, 10, 20, 107])

    protocol.data_received(frame + frame)

    assert protocol.data_received_callback.call_count == 2


def test_protocol_data_received_split_frame_followed_by_complete_frame(
    protocol: _AprilaireClientProtocol,
):
    frame = bytes([1, 1, 0, 7, 3, 2, 1, 1, 2, 10, 20, 107])

    # First chunk: the tail end of one frame, split mid-frame, plus a second,
    # fully complete frame right behind it in the same read.
    protocol.data_received(frame[:5])

    assert protocol.data_received_callback.call_count == 0

    protocol.data_received(frame[5:] + frame)

    assert protocol.data_received_callback.call_count == 2

    for call_args in protocol.data_received_callback.call_args_list:
        functional_domain, attribute, data = call_args[0]

        assert functional_domain == FunctionalDomain.CONTROL
        assert attribute == 1
        assert data == {
            Attribute.MODE: 1,
            Attribute.FAN_MODE: 2,
            Attribute.HEAT_SETPOINT: 10,
            Attribute.COOL_SETPOINT: 20,
        }


def test_protocol_data_received_never_completing_frame_capped(
    protocol: _AprilaireClientProtocol,
):
    # A peer that claims a huge frame (CNT close to its 65535 max) but never
    # finishes sending it must not be allowed to grow the receive buffer
    # without bound. Declare CNT = 65535 and dribble in data below that cap
    # without ever completing the frame; once the accumulated buffer would
    # exceed the max possible frame size, it must be dropped rather than
    # grown further, and no exception should reach the caller.
    header = bytes([1, 1, 0xFF, 0xFF])  # REV, SEQ, CNT=65535
    chunk = bytes([0xAA]) * 4096

    buffer_lengths = []

    for _ in range(20):
        protocol.data_received(header + chunk)

        buffer_lengths.append(len(protocol._receive_buffer))

        assert buffer_lengths[-1] <= 65535 + 5

    # The buffer must actually have been dropped at some point rather than
    # merely coincidentally staying under the cap - it would otherwise have
    # grown monotonically to 20 * 4100 = 82000 bytes.
    assert any(
        later < earlier
        for earlier, later in zip(buffer_lengths, buffer_lengths[1:], strict=False)
    )

    assert protocol.data_received_callback.call_count == 0


def test_protocol_connection_made_resets_receive_buffer(
    protocol: _AprilaireClientProtocol,
):
    protocol._queue_loop = AsyncMock()
    protocol._update_status = AsyncMock()

    protocol._receive_buffer.extend(b"\x01\x01\x00")

    protocol.connection_made(None)

    assert protocol._receive_buffer == bytearray()


def test_protocol_connection_lost_resets_receive_buffer(
    protocol: _AprilaireClientProtocol,
):
    protocol._receive_buffer.extend(b"\x01\x01\x00")

    protocol.connection_lost(None)

    assert protocol._receive_buffer == bytearray()


def test_protocol_mode_re_read(protocol: _AprilaireClientProtocol):
    protocol.read_control = AsyncMock()

    protocol.data_received(bytes([1, 1, 0, 7, 5, 2, 1, 1, 2, 10, 20, 127]))

    assert protocol.read_control.call_count == 1


def test_protocol_connection_lost(protocol: _AprilaireClientProtocol):
    protocol.connection_lost(None)

    assert protocol.data_received_callback.call_count == 1

    functional_domain, attribute, data = protocol.data_received_callback.call_args[0]

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

    sent_packet = protocol.packet_queue.put.call_args[0][0]

    assert original_packet == sent_packet


def assertPacketQueueContains(protocol: _AprilaireClientProtocol, packet: Packet):
    queue_items = list(protocol.packet_queue._queue)

    assert any(qp == packet for qp in queue_items)


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


async def test_client_set_written_outdoor_temperature_value(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    await client.set_written_outdoor_temperature_value(10)

    assertPacketQueueContains(
        protocol,
        Packet(
            Action.WRITE,
            FunctionalDomain.SENSORS,
            4,
            data={Attribute.OUTDOOR_SENSOR_STATUS: 0, Attribute.OUTDOOR_SENSOR: 10},
        ),
    )


async def test_client_read_thermostat_iaq_available(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    await client.read_thermostat_iaq_available()

    assertPacketQueueContains(
        protocol, Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 7)
    )


async def test_client_read_thermostat_status(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    await client.read_thermostat_status()

    assertPacketQueueContains(
        protocol, Packet(Action.READ_REQUEST, FunctionalDomain.STATUS, 6)
    )


async def test_client_read_iaq_status(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    await client.read_iaq_status()

    assertPacketQueueContains(
        protocol, Packet(Action.READ_REQUEST, FunctionalDomain.STATUS, 7)
    )


async def test_client_wait_for_response_success(client: AprilaireClient):
    wait_for_mock = AsyncMock(return_value=True)

    with patch("asyncio.wait_for", new=wait_for_mock):
        wait_for_response_result = await client.wait_for_response(
            FunctionalDomain.CONTROL, 1, 1
        )

    assert wait_for_response_result


async def test_client_wait_for_response_timeout(client: AprilaireClient):
    wait_for_mock = AsyncMock(side_effect=asyncio.exceptions.TimeoutError)

    with patch("asyncio.wait_for", new=wait_for_mock):
        wait_for_response_result = await client.wait_for_response(
            FunctionalDomain.CONTROL, 1, 1
        )

    assert wait_for_response_result is None


async def test_client_reconnect_with_delay(client: AprilaireClient):
    reconnect_mock = AsyncMock()

    with patch("pyaprilaire.socket_client.SocketClient._reconnect", new=reconnect_mock):
        await client._reconnect_with_delay()

        assert reconnect_mock.call_count == 1
        assert reconnect_mock.call_args[0][0] == client.retry_connection_interval


async def test_test_connection(client: AprilaireClient):
    reconnect_once_mock = AsyncMock()

    with patch(
        "pyaprilaire.socket_client.SocketClient._reconnect_once",
        new=reconnect_once_mock,
    ):
        await client.test_connection()

        assert reconnect_once_mock.call_count == 1
