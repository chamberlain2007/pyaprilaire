import asyncio
import logging
import tracemalloc
from unittest.mock import AsyncMock, Mock, patch

import pytest

from pyaprilaire.client import (
    COS_SUBSCRIPTIONS,
    COS_SUBSCRIPTIONS_READ_TIMEOUT,
    DEFAULT_COS_SUBSCRIPTIONS,
    AprilaireClient,
    NackError,
    _AprilaireClientProtocol,
)
from pyaprilaire.const import Action, Attribute, FunctionalDomain, NackStatus
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

    return _AprilaireClientProtocol(
        data_received_callback, reconnect_action, None, logger
    )


@pytest.fixture
def client(event_loop, logger, protocol):
    data_received_callback = Mock()

    client = AprilaireClient(None, None, data_received_callback, logger, 10, 10)

    client.protocol = protocol

    return client


def test_protocol_connection_made(protocol: _AprilaireClientProtocol):
    protocol._queue_loop = AsyncMock()
    protocol.connected_action = AsyncMock()

    protocol.connection_made(None)

    assert protocol._queue_loop.call_count == 1
    assert protocol.connected_action.call_count == 1


def test_protocol_connection_made_without_connected_action(
    protocol: _AprilaireClientProtocol,
):
    # The `protocol` fixture passes `None` for connected_action, so
    # connecting must still start the queue loop rather than raising.
    protocol._queue_loop = AsyncMock()

    assert protocol.connected_action is None

    protocol.connection_made(None)

    assert protocol._queue_loop.call_count == 1


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

    functional_domain, attribute, data, sequence = (
        protocol.data_received_callback.call_args[0]
    )

    assert functional_domain == FunctionalDomain.CONTROL
    assert attribute == 1
    assert data == {
        Attribute.MODE: 1,
        Attribute.FAN_MODE: 2,
        Attribute.HEAT_SETPOINT: 10,
        Attribute.COOL_SETPOINT: 20,
    }
    assert sequence == 1


def test_protocol_data_received_nack(protocol: _AprilaireClientProtocol):
    # CRC must be valid (0x63): NACK frames now have their CRC verified
    # like any other frame, so a frame with a bad CRC is silently dropped
    # before ever reaching the NackPacket branch this test exercises.
    protocol.data_received(bytes([1, 1, 0, 2, 6, 1, 0x63]))

    assert protocol.data_received_callback.call_count == 0


def test_protocol_data_received_error(protocol: _AprilaireClientProtocol):
    protocol.data_received(bytes([1, 1, 0, 4, 3, 7, 8, 2, 149]))

    assert protocol.data_received_callback.call_count == 1

    functional_domain, attribute, data, sequence = (
        protocol.data_received_callback.call_args[0]
    )

    assert functional_domain == FunctionalDomain.STATUS
    assert attribute == 8
    assert data == {
        "error": 2,
    }
    assert sequence == 1


def test_protocol_data_received_parse_exception_does_not_propagate(
    protocol: _AprilaireClientProtocol,
):
    # Regression guard: asyncio's transport treats any exception escaping
    # data_received as fatal and closes the connection, so a failure while
    # buffering/parsing must be logged and swallowed, not raised.
    with patch.object(protocol, "_parse_received_data", side_effect=ValueError("boom")):
        protocol.data_received(bytes([1, 1, 0, 7, 3, 2, 1, 1, 2, 10, 20, 107]))

    assert protocol.data_received_callback.call_count == 0


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

    functional_domain, attribute, data, sequence = (
        protocol.data_received_callback.call_args[0]
    )

    assert functional_domain == FunctionalDomain.CONTROL
    assert attribute == 1
    assert data == {
        Attribute.MODE: 1,
        Attribute.FAN_MODE: 2,
        Attribute.HEAT_SETPOINT: 10,
        Attribute.COOL_SETPOINT: 20,
    }
    assert sequence == 1


