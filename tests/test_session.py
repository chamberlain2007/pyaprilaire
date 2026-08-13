import asyncio
import json
import logging
from unittest.mock import AsyncMock, patch

import pytest

from pyaprilaire.commands import find_command
from pyaprilaire.const import Action, Attribute, FunctionalDomain
from pyaprilaire.packet import Packet
from pyaprilaire.session import (
    ERROR,
    INFO,
    RECEIVED,
    SENT,
    DebugSession,
    EntryWriter,
    LogEntry,
    SessionError,
    format_entry_lines,
)


class FakeTransport:
    """A transport that records what is written to it"""

    def __init__(self):
        self.writes = []
        self.closed = False

    def write(self, data):
        self.writes.append(bytes(data))

    def close(self):
        self.closed = True


@pytest.fixture
def logger():
    logger = logging.getLogger("pyaprilaire.test_session")
    logger.propagate = False

    return logger


@pytest.fixture
def session(event_loop, logger):
    return DebugSession("localhost", 7001, logger=logger, auto_status=False)


@pytest.fixture
def transport(session):
    """Attach a fake connection to the session"""

    protocol = session.client.create_protocol()

    # The real loops would run for the lifetime of the connection
    protocol._queue_loop = AsyncMock()
    protocol._update_status = AsyncMock()

    fake_transport = FakeTransport()

    protocol.connection_made(fake_transport)

    session.client.protocol = protocol
    session.client.connected = True
    session.client.stopped = False

    return fake_transport


def test_record_sent(session):
    data = Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1).serialize()

    entry = session.record_sent(data)

    assert entry.kind == SENT
    assert entry.raw == data
    assert entry.message == "8 byte(s): READ_REQUEST CONTROL attribute 1"
    assert len(entry.frames) == 1
    assert entry.frames[0].crc_valid
    assert list(session.entries) == [entry]


def test_record_received_decodes_multiple_frames(session):
    first = Packet(
        Action.READ_RESPONSE,
        FunctionalDomain.SCHEDULING,
        4,
        data={Attribute.HOLD: 1},
    ).serialize()
    second = Packet(
        Action.READ_RESPONSE,
        FunctionalDomain.IDENTIFICATION,
        2,
        data={Attribute.MAC_ADDRESS: [1, 2, 3, 4, 5, 6]},
    ).serialize()

    entry = session.record_received(first + second)

    assert entry.kind == RECEIVED
    assert [frame.summary for frame in entry.frames] == [
        "READ_RESPONSE SCHEDULING attribute 4",
        "READ_RESPONSE IDENTIFICATION attribute 2",
    ]
    assert dict(entry.frames[0].decoded) == {"hold": 1}
    assert dict(entry.frames[1].decoded) == {"mac_address": "1:2:3:4:5:6"}


def test_record_received_waits_for_the_rest_of_a_frame(session):
    data = Packet(
        Action.READ_RESPONSE,
        FunctionalDomain.SCHEDULING,
        4,
        data={Attribute.HOLD: 1},
    ).serialize()

    first_entry = session.record_received(data[:5])

    assert first_entry.frames == []
    assert first_entry.message == "5 byte(s): no complete frame"
    assert first_entry.remainder == data[:5]

    second_entry = session.record_received(data[5:])

    assert [frame.summary for frame in second_entry.frames] == [
        "READ_RESPONSE SCHEDULING attribute 4"
    ]
    assert second_entry.remainder == b""


def test_entry_listener(session):
    entries = []

    session.add_entry_listener(entries.append)
    session.log(INFO, "hello")

    assert [entry.message for entry in entries] == ["hello"]


def test_entry_listener_failure_is_contained(session):
    def failing_listener(entry):
        raise RuntimeError("listener failed")

    entries = []

    session.add_entry_listener(failing_listener)
    session.add_entry_listener(entries.append)

    entry = session.log(INFO, "hello")

    # One listener failing doesn't stop the entry being recorded or reaching
    # the other listeners
    assert entry in session.entries
    assert entries == [entry]


def test_clear(session):
    session.log(INFO, "hello")
    session.clear()

    assert not session.entries


def test_state_is_updated_from_received_data(session):
    states = []

    session.add_state_listener(states.append)

    session._data_received({Attribute.MODE: 3, Attribute.FAN_MODE: 2})

    assert session.state == {"mode": 3, "fan_mode": 2}
    assert states == [session.state]


async def test_run_command_queues_a_packet(session, transport):
    await session.run_command("read_control")

    packet = session.client.protocol.packet_queue.get_nowait()

    assert packet == Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1)
    assert session.entries[-1].message == "Queued read_control()"


