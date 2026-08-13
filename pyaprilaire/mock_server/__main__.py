"""Entry point for running the mock server"""

from __future__ import annotations

import argparse
import asyncio

from . import _LOGGER, _AprilaireServerProtocol


def main() -> None:
    """Run a mock server until it is interrupted"""

    parser = argparse.ArgumentParser(prog="pyaprilaire.mock_server")
    parser.add_argument("-H", "--host", default="localhost")
    parser.add_argument("-p", "--port", default=7001, type=int)

    args = parser.parse_args()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.create_task(loop.create_server(_AprilaireServerProtocol, args.host, args.port))

    _LOGGER.info("Server listening on %s port %d", args.host, args.port)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
