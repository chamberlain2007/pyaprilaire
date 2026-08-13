import asyncio
import importlib
import json
import logging
import os
import runpy
import sys
from unittest.mock import AsyncMock, Mock

import pytest

from pyaprilaire import cli
from pyaprilaire.cli import console as console_module
from pyaprilaire.cli.console import ConsoleSession
from pyaprilaire.cli.session import DEFAULT_PORT, DebugSession
from pyaprilaire.const import Action, Attribute, FunctionalDomain


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


def test_main_reports_a_missing_tui(monkeypatch, capsys, at_a_terminal):
    # Setting the module to None makes importing it raise ImportError, as it
    # would if Textual weren't installed
    monkeypatch.setitem(sys.modules, "pyaprilaire.cli.tui", None)

    assert cli.main([]) == 2

    assert "requires Textual" in capsys.readouterr().err


async def test_json_record_runs_a_command(console, session):
    await console.handle('{"command": "update_mode", "arguments": [3]}')

    command, arguments = session.run_command.await_args.args

    assert command.name == "update_mode"
    assert arguments == [3]


async def test_json_record_accepts_args(console, session):
    await console.handle('{"command": "update_setpoint", "args": [23.5, 19]}')

    assert session.run_command.await_args.args[1] == [23.5, 19.0]


async def test_json_record_rejects_bad_arguments(console, session):
    await console.handle('{"command": "update_mode", "arguments": 3}')

    assert "'arguments' must be a list" in session.entries[-1].message


async def test_json_record_sends_a_packet(console, session):
    await console.handle(
        '{"packet": {"action": "WRITE", "domain": "CONTROL", "attribute": 1,'
        ' "data": {"mode": 3, "cool_setpoint": 24.5}}}'
    )

    packet = session.send_packet.await_args.args[0]

    assert packet.action is Action.WRITE
    assert packet.data[Attribute.MODE] == 3
    assert packet.data[Attribute.COOL_SETPOINT] == 24.5


async def test_json_record_sends_a_packet_with_a_payload(console, session):
    await console.handle(
        '{"packet": {"action": "WRITE", "functional_domain": 2,'
        ' "attribute": 99, "payload": [1, 2]}}'
    )

    assert session.send_packet.await_args.args[0].raw_data == [1, 2]


async def test_json_record_requires_an_attribute(console, session):
    await console.handle('{"packet": {"action": "WRITE", "domain": "CONTROL"}}')

    assert "needs an 'attribute'" in session.entries[-1].message


async def test_json_record_sends_raw_bytes(console, session):
    await console.handle('{"raw": "01 02", "append_crc": true}')

    session.send_raw.assert_called_once_with(b"\x01\x02", append_crc=True)


async def test_json_record_waits(console, monkeypatch):
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(cli.asyncio, "sleep", fake_sleep)

    await console.handle('{"wait": 1.5}')

    assert slept == [1.5]


async def test_json_record_runs_text(console, session):
    await console.handle('{"text": "hex 01 02"}')

    session.send_raw.assert_called_once_with(b"\x01\x02")


async def test_captured_sent_record_is_replayed(console, session):
    await console.handle(
        '{"timestamp": "2026-01-01T00:00:00.000", "kind": "sent",'
        ' "message": "8 byte(s)", "raw": "01 01 00 03 02 02 01 46"}'
    )

    session.send_raw.assert_called_once_with(
        bytes([1, 1, 0, 3, 2, 2, 1, 0x46]), append_crc=False
    )


async def test_captured_received_record_is_ignored(console, session):
    await console.handle(
        '{"timestamp": "2026-01-01T00:00:00.000", "kind": "received",'
        ' "message": "8 byte(s)", "raw": "01 01 00 03 02 02 01 46"}'
    )

    assert session.send_raw.call_count == 0
    assert not session.entries


async def test_invalid_json_is_reported(console, session):
    await console.handle('{"command": ')

    assert "Unable to read the JSON record" in session.entries[-1].message


async def test_json_record_must_be_an_object(console, session):
    await console.handle("[1, 2]")

    assert session.entries[-1].kind == "error"


async def test_unrecognized_json_record_is_reported(console, session):
    await console.handle('{"nope": 1}')

    assert "A record needs one of" in session.entries[-1].message


async def test_wait_command(console, monkeypatch):
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(cli.asyncio, "sleep", fake_sleep)

    await console.handle("wait 2")

    assert slept == [2.0]