async def test_run_command_with_arguments(session, transport):
    await session.run_command("update_setpoint", [24.5, 19])

    packet = session.client.protocol.packet_queue.get_nowait()

    assert packet.data[Attribute.COOL_SETPOINT] == 24.5
    assert packet.data[Attribute.HEAT_SETPOINT] == 19


async def test_run_command_unknown(session, transport):
    with pytest.raises(SessionError, match="no command named 'nope'"):
        await session.run_command("nope")


async def test_run_command_requires_a_connection(session):
    with pytest.raises(SessionError, match="Not connected"):
        await session.run_command("read_control")


async def test_send_packet(session, transport):
    packet = Packet(Action.READ_REQUEST, FunctionalDomain.SENSORS, 2)

    await session.send_packet(packet)

    assert session.client.protocol.packet_queue.get_nowait() is packet
    assert session.entries[-1].message == ("Queued READ_REQUEST SENSORS attribute 2")


async def test_send_packet_rejects_an_unserializable_packet(session, transport):
    # A write to an unknown attribute has no mapping to build a payload from
    packet = Packet(Action.WRITE, FunctionalDomain.CONTROL, 99)

    with pytest.raises(SessionError, match="Unable to build the packet"):
        await session.send_packet(packet)


def test_send_raw_writes_exactly_what_was_given(session, transport):
    session.send_raw(b"\x01\x02\x03")

    assert transport.writes == [b"\x01\x02\x03"]
    assert session.entries[-2].message == "Writing 3 raw byte(s)"


def test_send_raw_appends_a_crc(session, transport):
    data = Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1).serialize()

    session.send_raw(data[:-1], append_crc=True)

    assert transport.writes == [data]


def test_send_raw_is_recorded(session, transport):
    data = Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1).serialize()

    session.send_raw(data)

    entry = session.entries[-1]

    assert entry.kind == SENT
    assert entry.frames[0].summary == "READ_REQUEST CONTROL attribute 1"


def test_send_raw_requires_bytes(session, transport):
    with pytest.raises(SessionError, match="No bytes to send"):
        session.send_raw(b"")


def test_send_raw_requires_a_connection(session):
    with pytest.raises(SessionError, match="Not connected"):
        session.send_raw(b"\x01")


async def test_received_data_is_recorded(session, transport):
    data = Packet(
        Action.READ_RESPONSE,
        FunctionalDomain.SCHEDULING,
        4,
        data={Attribute.HOLD: 1},
    ).serialize()

    session.client.protocol.data_received(data)

    # The client hands decoded data back through a task
    await asyncio.sleep(0)

    assert session.entries[-1].kind == RECEIVED
    assert session.state["hold"] == 1


def test_malformed_received_data_does_not_stop_the_session(session, transport):
    session.client.protocol.data_received(b"\x01\x02\xff\xff\x01\x02")

    # The bytes are still shown even though the client can't decode them
    assert session.entries[-2].kind == RECEIVED
    assert session.entries[-2].frames[0].packets == []
    assert session.entries[-1].kind == ERROR
    assert session.entries[-1].message.startswith("Error handling received data")


async def test_auto_status_can_be_suppressed(session, transport):
    protocol = session.client.create_protocol()
    protocol.auto_status = False

    await protocol._update_status()

    assert protocol.packet_queue.qsize() == 0


def test_disconnecting_does_not_reconnect(session, transport):
    reconnect = AsyncMock()

    session.client.protocol.reconnect_action = reconnect
    session.stopping = True

    session.client.protocol.connection_lost(None)

    assert reconnect.call_count == 0


def test_a_lost_connection_reconnects(session, transport):
    reconnect = AsyncMock()

    session.client.protocol.reconnect_action = reconnect

    session.client.protocol.connection_lost(None)

    assert reconnect.call_count == 1


def test_disconnect(session, transport):
    session.disconnect()

    assert session.stopping
    assert not session.connected
    assert session.status_text == "disconnected"
    assert session.entries[-1].message == "Disconnected"


def test_disconnect_when_not_connected(session):
    with pytest.raises(SessionError, match="Not connected"):
        session.disconnect()


async def test_connect_when_already_connected(session, transport):
    with pytest.raises(SessionError, match="Already connected"):
        await session.connect()


def test_status_text(session, transport):
    assert session.status_text == "connected"

    session.client.connected = False
    session.client.reconnecting = True

    assert session.status_text == "connecting"


def test_entry_to_json(session):
    data = Packet(
        Action.READ_RESPONSE,
        FunctionalDomain.SCHEDULING,
        4,
        data={Attribute.HOLD: 1},
    ).serialize()

    entry = session.record_received(data)

    result = json.loads(entry.to_json())

    assert result["kind"] == RECEIVED
    assert result["raw"] == data.hex(" ")
    assert result["frames"][0]["decoded"] == {"hold": 1}
    assert result["frames"][0]["crc_valid"] is True
    assert result["frames"][0]["action_name"] == "READ_RESPONSE"
    assert "timestamp" in result


