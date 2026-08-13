import json
import logging
import sys
from unittest.mock import AsyncMock, Mock

import pytest

from pyaprilaire import cli
from pyaprilaire.console import ConsoleSession
from pyaprilaire.const import Action, Attribute, FunctionalDomain
from pyaprilaire.session import DEFAULT_PORT, DebugSession


@pytest.fixture
def logger():
    logger = logging.getLogger("pyaprilaire.test_cli")
    logger.propagate = False

    return logger


@pytest.fixture
def session(event_loop, logger):
    session = DebugSession("localhost", 7001, logger=logger, auto_status=False)

    session.run_command = AsyncMock()
    session.send_packet = AsyncMock()
    session.send_raw = Mock()

    return session


@pytest.fixture
def console(session):
    return ConsoleSession(session)


async def test_run_client_command(console, session):
    await console.handle("update_mode 3")

    session.run_command.assert_awaited_once()

    command, arguments = session.run_command.await_args.args

    assert command.name == "update_mode"
    assert arguments == [3]


async def test_run_client_command_with_send(console, session):
    await console.handle("send read_control")

    assert session.run_command.await_args.args[0].name == "read_control"


async def test_unknown_command_is_reported(console, session):
    await console.handle("nope")

    assert session.entries[-1].kind == "error"
    assert "no command named 'nope'" in session.entries[-1].message


async def test_bad_argument_is_reported(console, session):
    await console.handle("update_mode cool")

    assert session.entries[-1].kind == "error"
    assert "mode must be an integer" in session.entries[-1].message


async def test_send_hex(console, session):
    await console.handle("hex 01 02 0a")

    session.send_raw.assert_called_once_with(b"\x01\x02\x0a")


async def test_send_hex_with_crc(console, session):
    await console.handle("hexcrc 0102")

    session.send_raw.assert_called_once_with(b"\x01\x02", append_crc=True)


async def test_send_packet_with_fields(console, session):
    await console.handle("packet WRITE CONTROL 1 mode=3 cool_setpoint=24.5")

    packet = session.send_packet.await_args.args[0]

    assert packet.action is Action.WRITE
    assert packet.functional_domain is FunctionalDomain.CONTROL
    assert packet.attribute == 1
    assert packet.data[Attribute.MODE] == 3
    assert packet.data[Attribute.COOL_SETPOINT] == 24.5


async def test_send_packet_with_payload(console, session):
    await console.handle("packet WRITE CONTROL 99 01 02")

    packet = session.send_packet.await_args.args[0]

    assert packet.raw_data == [1, 2]


async def test_send_packet_without_data(console, session):
    await console.handle("packet READ_REQUEST SENSORS 2")

    packet = session.send_packet.await_args.args[0]

    assert packet.attribute == 2
    assert packet.raw_data is None


async def test_send_packet_requires_all_parts(console, session):
    await console.handle("packet WRITE CONTROL")

    assert session.entries[-1].kind == "error"
    assert "Usage: packet" in session.entries[-1].message


async def test_send_packet_rejects_a_bad_attribute(console, session):
    await console.handle("packet WRITE CONTROL x")

    assert "not a valid attribute" in session.entries[-1].message


async def test_send_packet_rejects_a_bad_action(console, session):
    await console.handle("packet NOPE CONTROL 1")

    assert "expected one of" in session.entries[-1].message


async def test_list(console, capsys):
    await console.handle("list setpoint")

    output = capsys.readouterr().out

    assert "update_setpoint(cool_setpoint: float, heat_setpoint: float)" in output
    assert "read_control" not in output


async def test_fields(console, capsys):
    await console.handle("fields WRITE CONTROL 1")

    assert "mode: INTEGER_REQUIRED" in capsys.readouterr().out


async def test_fields_unknown(console, capsys):
    await console.handle("fields WRITE CONTROL 99")

    assert "has no known fields" in capsys.readouterr().out


async def test_state(console, session, capsys):
    session._data_received({Attribute.MODE: 3})

    await console.handle("state")

    assert "mode = 3" in capsys.readouterr().out


async def test_state_when_empty(console, capsys):
    await console.handle("state")

    assert "No data has been received yet" in capsys.readouterr().out


async def test_detail(console):
    await console.handle("detail on")
    assert console.detail

    await console.handle("detail")
    assert not console.detail


async def test_clear(console, session):
    session.log("info", "hello")

    await console.handle("clear")

    assert not session.entries


async def test_quit(console):
    console.running = True

    await console.handle("quit")

    assert not console.running


async def test_comments_and_blank_lines_are_ignored(console, session):
    await console.handle("")
    await console.handle("# a comment")

    assert not session.entries


async def test_help(console, capsys):
    await console.handle("help")

    assert "Commands:" in capsys.readouterr().out


async def test_entries_are_printed(session, capsys):
    # Creating the console attaches it to the session as a listener
    ConsoleSession(session)

    session.log("info", "hello")

    assert "--- hello" in capsys.readouterr().out


async def test_entries_are_printed_as_json(session, capsys):
    ConsoleSession(session, json_output=True)

    session.log("info", "hello")

    captured = capsys.readouterr()

    assert json.loads(captured.out)["message"] == "hello"


async def test_messages_go_to_stderr_when_output_is_json(session, capsys):
    console = ConsoleSession(session, json_output=True)

    await console.handle("help")

    captured = capsys.readouterr()

    assert "Commands:" in captured.err
    assert captured.out == ""


def test_parser_defaults():
    args = cli.build_parser().parse_args([])

    assert args.host == "localhost"
    assert args.port == DEFAULT_PORT
    assert not args.no_tui
    assert not args.json
    assert args.output is None


def test_parser_options():
    args = cli.build_parser().parse_args(
        ["-H", "device", "-p", "1234", "--json", "-o", "out.ndjson", "--detail"]
    )

    assert args.host == "device"
    assert args.port == 1234
    assert args.json
    assert args.output == "out.ndjson"
    assert args.detail


def test_main_uses_the_console_for_json(monkeypatch):
    console = Mock()
    console.run = AsyncMock()
    console_class = Mock(return_value=console)

    monkeypatch.setattr(cli, "ConsoleSession", console_class)
    monkeypatch.setattr(cli.asyncio, "run", lambda coroutine: coroutine.close())

    assert cli.main(["--json"]) == 0

    assert console_class.call_args.kwargs["json_output"] is True


def test_main_writes_to_a_file(monkeypatch, tmp_path):
    path = tmp_path / "capture.ndjson"

    console = Mock()
    console.run = AsyncMock()

    monkeypatch.setattr(cli, "ConsoleSession", Mock(return_value=console))
    monkeypatch.setattr(cli.asyncio, "run", lambda coroutine: coroutine.close())

    assert cli.main(["--no-tui", "--output", str(path)]) == 0

    assert path.exists()


def test_main_reports_a_missing_tui(monkeypatch, capsys):
    # Setting the module to None makes importing it raise ImportError, as it
    # would if Textual weren't installed
    monkeypatch.setitem(sys.modules, "pyaprilaire.tui", None)

    assert cli.main([]) == 2

    assert "requires Textual" in capsys.readouterr().err