async def test_wait_command_rejects_a_bad_value(console, session):
    await console.handle("wait soon")

    assert "is not a number of seconds" in session.entries[-1].message


async def test_running_a_script(console, session, capsys):
    await console.run_script(
        [
            "# a comment\n",
            "read_control\n",
            "\n",
            '{"raw": "01 02"}\n',
        ]
    )

    output = capsys.readouterr().out

    assert session.run_command.await_count == 1
    session.send_raw.assert_called_once_with(b"\x01\x02", append_crc=False)

    # Scripted lines are echoed so that the output reads as a session
    assert "> read_control" in output
    assert "# a comment" not in output


async def test_a_script_stops_at_quit(console, session):
    await console.run_script(["quit\n", "read_control\n"])

    assert not console.running
    assert session.run_command.await_count == 0


async def test_running_an_input_file(console, session, tmp_path):
    path = tmp_path / "script.txt"
    path.write_text("read_control\n")

    await console._run_input_path(str(path))

    assert session.run_command.await_count == 1


async def test_a_missing_input_file_is_reported(console, session, tmp_path):
    await console._run_input_path(str(tmp_path / "nope.txt"))

    assert "Unable to read" in session.entries[-1].message


def test_parser_input_options():
    args = cli.build_parser().parse_args(
        ["--input", "script.ndjson", "--wait", "5", "--follow"]
    )

    assert args.input == "script.ndjson"
    assert args.wait == 5
    assert args.follow


def test_main_uses_the_console_for_an_input_file(monkeypatch):
    console = Mock()
    console.run = AsyncMock()
    console_class = Mock(return_value=console)

    monkeypatch.setattr(cli, "ConsoleSession", console_class)
    monkeypatch.setattr(cli.asyncio, "run", lambda coroutine: coroutine.close())

    assert cli.main(["--input", "script.ndjson"]) == 0

    assert console_class.call_args.kwargs["input_path"] == "script.ndjson"


async def test_running_stdin_redirected_from_a_file(
    console, session, tmp_path, monkeypatch
):
    path = tmp_path / "script.txt"
    path.write_text("read_control\n")

    # Redirected input is a regular file, which can't be read as a pipe
    with open(path, encoding="utf-8") as input_file:
        monkeypatch.setattr(sys, "stdin", input_file)

        await console._run_stdin()

    assert session.run_command.await_count == 1


async def test_unreadable_stdin_is_reported(console, session, monkeypatch):
    async def fail():
        raise OSError("no pipe here")

    monkeypatch.setattr(console_module, "_stdin_is_a_file", lambda: False)
    monkeypatch.setattr(console_module, "_stdin_reader", fail)

    await console._run_stdin()

    assert "Unable to read standard input" in session.entries[-1].message


async def test_lingering_waits_for_responses(console, monkeypatch):
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(cli.asyncio, "sleep", fake_sleep)

    console.wait = 3

    await console._linger()

    assert slept == [3]


async def test_following_stays_until_stopped(console, monkeypatch):
    async def stop(seconds):
        console.running = False

    monkeypatch.setattr(cli.asyncio, "sleep", stop)

    console.follow = True

    await console._linger()

    assert not console.running


def test_verbose_logging_goes_to_stderr():
    logger = cli._build_logger(verbose=True, use_tui=False)

    assert any(
        isinstance(handler, logging.StreamHandler) and handler.stream is sys.stderr
        for handler in logger.handlers
    )


def test_verbose_logging_is_suppressed_by_the_tui():
    logger = cli._build_logger(verbose=True, use_tui=True)

    assert all(isinstance(handler, logging.NullHandler) for handler in logger.handlers)


def test_main_runs_the_tui(monkeypatch, at_a_terminal):
    pytest.importorskip("textual", reason="the TUI requires the cli extra")

    app = Mock()

    monkeypatch.setattr("pyaprilaire.cli.tui.AprilaireTui", Mock(return_value=app))

    assert cli.main([]) == 0

    app.run.assert_called_once()


