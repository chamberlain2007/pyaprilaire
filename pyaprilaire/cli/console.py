"""Line based interactive session with a device

This is the front end used when a full screen interface isn't wanted or
isn't available, and is the only front end when JSON goes to standard
output, so that stdout carries nothing but the JSON records.

The commands themselves are the same ones the full screen interface runs,
and live in :mod:`pyaprilaire.cli.script`.
"""

from __future__ import annotations

import asyncio
import os
import stat
import sys
from collections.abc import Iterable

from .script import HELP, ScriptRunner, read_script
from .session import (
    DebugSession,
    LogEntry,
    SessionError,
    check_connection,
    format_entry_lines,
)


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
        self.input_path = input_path
        self.wait = wait
        self.follow = follow

        self.runner = ScriptRunner(session, echo=self._echo, detail=detail)

        session.add_entry_listener(self._write_entry)

    @property
    def running(self) -> bool:
        """Whether the session is still running"""
        return self.runner.running

    @running.setter
    def running(self, running: bool) -> None:
        self.runner.running = running

    @property
    def detail(self) -> bool:
        """Whether hex dumps and full payloads are shown"""
        return self.runner.detail

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

    async def handle(self, line: str, echo: bool = False) -> None:
        """Handle a single line of input"""
        await self.runner.handle(line, echo=echo)

    async def run_script(self, lines: Iterable[str]) -> None:
        """Run a sequence of commands, stopping early if one of them quits"""
        await self.runner.run(lines)

    async def test_connection(self) -> bool:
        """Connect, report whether the device answers and disconnect

        Returns:
            Whether the device answered
        """

        try:
            return await check_connection(self.session)
        finally:
            await self.session.close()

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
            lines = read_script(path)
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
