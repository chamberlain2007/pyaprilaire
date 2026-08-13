import asyncio
import logging
import runpy
import sys

import pytest

from pyaprilaire import mock_server as mock_server_module
from pyaprilaire.const import Action, Attribute, FunctionalDomain
from pyaprilaire.mock_server import CustomFormatter, _AprilaireServerProtocol
from pyaprilaire.mock_server import __main__ as mock_server_main
from pyaprilaire.packet import Packet


class FakeTransport:
    """A transport that records what is written to it"""

    def __init__(self):
        self.writes = []

    def write(self, data):
        self.writes.append(bytes(data))


@pytest.fixture
def protocol():
    return _AprilaireServerProtocol()


@pytest.fixture
def quick(monkeypatch):
    """Run the server's loops without waiting between iterations"""

    monkeypatch.setattr(mock_server_module, "COS_FREQUENCY", 0)
    monkeypatch.setattr(mock_server_module, "QUEUE_FREQUENCY", 0)


def send(
    protocol: _AprilaireServerProtocol,
    action: Action,
    functional_domain: FunctionalDomain,
    attribute: int,
    data: dict = None,
) -> list[Packet]:
    """Send a packet to the server and collect what it queued in response"""

    protocol.data_received(
        Packet(action, functional_domain, attribute, sequence=1, data=data).serialize()
    )

    responses = []

    while not protocol.packet_queue.empty():
        responses.append(protocol.packet_queue.get_nowait())

    return responses


def addresses(packets: list[Packet]) -> list[tuple]:
    """The action, functional domain and attribute of each packet"""

    return [
        (packet.action, packet.functional_domain, packet.attribute)
        for packet in packets
    ]


def test_the_log_formatter_colors_each_level():
    formatter = CustomFormatter()

    record = logging.LogRecord(
        "aprilaire.mock_server", logging.INFO, __file__, 1, "hello", None, None
    )

    assert "hello" in formatter.format(record)
    assert CustomFormatter.green in formatter.format(record)


def test_the_sequence_number_wraps(protocol):
    protocol.sequence = 127

    assert protocol._get_sequence() == 0


async def test_send_status_queues_the_current_state(protocol):
    await protocol._send_status()

    responses = []

    while not protocol.packet_queue.empty():
        responses.append(protocol.packet_queue.get_nowait())

    assert (
        Action.READ_RESPONSE,
        FunctionalDomain.IDENTIFICATION,
        2,
    ) in addresses(responses)
    assert (Action.COS, FunctionalDomain.CONTROL, 1) in addresses(responses)


@pytest.mark.parametrize("attribute", [1, 3, 4, 5, 6, 7])
async def test_a_control_read_request_is_answered(protocol, attribute):
    responses = send(protocol, Action.READ_REQUEST, FunctionalDomain.CONTROL, attribute)

    assert addresses(responses) == [
        (Action.READ_RESPONSE, FunctionalDomain.CONTROL, attribute)
    ]


async def test_a_sensor_read_request_is_answered(protocol):
    responses = send(protocol, Action.READ_REQUEST, FunctionalDomain.SENSORS, 2)

    assert addresses(responses) == [(Action.READ_RESPONSE, FunctionalDomain.SENSORS, 2)]


async def test_a_scheduling_read_request_is_answered(protocol):
    responses = send(protocol, Action.READ_REQUEST, FunctionalDomain.SCHEDULING, 4)

    assert responses[0].data[Attribute.HOLD] == protocol.hold


async def test_a_mac_address_read_request_is_answered(protocol):
    responses = send(protocol, Action.READ_REQUEST, FunctionalDomain.IDENTIFICATION, 2)

    assert responses[0].data[Attribute.MAC_ADDRESS] == protocol.mac_address


@pytest.mark.parametrize("attribute", [4, 5])
async def test_a_name_read_request_is_answered(protocol, attribute):
    responses = send(
        protocol, Action.READ_REQUEST, FunctionalDomain.IDENTIFICATION, attribute
    )

    assert responses[0].data[Attribute.NAME] == protocol.name
    assert responses[0].data[Attribute.LOCATION] == protocol.location