def test_entry_to_json_without_frames():
    result = json.loads(LogEntry(INFO, "hello").to_json())

    assert result == {
        "timestamp": result["timestamp"],
        "kind": INFO,
        "message": "hello",
    }


def test_format_entry_lines(session):
    data = Packet(
        Action.READ_RESPONSE,
        FunctionalDomain.SCHEDULING,
        4,
        data={Attribute.HOLD: 1},
    ).serialize()

    lines = format_entry_lines(session.record_received(data))

    assert lines[0].endswith("<-- 18 byte(s): READ_RESPONSE SCHEDULING attribute 4")
    assert any("hold = 1" in line for line in lines)
    assert any(data.hex(" ") in line for line in lines)
    assert any("crc=0x" in line and "(valid)" in line for line in lines)


def test_format_entry_lines_with_detail(session):
    data = Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1).serialize()

    lines = format_entry_lines(session.record_sent(data), detail=True)

    assert any("0000  01" in line for line in lines)


def test_format_entry_lines_for_an_error():
    entry = LogEntry(ERROR, "it broke")

    assert format_entry_lines(entry) == [f"{entry.time_text} !!! it broke"]


def test_entry_writer_text(session, tmp_path):
    path = tmp_path / "session.log"

    writer = EntryWriter(str(path))
    writer(session.log(INFO, "hello"))
    writer.close()

    assert path.read_text().strip().endswith("--- hello")


def test_entry_writer_json(session, tmp_path):
    path = tmp_path / "session.ndjson"

    writer = EntryWriter(str(path), as_json=True)
    writer(session.log(INFO, "hello"))
    writer(session.log(ERROR, "it broke"))
    writer.close()

    entries = [json.loads(line) for line in path.read_text().splitlines()]

    assert [entry["message"] for entry in entries] == ["hello", "it broke"]


async def test_a_failed_connection_is_not_left_connecting(session):
    with pytest.raises(OSError):
        await session.connect()

    assert not session.connected
    assert session.status_text == "disconnected"


def test_entry_to_json_with_an_incomplete_frame(session):
    data = Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1).serialize()

    result = json.loads(session.record_received(data[:4]).to_json())

    assert result["remainder"] == data[:4].hex(" ")


def test_format_entry_lines_with_an_incomplete_frame(session):
    data = Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1).serialize()

    lines = format_entry_lines(session.record_received(data[:4]))

    assert lines[-1].strip() == f"incomplete frame: {data[:4].hex(' ')}"


def test_format_entry_lines_shows_a_frame_error(session):
    # A length that can't be trusted is surfaced rather than dropped
    lines = format_entry_lines(session.record_sent(b"\x01\x02\xff\xff\x01\x02"))

    assert any("Length mismatch" in line for line in lines)


def test_format_entry_lines_shows_the_payload_with_detail(session):
    data = Packet(
        Action.READ_RESPONSE,
        FunctionalDomain.SCHEDULING,
        4,
        data={Attribute.HOLD: 1},
    ).serialize()

    lines = format_entry_lines(session.record_received(data), detail=True)

    assert any("hold = 1" in line for line in lines)
    assert any(line.strip().startswith("payload: 01 00") for line in lines)
    assert any(line.strip().startswith("payload (decimal): 1 0") for line in lines)


async def test_auto_status_sends_the_startup_requests(session, transport):
    protocol = session.client.create_protocol()
    protocol.auto_status = True

    with patch("asyncio.sleep", new=AsyncMock()):
        await protocol._update_status()

    assert protocol.packet_queue.qsize() == 9


def test_state_listener_failure_is_contained(session):
    def failing_listener(state):
        raise RuntimeError("listener failed")

    states = []

    session.add_state_listener(failing_listener)
    session.add_state_listener(states.append)

    session._data_received({Attribute.MODE: 3})

    assert session.state == {"mode": 3}
    assert states == [session.state]


async def test_connect_with_reconnect(logger):
    session = DebugSession("localhost", 7001, logger=logger, reconnect=True)

    session.client.start_listen = AsyncMock()

    await session.connect()

    session.client.start_listen.assert_awaited_once()
    assert session.entries[-1].message == "Connected"


async def test_close_disconnects(session, transport):
    await session.close()

    assert session.stopping
    assert session.client.stopped
    assert transport.closed


async def test_close_when_not_connected(session):
    await session.close()

    assert session.stopping


async def test_run_command_with_a_command_object(session, transport):
    command = find_command("read_control", session.commands)

    await session.run_command(command)

    assert session.client.protocol.packet_queue.get_nowait() == Packet(
        Action.READ_REQUEST, FunctionalDomain.CONTROL, 1
    )
