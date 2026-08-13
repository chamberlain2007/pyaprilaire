"""Line based interactive session with a device

This is the front end used when a full screen interface isn't wanted or
isn't available, and is the only front end when output is JSON, so that
stdout carries nothing but the JSON records.

Commands can also be read from a file or from piped input, as either the
same text a person would type or as JSON records, one per line. The records
a session writes with --json are themselves valid input, so a captured
session can be replayed against a device.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
from collections.abc import Iterable
from typing import Any

from ..const import Action, FunctionalDomain
from .commands import (
    build_packet,
    known_attributes,
    mapping_fields,
    parse_enum,
    parse_hex_bytes,
)
from .session import SENT, DebugSession, LogEntry, SessionError, format_entry_lines

HELP = """
Commands:
  list [text]                 List the client functions, optionally filtered
  <function> [args...]        Run a client function, e.g. update_mode 3
  send <function> [args...]   Run a client function whose name collides with a
                              command below
  packet <action> <domain> <attribute> [values]
                              Send a packet, where values are either name=value
                              pairs for a known packet or raw payload hex
  hex <bytes>                 Write raw bytes exactly as given, as pairs of hex
                              digits with or without spaces, e.g. 01 02 0a
  hexcrc <bytes>              The same, with a calculated CRC appended
  fields <action> <domain> <attribute>
                              Show the known payload fields of a packet
  state                       Show the data received from the device so far
  connect / disconnect        Open or close the connection
  detail [on|off]             Show or hide hex dumps and full payloads
  wait <seconds>              Pause, to let responses arrive
  clear                       Clear the recorded entries
  help                        Show this help
  quit                        Leave the session

