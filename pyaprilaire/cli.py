"""Interactive session with a thermostat

Connects to a device, sends commands to it and shows every message in both
its raw form and its decoded form.

    python -m pyaprilaire.cli --host 192.168.1.5
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .console import ConsoleSession
from .session import DEFAULT_PORT, DebugSession, EntryWriter

TEXTUAL_MISSING = (
    "The full screen interface requires Textual, which is not installed."
    " Install it with 'pip install pyaprilaire[cli]', or use --no-tui for the"
    " line based interface."
)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the interactive session"""

    parser = argparse.ArgumentParser(
        prog="pyaprilaire",
        description="Interactively send commands to a thermostat and see the"
        " messages it sends back, as both raw and decoded packets.",
    )

    parser.add_argument("-H", "--host", default="localhost", help="device host")
    parser.add_argument(
        "-p", "--port", type=int, default=DEFAULT_PORT, help="device port"
    )
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="use the line based interface instead of the full screen one",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="write each message as a JSON object on its own line, which"
        " implies --no-tui so that only JSON is written to stdout",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="also write every message to this file, as JSON when --json is"
        " given and as text otherwise",
    )
    parser.add_argument(
        "-i",
        "--input",
        help="run the commands in this file, as either the text you would"
        " type or one JSON record per line, then continue interactively if"
        " there is a terminal; '-' reads them from standard input. Implies"
        " --no-tui. Commands are also read from standard input when it is"
        " piped in",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=2.0,
        metavar="SECONDS",
        help="how long to stay connected after scripted commands run out, so"
        " that the responses to them arrive (default: 2)",
    )
    parser.add_argument(
        "-f",
        "--follow",
        action="store_true",
        help="stay connected after scripted commands run out, until"
        " interrupted, rather than waiting a fixed time",
    )
    parser.add_argument(
        "--no-auto-status",
        action="store_true",
        help="don't send the usual startup requests when connecting, so that"
        " only the commands you send appear",
    )
    parser.add_argument(
        "--reconnect",
        action="store_true",
        help="keep reconnecting when the connection is lost or refused",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="start with hex dumps and full payloads shown",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="write client logging to stderr, which is ignored by the full"
        " screen interface as it would corrupt the display",
    )

    return parser


def _build_logger(verbose: bool, use_tui: bool) -> logging.Logger:
    """Build the logger used by the client"""

    logger = logging.getLogger("pyaprilaire.cli")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False
    logger.handlers.clear()

    if verbose and not use_tui:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    else:
        logger.addHandler(logging.NullHandler())

    return logger


def main(argv: list[str] = None) -> int:
    """Run an interactive session"""

    args = build_parser().parse_args(argv)

    # JSON output owns stdout, and scripted commands need somewhere to be
    # typed, so neither can use the full screen interface
    use_tui = not (args.no_tui or args.json or args.input)

    if use_tui:
        try:
            from .tui import AprilaireTui  # pylint: disable=import-outside-toplevel
        except ImportError:
            print(TEXTUAL_MISSING, file=sys.stderr)
            return 2

    session = DebugSession(
        args.host,
        args.port,
        logger=_build_logger(args.verbose, use_tui),
        auto_status=not args.no_auto_status,
        reconnect=args.reconnect,
    )

    writer = (
        EntryWriter(args.output, as_json=args.json, detail=args.detail)
        if args.output
        else None
    )

    if writer:
        session.add_entry_listener(writer)

    try:
        if use_tui:
            AprilaireTui(session, detail=args.detail).run()
        else:
            asyncio.run(
                ConsoleSession(
                    session,
                    json_output=args.json,
                    detail=args.detail,
                    input_path=args.input,
                    wait=args.wait,
                    follow=args.follow,
                ).run()
            )
    except KeyboardInterrupt:
        pass
    finally:
        if writer:
            writer.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