async def test_an_unknown_request_is_ignored(protocol):
    assert send(protocol, Action.READ_REQUEST, FunctionalDomain.STATUS, 2) == []


async def test_writing_the_control_state(protocol):
    responses = send(
        protocol,
        Action.WRITE,
        FunctionalDomain.CONTROL,
        1,
        data={
            Attribute.MODE: 3,
            Attribute.FAN_MODE: 1,
            Attribute.HEAT_SETPOINT: 18,
            Attribute.COOL_SETPOINT: 24,
        },
    )

    assert protocol.mode == 3
    assert protocol.fan_mode == 1
    assert protocol.heat_setpoint == 18
    assert protocol.cool_setpoint == 24
    # Changing a setpoint holds, where changing the mode releases the hold
    assert protocol.hold == 1

    assert addresses(responses) == [
        (Action.COS, FunctionalDomain.CONTROL, 1),
        (Action.COS, FunctionalDomain.STATUS, 6),
        (Action.COS, FunctionalDomain.SCHEDULING, 4),
    ]


async def test_writing_the_mode_releases_the_hold(protocol):
    protocol.hold = 1

    send(
        protocol,
        Action.WRITE,
        FunctionalDomain.CONTROL,
        1,
        data={
            Attribute.MODE: 2,
            Attribute.FAN_MODE: 0,
            Attribute.HEAT_SETPOINT: 0,
            Attribute.COOL_SETPOINT: 0,
        },
    )

    assert protocol.mode == 2
    assert protocol.hold == 0


async def test_writing_the_dehumidification_setpoint(protocol):
    responses = send(
        protocol,
        Action.WRITE,
        FunctionalDomain.CONTROL,
        3,
        data={Attribute.DEHUMIDIFICATION_SETPOINT: 55},
    )

    assert protocol.dehumidification_setpoint == 55
    assert protocol.dehumidification_status == 2

    assert addresses(responses) == [
        (Action.COS, FunctionalDomain.CONTROL, 3),
        (Action.COS, FunctionalDomain.STATUS, 7),
    ]


async def test_writing_the_humidification_setpoint(protocol):
    responses = send(
        protocol,
        Action.WRITE,
        FunctionalDomain.CONTROL,
        4,
        data={Attribute.HUMIDIFICATION_SETPOINT: 35},
    )

    assert protocol.humidification_setpoint == 35
    assert protocol.humidification_status == 2

    assert addresses(responses) == [
        (Action.COS, FunctionalDomain.CONTROL, 4),
        (Action.COS, FunctionalDomain.STATUS, 7),
    ]


async def test_writing_the_fresh_air_mode(protocol):
    responses = send(
        protocol,
        Action.WRITE,
        FunctionalDomain.CONTROL,
        5,
        data={Attribute.FRESH_AIR_MODE: 1, Attribute.FRESH_AIR_EVENT: 2},
    )

    assert protocol.fresh_air_mode == 1
    assert protocol.fresh_air_event == 2

    assert addresses(responses) == [
        (Action.COS, FunctionalDomain.CONTROL, 5),
        (Action.COS, FunctionalDomain.STATUS, 7),
    ]


async def test_writing_the_air_cleaning_mode(protocol):
    responses = send(
        protocol,
        Action.WRITE,
        FunctionalDomain.CONTROL,
        6,
        data={Attribute.AIR_CLEANING_MODE: 1, Attribute.AIR_CLEANING_EVENT: 3},
    )

    assert protocol.air_cleaning_mode == 1
    assert protocol.air_cleaning_event == 3

    assert addresses(responses) == [
        (Action.COS, FunctionalDomain.CONTROL, 6),
        (Action.COS, FunctionalDomain.STATUS, 7),
    ]