@pytest.mark.parametrize("split_index", range(1, 12))
def test_protocol_data_received_split_at_every_boundary(
    protocol: _AprilaireClientProtocol, split_index: int
):
    frame = bytes([1, 1, 0, 7, 3, 2, 1, 1, 2, 10, 20, 107])

    protocol.data_received(frame[:split_index])

    assert protocol.data_received_callback.call_count == 0

    protocol.data_received(frame[split_index:])

    assert protocol.data_received_callback.call_count == 1

    functional_domain, attribute, data, sequence = (
        protocol.data_received_callback.call_args[0]
    )

    assert functional_domain == FunctionalDomain.CONTROL
    assert attribute == 1
    assert data == {
        Attribute.MODE: 1,
        Attribute.FAN_MODE: 2,
        Attribute.HEAT_SETPOINT: 10,
        Attribute.COOL_SETPOINT: 20,
    }
    assert sequence == 1


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
        functional_domain, attribute, data, sequence = call_args[0]

        assert functional_domain == FunctionalDomain.CONTROL
        assert attribute == 1
        assert data == {
            Attribute.MODE: 1,
            Attribute.FAN_MODE: 2,
            Attribute.HEAT_SETPOINT: 10,
            Attribute.COOL_SETPOINT: 20,
        }
        assert sequence == 1


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
    protocol.connected_action = AsyncMock()

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

    functional_domain, attribute, data, sequence = (
        protocol.data_received_callback.call_args[0]
    )

    assert functional_domain == FunctionalDomain.NONE
    assert attribute == 0
    assert data == {
        "available": False,
    }
    assert sequence is None


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


def _expected_cos_raw_data(overrides: dict[Attribute, int] | None = None) -> list[int]:
    desired = dict(DEFAULT_COS_SUBSCRIPTIONS)

    if overrides:
        desired.update(overrides)

    return [
        0 if attribute is None else desired[attribute]
        for attribute, _ in COS_SUBSCRIPTIONS
    ]


async def test_protocol_read_cos_subscriptions(protocol: _AprilaireClientProtocol):
    sequence = await protocol.read_cos_subscriptions()

    assertPacketQueueContains(
        protocol, Packet(Action.READ_REQUEST, FunctionalDomain.STATUS, 1)
    )

    # The sequence number must come back so the caller can correlate the
    # response to this exact request (spec section F notes 2-3) rather than
    # to an unsolicited STATUS/1 COS.
    assert sequence == list(protocol.packet_queue._queue)[0].sequence


async def test_protocol_write_cos_subscriptions(protocol: _AprilaireClientProtocol):
    await protocol.write_cos_subscriptions(dict(DEFAULT_COS_SUBSCRIPTIONS))

    queue_items = list(protocol.packet_queue._queue)

    assert len(queue_items) == 1

    packet = queue_items[0]

    assert packet.action == Action.WRITE
    assert packet.functional_domain == FunctionalDomain.STATUS
    assert packet.attribute == 1
    assert len(packet.raw_data) == 29
    assert packet.raw_data == _expected_cos_raw_data()


async def test_protocol_write_cos_subscriptions_reserved_byte_is_placeholder_zero(
    protocol: _AprilaireClientProtocol,
):
    await protocol.write_cos_subscriptions(dict(DEFAULT_COS_SUBSCRIPTIONS))

    queue_items = list(protocol.packet_queue._queue)

    assert queue_items[0].raw_data[21] == 0


def test_cos_subscriptions_is_29_bytes_in_spec_order():
    assert len(COS_SUBSCRIPTIONS) == 29
    assert COS_SUBSCRIPTIONS[21][0] is None


def test_cos_subscriptions_previously_disabled_dependent_channels_now_enabled():
    # These channels back library functionality and used to be written as
    # disabled unconditionally on every connect - see PR description.
    for attribute in (
        Attribute.COS_SERVICE_REMINDERS_STATUS,  # spec J.18
        Attribute.COS_ALERTS_STATUS,  # spec J.19
        Attribute.COS_ALERTS_SETTINGS,  # spec J.19
        Attribute.COS_OVER_THE_AIR_ODT_UPDATE_TIMEOUT,  # spec J.15
    ):
        assert DEFAULT_COS_SUBSCRIPTIONS[attribute] == 1


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

    # No expected sequence recorded - falls back to matching by
    # (functional_domain, attribute) alone, same as before sequence
    # tracking existed.
    client.futures.setdefault(future_key, []).append((future, None))

    await client.data_received(functional_domain, attribute, data)

    assert client.data_received_callback.call_count == 1
    assert client.data_received_callback.call_args[0][0] == data

    assert future.result() == data
    assert client.futures == {}


async def test_client_data_received_empty(client: AprilaireClient):
    await client.data_received(None, None, None)


async def test_client_data_received_state_error(client: AprilaireClient):
    functional_domain = FunctionalDomain.CONTROL
    attribute = 1

    loop = asyncio.get_event_loop()
    future = loop.create_future()

    future_key = (functional_domain, attribute)

    client.futures.setdefault(future_key, []).append((future, None))

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