def test_main_uses_the_line_interface_without_a_terminal(monkeypatch):
    """Commands piped in need standard input, so the full screen interface
    gives way to the line based one"""

    run = AsyncMock()

    monkeypatch.setattr(console_module.ConsoleSession, "run", run)
    monkeypatch.setattr(sys, "stdin", Mock(isatty=Mock(return_value=False)))

    assert cli.main([]) == 0

    run.assert_awaited_once()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--no-tui"],
        ["--json"],
        ["--input", "-"],
        ["--test-connection"],
    ],
)
def test_main_uses_the_line_interface_when_stdout_or_stdin_is_needed(
    monkeypatch, at_a_terminal, arguments, tmp_path
):
    pytest.importorskip("textual", reason="the TUI requires the cli extra")

    tui = Mock()

    monkeypatch.setattr("pyaprilaire.cli.tui.AprilaireTui", tui)
    monkeypatch.setattr(console_module.ConsoleSession, "run", AsyncMock())
    monkeypatch.setattr(
        console_module, "check_connection", AsyncMock(return_value=True)
    )

    cli.main(arguments)

    assert tui.call_count == 0


def test_main_keeps_the_tui_when_json_goes_to_a_file(
    monkeypatch, at_a_terminal, tmp_path
):
    pytest.importorskip("textual", reason="the TUI requires the cli extra")

    app = Mock()

    monkeypatch.setattr("pyaprilaire.cli.tui.AprilaireTui", Mock(return_value=app))

    # The JSON has somewhere of its own to go, so it isn't competing for
    # standard output
    assert cli.main(["--json", "--output", str(tmp_path / "capture.ndjson")]) == 0

    app.run.assert_called_once()


def test_main_gives_the_tui_a_script_to_run(monkeypatch, at_a_terminal, tmp_path):
    pytest.importorskip("textual", reason="the TUI requires the cli extra")

    script = tmp_path / "script.txt"
    script.write_text("read_control\n")

    tui = Mock()

    monkeypatch.setattr("pyaprilaire.cli.tui.AprilaireTui", tui)

    assert cli.main(["--input", str(script)]) == 0

    assert tui.call_args.kwargs["script_path"] == str(script)


def test_main_tests_the_connection(monkeypatch, capsys):
    check = AsyncMock(return_value=True)

    monkeypatch.setattr(console_module, "check_connection", check)

    assert cli.main(["--test-connection"]) == 0

    assert check.await_count == 1


def test_main_reports_a_connection_that_failed(monkeypatch):
    monkeypatch.setattr(
        console_module, "check_connection", AsyncMock(return_value=False)
    )

    assert cli.main(["--test-connection"]) == 1


def test_main_handles_an_interrupt(monkeypatch):
    def interrupt(coroutine):
        coroutine.close()

        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "ConsoleSession", Mock())
    monkeypatch.setattr(cli.asyncio, "run", interrupt)

    assert cli.main(["--no-tui"]) == 0


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_module_entry_point(monkeypatch):
    console = Mock()
    console.run = AsyncMock()

    monkeypatch.setattr(
        "pyaprilaire.cli.console.ConsoleSession", Mock(return_value=console)
    )
    monkeypatch.setattr(cli.asyncio, "run", lambda coroutine: coroutine.close())
    monkeypatch.setattr(sys, "argv", ["pyaprilaire", "--no-tui"])

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("pyaprilaire.cli", run_name="__main__")

    assert exit_info.value.code == 0


def prepared_input(text: str) -> asyncio.StreamReader:
    """A reader holding input that has already arrived"""

    reader = asyncio.StreamReader()
    reader.feed_data(text.encode())
    reader.feed_eof()

    return reader


@pytest.fixture
def at_a_terminal(monkeypatch):
    """Pretend that standard input is a terminal"""

    monkeypatch.setattr(sys, "stdin", Mock(isatty=Mock(return_value=True)))


@pytest.fixture
def piped_input(monkeypatch):
    """Pretend that standard input is piped in rather than a terminal"""

    monkeypatch.setattr(sys, "stdin", Mock(isatty=Mock(return_value=False)))
    monkeypatch.setattr(console_module, "_stdin_is_a_file", lambda: False)


def prepare_stdin(monkeypatch, text: str) -> None:
    """Make the next read of standard input return the given text"""

    async def reader():
        return prepared_input(text)

    monkeypatch.setattr(console_module, "_stdin_reader", reader)