async def test_writing_the_hold(protocol):
    responses = send(
        protocol,
        Action.WRITE,
        FunctionalDomain.SCHEDULING,
        4,
        data={Attribute.HOLD: 2},
    )

    assert protocol.hold == 2
    assert responses[0].data[Attribute.HOLD] == 2


async def test_writing_to_status_sends_the_whole_state(protocol):
    protocol.data_received(
        Packet(
            Action.WRITE,
            FunctionalDomain.STATUS,
            2,
            sequence=1,
            data={Attribute.SYNCED: 1},
        ).serialize()
    )

    # The status is sent from a task, so it isn't queued until it runs
    await asyncio.sleep(0)

    assert not protocol.packet_queue.empty()


async def test_a_packet_that_cannot_be_parsed_is_ignored(protocol):
    protocol.data_received(b"\x01\x02\x00\x03\x63\x63\x63\x00")

    assert protocol.packet_queue.empty()


async def test_the_queue_is_written_to_the_transport(protocol, quick):
    transport = FakeTransport()
    protocol.transport = transport

    packet = Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1)
    protocol.packet_queue.put_nowait(packet)

    task = asyncio.ensure_future(protocol._queue_loop())

    for _ in range(5):
        await asyncio.sleep(0)

    assert transport.writes == [packet.serialize()]

    protocol.transport = None

    await asyncio.wait_for(task, 1)


async def test_the_status_is_sent_periodically(protocol, quick):
    protocol.transport = FakeTransport()

    task = asyncio.ensure_future(protocol._cos_loop())

    for _ in range(5):
        await asyncio.sleep(0)

    assert not protocol.packet_queue.empty()

    protocol.transport = None

    await asyncio.wait_for(task, 1)


async def test_connecting_and_disconnecting(protocol, quick):
    transport = FakeTransport()

    protocol.connection_made(transport)

    assert protocol.transport is transport

    protocol.connection_lost(None)

    assert protocol.transport is None

    # Let the loops notice that the connection has gone
    for _ in range(5):
        await asyncio.sleep(0)


async def _nothing() -> None:
    """A coroutine that does nothing, standing in for a server"""


class FakeLoop(asyncio.AbstractEventLoop):
    """An event loop that records what it was asked to do without doing it"""

    def __init__(self, interrupt: bool = False):
        self.servers = []
        self.ran = False
        self.interrupt = interrupt

    def create_server(self, factory, host, port):
        self.servers.append((factory, host, port))

        return _nothing()

    def create_task(self, coroutine):
        # Nothing runs the coroutine, so it is closed rather than left to
        # warn that it was never awaited
        coroutine.close()

    def run_forever(self):
        self.ran = True

        if self.interrupt:
            raise KeyboardInterrupt


@pytest.fixture
def loop(monkeypatch):
    """Stand in for the event loop the server would run on"""

    fake_loop = FakeLoop()

    monkeypatch.setattr(asyncio, "new_event_loop", lambda: fake_loop)
    monkeypatch.setattr(asyncio, "set_event_loop", lambda loop: None)

    return fake_loop


def test_running_the_module_listens_on_the_given_port(monkeypatch, loop):
    monkeypatch.setattr(sys, "argv", ["pyaprilaire.mock_server", "-p", "7123"])

    # Running a module that has already been imported warns, so it is taken
    # out of the way and put back afterwards
    monkeypatch.delitem(sys.modules, "pyaprilaire.mock_server.__main__")

    runpy.run_module("pyaprilaire.mock_server", run_name="__main__")

    assert loop.servers == [(_AprilaireServerProtocol, "localhost", 7123)]
    assert loop.ran


def test_the_server_listens_on_the_default_port(monkeypatch, loop):
    monkeypatch.setattr(sys, "argv", ["pyaprilaire.mock_server"])

    mock_server_main.main()

    assert loop.servers == [(_AprilaireServerProtocol, "localhost", 7001)]


def test_the_server_stops_when_interrupted(monkeypatch, loop):
    loop.interrupt = True

    monkeypatch.setattr(sys, "argv", ["pyaprilaire.mock_server"])

    mock_server_main.main()

    assert loop.ran
