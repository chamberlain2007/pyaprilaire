"""Synthetic 6003 protocol evidence without hardware access."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from pyaprilaire.client import _AprilaireClientProtocol
from pyaprilaire.const import Action, Attribute, FunctionalDomain
from pyaprilaire.packet import Packet


def wire(body):
    header = bytes([1, 1, len(body) >> 8, len(body) & 255]) + bytes(body)
    return header + bytes([Packet._generate_crc(header)])


def test_extended_identification_keeps_revision_and_model():
    packet = next(
        Packet.parse(wire([3, 8, 2, 2, 0, 0, 0, 0, 1, 1, 66, 2, 2, 2, 28, 4, 14]))
    )
    assert packet.data[Attribute.MODEL_NUMBER] == 28
    assert packet.data[Attribute.HARDWARE_REVISION] == 66
    assert Attribute.CONNECTION_TYPE not in packet.data


def test_zone_system_settings_decode_count_and_limits():
    packet = next(Packet.parse(wire([3, 1, 10, 1, 0, 2, 1, 1, 1, 1, 10, 10, 1, 47])))
    assert packet.data[Attribute.ZONE_COUNT] == 2
    assert packet.data[Attribute.DAT_LOW_LIMIT] == 10
    assert packet.data[Attribute.DAT_HIGH_LIMIT] == 47


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [None, 28])
async def test_identified_6003_outgoing_frames_are_paced(model):
    protocol = _AprilaireClientProtocol(AsyncMock())
    protocol.transport = Mock()
    protocol.model_number = model
    await protocol.read_control()
    await protocol.read_sensors()
    sleep = AsyncMock()
    with patch("asyncio.sleep", sleep):
        await protocol._queue_loop(loop_count=1)
    assert protocol.transport.write.call_count == 2
    assert [c.args for c in sleep.await_args_list].count((0.3,)) == 2


def test_heat_blast_round_trip():
    packet = Packet(
        Action.WRITE, FunctionalDomain.SCHEDULING, 5, data={Attribute.HEAT_BLAST: 1}
    )
    assert packet.serialize()[4:-1] == bytes([1, 3, 5, 1])
    received = next(Packet.parse(wire([3, 3, 5, 1])))
    assert received.data[Attribute.HEAT_BLAST] == 1


@pytest.mark.asyncio
async def test_6003_helpers_queue_expected_protocol_frames():
    protocol = _AprilaireClientProtocol(AsyncMock())
    assert await protocol.read_zone_system_settings() == 1
    assert await protocol.read_heat_blast() == 2
    assert await protocol.set_heat_blast(True) == 3
    assert [protocol.packet_queue.get_nowait().serialize()[4:-1] for _ in range(3)] == [
        bytes([2, 1, 10]),
        bytes([2, 3, 5]),
        bytes([1, 3, 5, 1]),
    ]
