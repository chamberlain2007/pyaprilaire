"""Line based interactive session with a device

This is the front end used when a full screen interface isn't wanted or
isn't available, and is the only front end when output is JSON, so that
stdout carries nothing but the JSON records.
"""

from __future__ import annotations

import asyncio
import sys

from .commands import (
    build_packet,
    known_attributes,
    mapping_fields,
    parse_enum,
    parse_hex_bytes,
)
from .const import Action, FunctionalDomain
from .session import DebugSession, LogEntry, SessionError, format_entry_lines

HELP = """
Commands:
  list [text]                 List the client functions, optionally filtered
  <function> [args...]        Run a client function, e.g. update_mode 3
  send <function> [args...]   Run a client function whose name collides with a
                              command below
  packet <action> <domain> <attribute> [values]
                              Send a packet, where values are either name=value
                              pairs for a known packet or raw payload hex
  hex <bytes>                 Write raw bytes exactly as given
  hexcrc <bytes>              Write raw bytes with a calculated CRC appended
  fields <action> <domain> <attribute>
                              Show the known payload fields of a packet
  state                       Show the data received from the device so far
  connect / disconnect        Open or close the connection
  detail [on|off]             Show or hide hex dumps and full payloads
  clear                       Clear the recorded entries
  help                        Show this help
  quit                        Leave the session
""".strip()


class ConsoleSession:
    """Runs an interactive session over plain input and output"""

    def __init__(
        self,
        session: DebugSession,
        json_output: bool = False,
        detail: bool = False,
    ) -> None:
        self.session = session
        self.json_output = json_output
        self.detail = detail

        self.running = False

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
        """Run until the user leaves the session or input ends"""

        self.running = True

        self._echo(HELP)
        self._echo()

        try:
            await self.session.connect()
        except (OSError, SessionError) as exc:
            self.session.log("error", f"Unable to connect: {exc}")

        reader = await _stdin_reader()

        while self.running:
            line = await reader.readline()

            if not line:
                break

            await self.handle(line.decode(errors="replace").strip())

        await self.session.close()

    async def handle(self, line: str) -> None:
        """Handle a single line of input"""

        if not line or line.startswith("#"):
            return

        parts = line.split()
        command, arguments = parts[0].lower(), parts[1:]

        try:
            await self._dispatch(command, arguments, line)
        except SessionError as exc:
            self.session.log("error", str(exc))
        except ValueError as exc:
            self.session.log("error", str(exc))
        except Exception as exc:  # pylint: disable=broad-except
            self.session.log("error", f"{type(exc).__name__}: {exc}")

    async def _dispatch(self, command: str, arguments: list[str], line: str) -> None:
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

        del line

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


async def _stdin_reader() -> asyncio.StreamReader:
    """Get a reader for standard input attached to the running loop"""

    reader = asyncio.StreamReader()

    await asyncio.get_event_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin
    )

    return reader
