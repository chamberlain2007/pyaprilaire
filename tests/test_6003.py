"""Synthetic 6003 protocol evidence without hardware access."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from pyaprilaire.client import (
    AprilaireClient,
    NackError,
    _AprilaireClientProtocol,
)
from pyaprilaire.const import Action, Attribute, FunctionalDomain, NackStatus
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


def test_heat_blast_cos_decodes():
    received = next(Packet.parse(wire([5, 3, 5, 0])))
    assert received.action == Action.COS
    assert received.data[Attribute.HEAT_BLAST] == 0


def _client():
    client = AprilaireClient(None, None, Mock(), 10, 10)
    client.protocol = _AprilaireClientProtocol(client.data_received)
    return client


async def _answer_next(client, *responses):
    """Feed `(sequence, data)` pairs to the client once its waits exist."""
    await asyncio.sleep(0)
    for sequence, data in responses:
        await client.data_received(FunctionalDomain.SCHEDULING, 5, data, sequence)


@pytest.mark.asyncio
async def test_set_heat_blast_and_wait_writes_then_returns_read_back():
    client = _client()
    answer = asyncio.ensure_future(_answer_next(client, (2, {Attribute.HEAT_BLAST: 1})))

    result = await client.set_heat_blast_and_wait(True, 1)
    await answer

    assert result == {Attribute.HEAT_BLAST: 1}
    assert [
        client.protocol.packet_queue.get_nowait().serialize()[4:-1] for _ in range(2)
    ] == [bytes([1, 3, 5, 1]), bytes([2, 3, 5])]
    assert not client.futures


@pytest.mark.asyncio
async def test_set_heat_blast_and_wait_raises_the_write_nack():
    client = _client()
    nack = NackError(NackStatus.VALUE_OUT_OF_RANGE, 0x10)
    answer = asyncio.ensure_future(
        _answer_next(client, (1, nack), (2, {Attribute.HEAT_BLAST: 0}))
    )

    with pytest.raises(NackError):
        await client.set_heat_blast_and_wait(True, 1)
    await answer

    assert not client.futures