A line starting with { is read as a JSON record instead:
  {"command": "update_setpoint", "arguments": [23.5, 19]}
  {"packet": {"action": "WRITE", "domain": "CONTROL", "attribute": 1,
              "data": {"mode": 3}}}
  {"raw": "01 02 00 03 02 05 02 c9", "append_crc": false}
  {"wait": 2}
Records written by --json are also accepted, so a captured session can be
replayed: what was sent is sent again, and what was received is ignored.
""".strip()


class ConsoleSession:
    """Runs an interactive session over plain input and output"""

    def __init__(
        self,
        session: DebugSession,
        json_output: bool = False,
        detail: bool = False,
        input_path: str = None,
        wait: float = 2.0,
        follow: bool = False,
    ) -> None:
        self.session = session
        self.json_output = json_output
        self.detail = detail
        self.input_path = input_path
        self.wait = wait
        self.follow = follow

        # The session runs until something asks it to stop, which a script
        # can do before run() is ever reached
        self.running = True

        session.add_entry_listener(self._write_entry)

    def _echo(self, text: str = "") -> None:
        """Write a message for the user

        Messages go to stderr when the output is JSON so that stdout stays
        machine readable.
        """

        print(text, file=sys.stderr if self.json_output else sys.stdout, flush=True)

    def _write_entry(self, entry: LogEntry) -> None:
        """Write an entry as it is recorded"""

        if self.json_output:
            print(entry.to_json(), flush=True)
            return

        for line in format_entry_lines(entry, self.detail):
            print(line, flush=True)

    async def run(self) -> None:
        """Run until the user leaves the session or input ends

        Commands come from a file when one was given, from the terminal when
        there is one, and otherwise from whatever was piped in.
        """

        at_a_terminal = sys.stdin.isatty()

        if at_a_terminal and not self.input_path:
            self._echo(HELP)
            self._echo()

        try:
            await self.session.connect()
        except (OSError, SessionError) as exc:
            self.session.log("error", f"Unable to connect: {exc}")

        scripted = False

        if self.input_path:
            await self._run_input_path(self.input_path)
            scripted = True

        if self.running and at_a_terminal:
            await self._run_lines(await _stdin_reader())
        elif self.running and not self.input_path:
            await self._run_stdin()
            scripted = True

        if self.running and scripted:
            await self._linger()

        await self.session.close()

    async def _run_input_path(self, path: str) -> None:
        """Run the commands in a file, or in standard input for '-'"""

        if path == "-":
            await self._run_stdin()
            return

        try:
            with open(path, encoding="utf-8") as input_file:
                lines = input_file.readlines()
        except OSError as exc:
            self.session.log("error", f"Unable to read {path}: {exc}")
            return

        await self.run_script(lines)

    async def _run_stdin(self) -> None:
        """Run the commands from standard input

        Input redirected from a file can't be read as a pipe, so it is read
        in one go instead.
        """

        if _stdin_is_a_file():
            await self.run_script(sys.stdin.readlines())
            return

        try:
            reader = await _stdin_reader()
        except (OSError, ValueError) as exc:
            self.session.log("error", f"Unable to read standard input: {exc}")
            return

        await self._run_lines(reader, echo=True)

    async def _run_lines(
        self, reader: asyncio.StreamReader, echo: bool = False
    ) -> None:
        """Run commands as they are read"""

        while self.running:
            line = await reader.readline()

            if not line:
                break

            await self.handle(line.decode(errors="replace").strip(), echo=echo)

    async def run_script(self, lines: Iterable[str]) -> None:
        """Run a sequence of commands, stopping early if one of them quits"""

        for line in lines:
            if not self.running:
                break

            await self.handle(line.strip(), echo=True)

    async def _linger(self) -> None:
        """Stay connected after scripted commands run out

        Responses arrive after the command that caused them, so leaving
        immediately would mean never seeing them.
        """

        if self.follow:
            while self.running:
                await asyncio.sleep(0.5)
        elif self.wait > 0:
            await asyncio.sleep(self.wait)

    async def handle(self, line: str, echo: bool = False) -> None:
        """Handle a single line of input, as either text or a JSON record

        Scripted lines are echoed so that the output reads as a session, but
        only once it is known that the line does something.
        """

        if not line or line.startswith("#"):
            return

        if line.startswith(("{", "[")):
            await self._handle_json(line, echo)
            return

        if echo:
            self._echo(f"> {line}")

        parts = line.split()
        command, arguments = parts[0].lower(), parts[1:]

        try:
            await self._dispatch(command, arguments)
        except (SessionError, ValueError) as exc:
            self.session.log("error", str(exc))
        except Exception as exc:
            self.session.log("error", f"{type(exc).__name__}: {exc}")

    async def _dispatch(self, command: str, arguments: list[str]) -> None:
        """Run a single command"""

        if command in ("quit", "exit", "q"):
            self.running = False
        elif command in ("help", "?"):
            self._echo(HELP)
        elif command == "list":
            self._list_commands(arguments[0] if arguments else None)
        elif command == "state":
            self._show_state()
        elif command == "clear":
            self.session.clear()
            self._echo("Cleared")
        elif command == "detail":
            self._set_detail(arguments)
        elif command == "connect":
            await self.session.connect()
        elif command == "disconnect":
            self.session.disconnect()
        elif command == "wait":
            await self._wait(arguments[0] if arguments else "1")
        elif command == "hex":
            self.session.send_raw(parse_hex_bytes(" ".join(arguments)))
        elif command == "hexcrc":
            self.session.send_raw(parse_hex_bytes(" ".join(arguments)), append_crc=True)
        elif command == "packet":
            await self._send_packet(arguments)
        elif command == "fields":
            self._show_fields(arguments)
        elif command == "send":
            if not arguments:
                raise SessionError("Usage: send <function> [args...]")

            await self._run_client_command(arguments[0], arguments[1:])
        else:
            await self._run_client_command(command, arguments)

    async def _handle_json(self, line: str, echo: bool = False) -> None:
        """Handle a single JSON record"""

        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            self.session.log("error", f"Unable to read the JSON record: {exc}")
            return

        if not isinstance(record, dict):
            self.session.log("error", "A JSON record must be an object")
            return

        # A record from a captured session describes what happened rather than
        # what to do, so only the outgoing half of it is replayed
        if "kind" in record:
            if record["kind"] != SENT:
                return

            # Captured records are long, and what they do is about to be
            # logged anyway, so only written commands are echoed
            echo = False

        if echo:
            self._echo(f"> {line}")

        try:
            await self._dispatch_json(record)
        except (SessionError, ValueError) as exc:
            self.session.log("error", str(exc))
        except Exception as exc:
            self.session.log("error", f"{type(exc).__name__}: {exc}")

    async def _dispatch_json(self, record: dict[str, Any]) -> None:
        """Run the command described by a JSON record

        Raises:
            SessionError: the record could not be carried out
            ValueError: the record is not valid
        """

        if "wait" in record or "sleep" in record:
            await self._wait(record.get("wait", record.get("sleep")))
            return

        if "command" in record:
            arguments = record.get("arguments", record.get("args", []))

            if not isinstance(arguments, list):
                raise ValueError("'arguments' must be a list")

            await self._run_client_command(
                record["command"], [str(argument) for argument in arguments]
            )
        elif "packet" in record:
            await self.session.send_packet(_packet_from_record(record["packet"]))
        elif "raw" in record:
            self.session.send_raw(
                parse_hex_bytes(str(record["raw"])),
                append_crc=bool(record.get("append_crc")),
            )
        elif "text" in record:
            await self.handle(str(record["text"]))
        else:
            raise ValueError(
                "A record needs one of 'command', 'packet', 'raw', 'text' or"
                f" 'wait', got: {', '.join(record) or 'nothing'}"
            )

    async def _wait(self, seconds) -> None:
        """Pause for the given number of seconds

        Raises:
            ValueError: the number of seconds is not valid
        """

        try:
            seconds = float(seconds)
        except (TypeError, ValueError):
            raise ValueError(f"'{seconds}' is not a number of seconds") from None

        await asyncio.sleep(max(seconds, 0))

    def _list_commands(self, text: str = None) -> None:
        """List the functions exposed by the client"""

        for command in self.session.commands:
            if text and text.lower() not in command.name.lower():
                continue

            description = f"  - {command.description}" if command.description else ""

            self._echo(f"{command.signature}{description}")

    def _show_state(self) -> None:
        """Show the data received from the device so far"""

        if not self.session.state:
            self._echo("No data has been received yet")
            return

        for name in sorted(self.session.state):
            self._echo(f"{name} = {self.session.state[name]}")

    def _set_detail(self, arguments: list[str]) -> None:
        """Turn the detailed view on or off"""

        if arguments:
            self.detail = arguments[0].lower() in ("on", "true", "yes", "1")
        else:
            self.detail = not self.detail

        self._echo(f"Detail {'on' if self.detail else 'off'}")

    async def _run_client_command(self, name: str, arguments: list[str]) -> None:
        """Run one of the functions exposed by the client"""

        command = next(
            (
                candidate
                for candidate in self.session.commands
                if candidate.name == name
            ),
            None,
        )

        if not command:
            raise SessionError(
                f"There is no command named '{name}'. Use 'list' to see the"
                " available commands, or 'help' for other options."
            )

        await self.session.run_command(command, command.parse_arguments(arguments))

    def _show_fields(self, arguments: list[str]) -> None:
        """Show the known payload fields of a packet"""

        action, functional_domain, attribute = _parse_packet_target(arguments)

        fields = mapping_fields(action, functional_domain, attribute)

        if not fields:
            attributes = known_attributes(action, functional_domain)

            self._echo(
                f"{action.name} {functional_domain.name} attribute {attribute}"
                " has no known fields."
                + (
                    f" Known attributes: {', '.join(str(a) for a in attributes)}"
                    if attributes
                    else ""
                )
            )
            return

        for mapping_field in fields:
            self._echo(f"{mapping_field.name}: {mapping_field.type_name}")

    async def _send_packet(self, arguments: list[str]) -> None:
        """Build and send a packet from its parts"""

        action, functional_domain, attribute = _parse_packet_target(arguments)

        packet = build_packet(action, functional_domain, attribute, arguments[3:])

        await self.session.send_packet(packet)


def _parse_packet_target(arguments: list[str]) -> tuple[Action, FunctionalDomain, int]:
    """Parse the action, functional domain and attribute of a packet"""

    if len(arguments) < 3:
        raise SessionError(
            "Usage: packet <action> <domain> <attribute> [name=value... | hex]"
        )

    action = parse_enum(Action, arguments[0])
    functional_domain = parse_enum(FunctionalDomain, arguments[1])

    try:
        attribute = int(arguments[2], 0)
    except ValueError:
        raise SessionError(f"'{arguments[2]}' is not a valid attribute") from None

    return action, functional_domain, attribute


def _packet_from_record(record: Any):
    """Build a packet from the 'packet' part of a JSON record

    Raises:
        SessionError: the record is missing a part of the packet
        ValueError: a part of the packet is not valid
    """

    if not isinstance(record, dict):
        raise ValueError("'packet' must be an object")

    if "attribute" not in record:
        raise SessionError("A packet record needs an 'attribute'")

    action = parse_enum(Action, str(record.get("action", "")))
    functional_domain = parse_enum(
        FunctionalDomain,
        str(record.get("functional_domain", record.get("domain", ""))),
    )

    try:
        attribute = int(record["attribute"])
    except (TypeError, ValueError):
        raise ValueError(f"'{record['attribute']}' is not a valid attribute") from None

    payload = record.get("payload", record.get("raw_data"))

    if payload is not None:
        values = [
            (
                payload
                if isinstance(payload, str)
                else " ".join(f"{value:02x}" for value in payload)
            )
        ]
    else:
        values = [f"{name}={value}" for name, value in record.get("data", {}).items()]

    return build_packet(action, functional_domain, attribute, values)


def _stdin_is_a_file() -> bool:
    """Whether standard input has been redirected from a regular file"""

    try:
        return stat.S_ISREG(os.fstat(sys.stdin.fileno()).st_mode)
    except (OSError, ValueError):
        return False


async def _stdin_reader() -> asyncio.StreamReader:
    """Get a reader for standard input attached to the running loop"""

    reader = asyncio.StreamReader()

    await asyncio.get_event_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin
    )

    return reader