async def test_client_configure_cos_reads_before_writing(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    client.wait_for_response = AsyncMock(return_value=None)

    await client.configure_cos()

    queue_items = list(protocol.packet_queue._queue)

    assert len(queue_items) == 2

    assert queue_items[0].action == Action.READ_REQUEST
    assert queue_items[0].functional_domain == FunctionalDomain.STATUS
    assert queue_items[0].attribute == 1

    assert queue_items[1].action == Action.WRITE
    assert queue_items[1].functional_domain == FunctionalDomain.STATUS
    assert queue_items[1].attribute == 1
    assert queue_items[1].raw_data == _expected_cos_raw_data()

    # The wait must be correlated to the read's own sequence number, so an
    # unsolicited STATUS/1 COS can't be mistaken for its response.
    client.wait_for_response.assert_called_once_with(
        FunctionalDomain.STATUS,
        1,
        COS_SUBSCRIPTIONS_READ_TIMEOUT,
        sequence=queue_items[0].sequence,
    )


async def test_client_configure_cos_skips_write_when_matching(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    # The thermostat already reports exactly the desired mask (e.g. it's
    # still at its factory default, per spec 7.1's "Default settings are in
    # bold") - no write should be issued.
    client.wait_for_response = AsyncMock(return_value=dict(DEFAULT_COS_SUBSCRIPTIONS))

    await client.configure_cos()

    queue_items = list(protocol.packet_queue._queue)

    assert len(queue_items) == 1
    assert queue_items[0].action == Action.READ_REQUEST


async def test_client_configure_cos_writes_when_mismatched(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    current = dict(DEFAULT_COS_SUBSCRIPTIONS)
    current[Attribute.COS_DEHUMIDIFICATION_SETPOINT] = 0

    client.wait_for_response = AsyncMock(return_value=current)

    await client.configure_cos()

    queue_items = list(protocol.packet_queue._queue)

    assert len(queue_items) == 2

    write_packet = queue_items[1]

    assert write_packet.action == Action.WRITE
    assert len(write_packet.raw_data) == 29
    assert write_packet.raw_data == _expected_cos_raw_data()


async def test_client_configure_cos_reserved_byte_never_forced(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    # The real parser (packet.py) drops the Reserved byte 21 entirely, so a
    # read response never carries a key for it - that must not be treated
    # as a mismatch that triggers a write.
    current = dict(DEFAULT_COS_SUBSCRIPTIONS)

    assert None not in current

    client.wait_for_response = AsyncMock(return_value=current)

    await client.configure_cos()

    queue_items = list(protocol.packet_queue._queue)

    assert len(queue_items) == 1


async def test_client_configure_cos_overrides(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    client.wait_for_response = AsyncMock(return_value=None)

    await client.configure_cos(overrides={Attribute.COS_DEHUMIDIFICATION_SETPOINT: 0})

    queue_items = list(protocol.packet_queue._queue)

    assert queue_items[1].raw_data == _expected_cos_raw_data(
        {Attribute.COS_DEHUMIDIFICATION_SETPOINT: 0}
    )


async def test_client_configure_cos_overrides_ignore_unmapped_attributes(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    # An override for something outside the COS mask (or the Reserved byte,
    # which has no Attribute) is silently ignored rather than raising.
    client.wait_for_response = AsyncMock(return_value=None)

    await client.configure_cos(overrides={Attribute.MODE: 5})

    queue_items = list(protocol.packet_queue._queue)

    assert queue_items[1].raw_data == _expected_cos_raw_data()


async def test_client_read_cos_subscriptions(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    await client.read_cos_subscriptions()

    assertPacketQueueContains(
        protocol, Packet(Action.READ_REQUEST, FunctionalDomain.STATUS, 1)
    )


async def test_client_read_cos_subscriptions_and_wait(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    client.wait_for_response = AsyncMock(return_value={Attribute.COS_IAQ_STATUS: 1})

    result = await client.read_cos_subscriptions_and_wait(1)

    queue_items = list(protocol.packet_queue._queue)

    assert result == {Attribute.COS_IAQ_STATUS: 1}
    client.wait_for_response.assert_called_once_with(
        FunctionalDomain.STATUS, 1, 1, sequence=queue_items[0].sequence
    )


def test_client_create_protocol_wires_connection_made(client: AprilaireClient):
    # The protocol only knows how to send and receive packets; which
    # requests a fresh connection should make is the client's business.
    created_protocol = client.create_protocol()

    assert created_protocol.connected_action == client.connection_made


async def test_client_connection_made_updates_status(client: AprilaireClient):
    client._update_status = AsyncMock()

    await client.connection_made()

    assert client._update_status.call_count == 1


def test_client_connected_attribute_not_shadowed_by_a_method(
    client: AprilaireClient,
):
    # `SocketClient.__init__` sets `self.connected` as a bool, so the
    # connect hook must not be named `connected` - it would be shadowed on
    # every instance and, being falsy, silently skipped by the protocol's
    # `if self.connected_action:` check.
    assert client.connected is False
    assert callable(client.connection_made)


async def test_client_update_status(
    client: AprilaireClient, protocol: _AprilaireClientProtocol
):
    client.wait_for_response = AsyncMock(return_value=None)

    sleep_mock = AsyncMock()

    with patch("asyncio.sleep", new=sleep_mock):
        await client._update_status()

    # mac_address, thermostat_status, iaq_status, control,
    # thermostat_iaq_available, sensors, thermostat_name, scheduling,
    # configure_cos (a read, then a write because the read returned no
    # current mask), dehumidification_setpoint, humidification_setpoint,
    # sync.
    assert protocol.packet_queue.qsize() == 13
    assert sleep_mock.call_count == 1


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


@pytest.mark.parametrize(
    "method_name,functional_domain,attribute,expected_packet",
    [
        (
            "read_sensors_and_wait",
            FunctionalDomain.SENSORS,
            2,
            Packet(Action.READ_REQUEST, FunctionalDomain.SENSORS, 2),
        ),
        (
            "read_control_and_wait",
            FunctionalDomain.CONTROL,
            1,
            Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1),
        ),
        (
            "read_scheduling_and_wait",
            FunctionalDomain.SCHEDULING,
            4,
            Packet(Action.READ_REQUEST, FunctionalDomain.SCHEDULING, 4),
        ),
        (
            "read_mac_address_and_wait",
            FunctionalDomain.IDENTIFICATION,
            2,
            Packet(Action.READ_REQUEST, FunctionalDomain.IDENTIFICATION, 2),
        ),
        (
            "read_thermostat_name_and_wait",
            FunctionalDomain.IDENTIFICATION,
            5,
            Packet(Action.READ_REQUEST, FunctionalDomain.IDENTIFICATION, 5),
        ),
        (
            "read_thermostat_iaq_available_and_wait",
            FunctionalDomain.CONTROL,
            7,
            Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 7),
        ),
        (
            "read_thermostat_status_and_wait",
            FunctionalDomain.STATUS,
            6,
            Packet(Action.READ_REQUEST, FunctionalDomain.STATUS, 6),
        ),
        (
            "read_iaq_status_and_wait",
            FunctionalDomain.STATUS,
            7,
            Packet(Action.READ_REQUEST, FunctionalDomain.STATUS, 7),
        ),
    ],
)
async def test_client_read_and_wait_sends_request_and_waits_on_its_own_sequence(
    client: AprilaireClient,
    protocol: _AprilaireClientProtocol,
    method_name: str,
    functional_domain: FunctionalDomain,
    attribute: int,
    expected_packet: Packet,
):
    """Each `read_*_and_wait` method must send its request, then wait pinned
    to the exact sequence number that specific send used."""

    wait_for_response_mock = AsyncMock(return_value={"result": "ok"})
    client.wait_for_response = wait_for_response_mock

    result = await getattr(client, method_name)(5)

    assertPacketQueueContains(protocol, expected_packet)

    # First (and only) send from this fixture's fresh protocol, so it used
    # sequence 1 (`_get_sequence` starts at 0 and pre-increments).
    wait_for_response_mock.assert_called_once_with(
        functional_domain, attribute, 5, sequence=1
    )
    assert result == {"result": "ok"}


async def test_client_read_mac_address_and_wait_pins_to_its_own_sequence(
    client: AprilaireClient,
):
    """Regression test for the actual race: a second, unrelated call to
    read_mac_address() landing between this call's send and its wait (e.g.
    from a concurrent task) must not change which sequence this wait ends
    up pinned to - it must stay pinned to the sequence its own send
    returned, not whatever the most recent send happened to be."""

    real_read_mac_address = client.read_mac_address
    interleaved_sequence = None

    async def read_mac_address_then_interleave():
        nonlocal interleaved_sequence
        sequence = await real_read_mac_address()
        # Simulates a second, concurrent caller sending the same request
        # before this call gets to wait on its own.
        interleaved_sequence = await real_read_mac_address()
        return sequence

    client.read_mac_address = read_mac_address_then_interleave

    wait_for_response_mock = AsyncMock(return_value={"result": "ok"})
    client.wait_for_response = wait_for_response_mock

    await client.read_mac_address_and_wait(5)

    # The interleaved call really did get a different sequence...
    assert interleaved_sequence == 2
    # ...but this call's wait is still pinned to its own (the first) one.
    wait_for_response_mock.assert_called_once_with(
        FunctionalDomain.IDENTIFICATION, 2, 5, sequence=1
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


# --- Regression tests for the sequence-correlation defects described in
# spec section F notes 2-3 and section H.4: responses (including COS) are
# now correlated back to the specific request that caused them via
# sequence number, rather than only by (functional_domain, attribute). See
# `AprilaireClient.data_received` and `wait_for_response`.


async def test_client_wait_for_response_explicit_sequence_pins_wait(
    client: AprilaireClient,
):
    """An explicit `sequence` argument pins the wait to that exact sequence
    number - this is what lets `read_mac_address_and_wait` and its
    siblings correlate a wait back to the specific request their own send
    just made, rather than to any response for the same
    (functional_domain, attribute)."""

    captured_entries = []

    async def fake_wait_for(future, timeout):
        captured_entries.extend(client.futures[(FunctionalDomain.CONTROL, 1)])
        return "unused"

    with patch("asyncio.wait_for", new=fake_wait_for):
        result = await client.wait_for_response(
            FunctionalDomain.CONTROL, 1, 1, sequence=42
        )

    assert result == "unused"
    assert captured_entries == [(captured_entries[0][0], 42)]


async def test_client_wait_for_response_default_sequence_is_unpinned(
    client: AprilaireClient,
):
    """Omitting `sequence` (the default) resolves on the next response for
    this (functional_domain, attribute) regardless of which request caused
    it, including an unsolicited COS - the caller is explicitly asking to
    observe the key, not correlate a specific request's answer."""

    captured_entries = []

    async def fake_wait_for(future, timeout):
        captured_entries.extend(client.futures[(FunctionalDomain.CONTROL, 1)])
        return "unused"

    with patch("asyncio.wait_for", new=fake_wait_for):
        await client.wait_for_response(FunctionalDomain.CONTROL, 1, 1)

    assert captured_entries == [(captured_entries[0][0], None)]


async def test_client_data_received_unsolicited_cos_does_not_resolve_pending_read(
    client: AprilaireClient,
):
    """Failure mode 1: an unsolicited COS carrying a different sequence
    number than the read request must NOT resolve that read's future, even
    though it shares the same (functional_domain, attribute) - see spec
    section H.4 ("COS Actions are asynchronous events, a COS transaction
    may happen in parallel with a Write, Read request action happening in
    the other direction")."""

    functional_domain = FunctionalDomain.CONTROL
    attribute = 3  # Dehumidification setpoint

    future = asyncio.get_event_loop().create_future()

    future_key = (functional_domain, attribute)
    request_sequence = 5

    client.futures[future_key] = [(future, request_sequence)]

    # An unsolicited COS carrying the pre-write value, with a sequence
    # number that belongs to the thermostat (spec section F note 1: device
    # sequence numbers are 128-255) rather than to our request.
    stale_cos_data = {Attribute.DEHUMIDIFICATION_SETPOINT: 40}
    await client.data_received(functional_domain, attribute, stale_cos_data, 200)

    assert not future.done()
    assert client.futures[future_key] == [(future, request_sequence)]

    # The actual Read Response, carrying the same sequence number as the
    # request (spec section F note 2), does resolve it.
    fresh_data = {Attribute.DEHUMIDIFICATION_SETPOINT: 50}
    await client.data_received(
        functional_domain, attribute, fresh_data, request_sequence
    )

    assert future.done()
    assert future.result() == fresh_data
    assert client.futures == {}


async def test_client_data_received_concurrent_duplicate_requests_resolved_independently(
    client: AprilaireClient,
):
    """Failure mode 2: two concurrent waiters on the same
    (functional_domain, attribute), pinned to different request sequence
    numbers, must each only be resolved by the response matching their own
    sequence number - not both by whichever response arrives first."""

    functional_domain = FunctionalDomain.CONTROL
    attribute = 3

    first_future = asyncio.get_event_loop().create_future()
    second_future = asyncio.get_event_loop().create_future()

    future_key = (functional_domain, attribute)
    client.futures[future_key] = [(first_future, 5), (second_future, 6)]

    await client.data_received(functional_domain, attribute, {"value": 60}, 6)

    assert second_future.done()
    assert second_future.result() == {"value": 60}
    assert not first_future.done()
    assert client.futures[future_key] == [(first_future, 5)]

    await client.data_received(functional_domain, attribute, {"value": 55}, 5)

    assert first_future.done()
    assert first_future.result() == {"value": 55}
    assert client.futures == {}


async def test_client_wait_for_response_cleanup_survives_already_removed_entry(
    client: AprilaireClient,
):
    """When a response resolves one of several concurrent waiters on the
    same key, `data_received` replaces `self.futures[future_key]` with a
    new list containing only the still-unresolved entries. The resolved
    waiter's own `finally` cleanup then finds its entry missing from that
    (different) list object - `list.remove` raising ValueError there must
    be swallowed, not propagated."""

    functional_domain = FunctionalDomain.CONTROL
    attribute = 3
    future_key = (functional_domain, attribute)

    first_task = asyncio.ensure_future(
        client.wait_for_response(functional_domain, attribute, 1, sequence=5)
    )
    await asyncio.sleep(0)  # let it register its (future, 5) entry

    second_task = asyncio.ensure_future(
        client.wait_for_response(functional_domain, attribute, 1, sequence=6)
    )
    await asyncio.sleep(0)  # let it register its (future, 6) entry

    # Resolves only the second waiter; futures[future_key] is rebuilt as a
    # new list containing just the first (still-pending) entry.
    await client.data_received(functional_domain, attribute, {"value": 60}, 6)

    # The second waiter's finally block must not raise even though its own
    # entry is no longer in the list it finds at futures[future_key], and
    # the still-pending first entry must be untouched.
    assert await second_task == {"value": 60}
    assert len(client.futures[future_key]) == 1
    assert client.futures[future_key][0][1] == 5

    first_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_task


async def test_client_wait_for_response_timeout_removes_future(
    client: AprilaireClient,
):
    """Failure mode 4: a timed-out wait must not leave a stale entry behind
    in `self.futures` - `asyncio.wait_for` cancels the future, but nothing
    previously removed the corresponding list entry."""

    result = await client.wait_for_response(FunctionalDomain.CONTROL, 1, 0.01)

    assert result is None
    assert client.futures == {}


async def test_client_wait_for_response_timeout_removes_only_its_own_entry(
    client: AprilaireClient,
):
    """The leak fix must remove only the timed-out entry, leaving sibling
    waiters on the same key (and other keys) untouched."""

    sibling_future = asyncio.get_event_loop().create_future()
    future_key = (FunctionalDomain.CONTROL, 1)
    client.futures[future_key] = [(sibling_future, None)]

    result = await client.wait_for_response(FunctionalDomain.CONTROL, 1, 0.01)

    assert result is None
    assert client.futures == {future_key: [(sibling_future, None)]}


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


async def test_test_connection_stops_listening_on_nack_error(client: AprilaireClient):
    """The device only accepts one home-automation connection at a time (see
    the README), so `test_connection` must not leak the connection when the
    identification read is terminally NACKed: `stop_listen()` must still run
    even though `wait_for_response` now raises `NackError` instead of
    returning, and that error must still reach the caller."""

    reconnect_once_mock = AsyncMock()
    nack_error = NackError(NackStatus.VALUE_OUT_OF_RANGE, 0x10)

    client.read_mac_address = AsyncMock()
    client.wait_for_response = AsyncMock(side_effect=nack_error)
    client.stop_listen = Mock()

    with patch(
        "pyaprilaire.socket_client.SocketClient._reconnect_once",
        new=reconnect_once_mock,
    ):
        with pytest.raises(NackError) as exc_info:
            await client.test_connection()

    assert exc_info.value is nack_error
    assert client.stop_listen.call_count == 1


# --- Regression/coverage tests for the spec section H.5 NACK status table
# and retry policy: a NACK is no longer just a log line - its status code is
# decoded (`NackStatus`), the three retryable codes are retried per the
# spec's "Action in Case of NACK" column (reusing the original request's
# sequence number, per section F note 3), and a terminal NACK fails the
# pending `wait_for_response` future promptly via `NackError` instead of
# leaving the caller to wait out its timeout. See
# `_AprilaireClientProtocol._handle_nack` / `_retry_packet` and
# `AprilaireClient.data_received` / `wait_for_response`.


def _nack_frame(sequence: int, status: int) -> bytes:
    """Build a CRC-valid NACK frame carrying `status` at the position spec
    section G calls FUNCTIONAL DOMAIN / STATUS CODE, and `sequence` in the
    frame header (spec section F notes 2-3)."""
    frame = [1, sequence, 0, 2, 6, status]
    frame.append(Packet._generate_crc(frame))
    return bytes(frame)


@pytest.mark.parametrize(
    "status",
    [
        NackStatus.GENERIC_ERROR,
        NackStatus.BUFFER_FULL_OR_DEVICE_BUSY,
        NackStatus.TIMED_OUT_WAITING_FOR_RESPONSE,
    ],
)
async def test_protocol_nack_retryable_status_retries_exactly_twice_then_stops(
    protocol: _AprilaireClientProtocol, status: NackStatus
):
    """Spec section H.5: these three status codes are retried "2 additional
    times ... and then clear[ed] from the queue" - a third NACK for the same
    request must stop retrying and drop the in-flight record."""

    protocol._retry_packet = AsyncMock()

    original_packet = Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1)
    await protocol._send_packet(original_packet)
    sequence = original_packet.sequence

    protocol.data_received(_nack_frame(sequence, int(status)))
    assert protocol._retry_packet.call_count == 1
    assert protocol._retry_packet.call_args[0][0] is original_packet
    assert protocol._in_flight_requests[sequence] == (original_packet, 1)

    protocol.data_received(_nack_frame(sequence, int(status)))
    assert protocol._retry_packet.call_count == 2
    assert protocol._in_flight_requests[sequence] == (original_packet, 2)

    # Third NACK: the retry budget (2 additional attempts) is exhausted, so
    # no further retry is scheduled and the record is cleared.
    protocol.data_received(_nack_frame(sequence, int(status)))
    assert protocol._retry_packet.call_count == 2
    assert sequence not in protocol._in_flight_requests


@pytest.mark.parametrize(
    "status",
    [
        NackStatus.UNKNOWN_ATTRIBUTE,
        NackStatus.WRITES_NOT_ACCEPTED_IN_CURRENT_APPLICATION_MODE,
        NackStatus.VALUE_OUT_OF_RANGE,
    ],
)
async def test_protocol_nack_terminal_status_does_not_retry(
    protocol: _AprilaireClientProtocol, status: NackStatus
):
    """Spec section H.5: every status code other than the three retryable
    ones has an action of just "Clear the transaction from the queue" - no
    retry at all, not even once."""

    protocol._retry_packet = AsyncMock()

    original_packet = Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1)
    await protocol._send_packet(original_packet)
    sequence = original_packet.sequence

    protocol.data_received(_nack_frame(sequence, int(status)))

    assert protocol._retry_packet.call_count == 0
    assert sequence not in protocol._in_flight_requests


async def test_protocol_nack_unknown_status_treated_as_terminal(
    protocol: _AprilaireClientProtocol,
):
    """A status code this client doesn't recognize (not defined in
    `NackStatus`) must not be assumed retryable - only the three codes spec
    section H.5 explicitly calls out are retried."""

    protocol._retry_packet = AsyncMock()

    original_packet = Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1)
    await protocol._send_packet(original_packet)
    sequence = original_packet.sequence

    # 0x0D is not one of spec section H.5's defined status codes.
    protocol.data_received(_nack_frame(sequence, 0x0D))

    assert protocol._retry_packet.call_count == 0
    assert sequence not in protocol._in_flight_requests


async def test_protocol_retry_packet_reuses_sequence_and_delay_in_range(
    protocol: _AprilaireClientProtocol,
):
    """Spec section F note 3: "Retries of a packet will use the same
    sequence number as the initial packet" - `_retry_packet` must re-queue
    the exact same packet object (so its `.sequence` is untouched) rather
    than allocating a new one, after spec section H.5's "0.5 to 1 second
    delay between retries"."""

    sleep_mock = AsyncMock()
    protocol.packet_queue.put = AsyncMock()

    packet = Packet(Action.WRITE, FunctionalDomain.CONTROL, 1, sequence=42)

    with patch("asyncio.sleep", new=sleep_mock):
        await protocol._retry_packet(packet)

    assert sleep_mock.call_count == 1
    (delay,) = sleep_mock.call_args[0]
    assert 0.5 <= delay <= 1.0

    protocol.packet_queue.put.assert_awaited_once_with(packet)
    assert packet.sequence == 42


async def test_protocol_nack_in_flight_record_cleared_on_success(
    protocol: _AprilaireClientProtocol,
):
    """A genuine (non-NACK) response for a sequence number must clear that
    sequence's in-flight record - otherwise a late, spurious NACK reusing
    the same sequence number (after it wraps around) could be mistaken for
    belonging to the completed request."""

    original_packet = Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1)
    await protocol._send_packet(original_packet)
    sequence = original_packet.sequence

    assert sequence in protocol._in_flight_requests

    # A Control/1 Read Response, carrying the same sequence as the request.
    frame = [1, sequence, 0, 7, 3, 2, 1, 1, 2, 10, 20]
    frame.append(Packet._generate_crc(frame))
    protocol.data_received(bytes(frame))

    assert sequence not in protocol._in_flight_requests


async def test_protocol_in_flight_requests_bounded_by_sequence_wraparound(
    protocol: _AprilaireClientProtocol,
):
    """`_in_flight_requests` must not grow without bound: since sequence
    numbers cycle through 0-127 (`_get_sequence`), sending a new request
    eventually overwrites whatever was previously recorded for that
    sequence number, capping the dict at 128 entries regardless of how many
    requests are sent."""

    for _ in range(300):
        await protocol._send_packet(
            Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1)
        )

    size_after_wraparound = len(protocol._in_flight_requests)
    assert size_after_wraparound <= 128

    for _ in range(50):
        await protocol._send_packet(
            Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1)
        )

    assert len(protocol._in_flight_requests) == size_after_wraparound


async def test_protocol_nack_terminal_invokes_callback_with_nack_error(
    protocol: _AprilaireClientProtocol,
):
    """A terminal NACK must report a `NackError` back through
    `data_received_callback`, carrying the (functional_domain, attribute,
    sequence) of the request it failed, so `AprilaireClient.data_received`
    can fail the matching `wait_for_response` future."""

    original_packet = Packet(
        Action.WRITE,
        FunctionalDomain.CONTROL,
        1,
        data={
            Attribute.MODE: 0,
            Attribute.FAN_MODE: 0,
            Attribute.HEAT_SETPOINT: 70,
            Attribute.COOL_SETPOINT: 0,
        },
    )
    await protocol._send_packet(original_packet)
    sequence = original_packet.sequence

    protocol.data_received(_nack_frame(sequence, int(NackStatus.VALUE_OUT_OF_RANGE)))

    assert protocol.data_received_callback.call_count == 1

    functional_domain, attribute, data, callback_sequence = (
        protocol.data_received_callback.call_args[0]
    )

    assert functional_domain == FunctionalDomain.CONTROL
    assert attribute == 1
    assert isinstance(data, NackError)
    assert data.status == NackStatus.VALUE_OUT_OF_RANGE
    assert callback_sequence == sequence


async def test_protocol_nack_retrying_does_not_invoke_callback(
    protocol: _AprilaireClientProtocol,
):
    """While a NACK is still being retried, the request has not failed yet
    - the callback (and therefore the pending future) must not be
    touched."""

    protocol._retry_packet = AsyncMock()

    original_packet = Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1)
    await protocol._send_packet(original_packet)
    sequence = original_packet.sequence

    protocol.data_received(
        _nack_frame(sequence, int(NackStatus.BUFFER_FULL_OR_DEVICE_BUSY))
    )

    assert protocol.data_received_callback.call_count == 0