async def test_run_at_a_terminal(console, session, monkeypatch, capsys, at_a_terminal):
    session.connect = AsyncMock()
    console._linger = AsyncMock()

    prepare_stdin(monkeypatch, "read_control\n")

    await console.run()

    session.connect.assert_awaited_once()
    assert session.run_command.await_count == 1

    # A terminal gets the help, and isn't kept open afterwards
    assert "Commands:" in capsys.readouterr().out
    assert console._linger.await_count == 0


async def test_run_with_piped_input(console, session, monkeypatch, piped_input):
    session.connect = AsyncMock()
    console._linger = AsyncMock()

    prepare_stdin(monkeypatch, "read_control\n")

    await console.run()

    assert session.run_command.await_count == 1

    # Piped commands are followed by a wait, so their responses arrive
    console._linger.assert_awaited_once()


async def test_run_with_an_input_file(
    console, session, monkeypatch, tmp_path, piped_input
):
    path = tmp_path / "script.txt"
    path.write_text("read_control\n")

    console.input_path = str(path)
    session.connect = AsyncMock()
    console._linger = AsyncMock()

    await console.run()

    assert session.run_command.await_count == 1
    console._linger.assert_awaited_once()


async def test_run_reports_a_failed_connection(
    console, session, monkeypatch, piped_input
):
    session.connect = AsyncMock(side_effect=OSError("refused"))

    prepare_stdin(monkeypatch, "")
    console.wait = 0

    await console.run()

    assert any(
        "Unable to connect: refused" in entry.message for entry in session.entries
    )


async def test_run_does_not_wait_after_quit(console, session, monkeypatch, piped_input):
    session.connect = AsyncMock()
    console._linger = AsyncMock()

    prepare_stdin(monkeypatch, "quit\n")

    await console.run()

    assert console._linger.await_count == 0


async def test_input_path_of_a_dash_reads_stdin(console, monkeypatch):
    console._run_stdin = AsyncMock()

    await console._run_input_path("-")

    console._run_stdin.assert_awaited_once()


async def test_running_piped_stdin(console, session, monkeypatch, piped_input):
    prepare_stdin(monkeypatch, "read_control\n")

    await console._run_stdin()

    assert session.run_command.await_count == 1


async def test_connect_command(console, session):
    session.connect = AsyncMock()

    await console.handle("connect")

    session.connect.assert_awaited_once()


async def test_disconnect_command(console, session):
    session.disconnect = Mock()

    await console.handle("disconnect")

    session.disconnect.assert_called_once()


async def test_send_without_a_function(console, session):
    await console.handle("send")

    assert "Usage: send" in session.entries[-1].message


async def test_an_unexpected_failure_is_reported(console, session):
    session.run_command = AsyncMock(side_effect=RuntimeError("boom"))

    await console.handle("read_control")

    assert session.entries[-1].message == "RuntimeError: boom"


async def test_an_unexpected_failure_in_a_record_is_reported(console, session):
    session.run_command = AsyncMock(side_effect=RuntimeError("boom"))

    await console.handle('{"command": "read_control"}')

    assert session.entries[-1].message == "RuntimeError: boom"


async def test_a_json_array_is_reported(console, session):
    await console.handle("[1, 2]")

    assert session.entries[-1].message == "A JSON record must be an object"


async def test_a_packet_record_must_be_an_object(console, session):
    await console.handle('{"packet": 5}')

    assert "'packet' must be an object" in session.entries[-1].message


async def test_a_packet_record_rejects_a_bad_attribute(console, session):
    await console.handle(
        '{"packet": {"action": "WRITE", "domain": "CONTROL", "attribute": "x"}}'
    )

    assert "not a valid attribute" in session.entries[-1].message


def test_stdin_is_a_file_handles_a_missing_descriptor(monkeypatch):
    monkeypatch.setattr(sys, "stdin", Mock(fileno=Mock(side_effect=ValueError)))

    assert not console_module._stdin_is_a_file()


async def test_stdin_reader_reads_a_pipe(monkeypatch):
    read_descriptor, write_descriptor = os.pipe()

    os.write(write_descriptor, b"read_control\n")
    os.close(write_descriptor)

    with os.fdopen(read_descriptor) as pipe:
        monkeypatch.setattr(sys, "stdin", pipe)

        reader = await console_module._stdin_reader()

        assert await reader.readline() == b"read_control\n"


def test_the_entry_point_module_does_nothing_when_imported():
    entry_point = importlib.import_module("pyaprilaire.cli.__main__")

    assert entry_point.main is cli.main