async def test_client_wait_for_response_raises_nack_error_on_terminal_nack(
    client: AprilaireClient,
):
    """A terminal NACK must fail the pending `wait_for_response` future
    promptly via `NackError`, rather than leaving the caller to wait out its
    full timeout only to receive an unexplained `None` (failure mode 3)."""

    functional_domain = FunctionalDomain.CONTROL
    attribute = 1

    wait_task = asyncio.ensure_future(
        client.wait_for_response(functional_domain, attribute, 5)
    )
    await asyncio.sleep(0)  # let wait_for_response register its future

    nack_error = NackError(NackStatus.VALUE_OUT_OF_RANGE, 0x10)
    await client.data_received(functional_domain, attribute, nack_error, None)

    with pytest.raises(NackError) as exc_info:
        await asyncio.wait_for(wait_task, 1)

    assert exc_info.value is nack_error
    assert client.futures == {}


async def test_client_data_received_nack_error_not_passed_to_user_callback(
    client: AprilaireClient,
):
    """`NackError` is an internal signal for resolving `wait_for_response`
    futures - it must never reach the user-supplied `data_received_callback`
    as if it were response data."""

    nack_error = NackError(NackStatus.VALUE_OUT_OF_RANGE, 0x10)

    await client.data_received(FunctionalDomain.CONTROL, 1, nack_error, None)

    client.data_received_callback.assert_not_called()
