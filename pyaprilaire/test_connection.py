"""Utility for testing connection to AprilAire thermostat"""

from __future__ import annotations

import argparse
import asyncio
import logging

from .client import AprilaireClient
from .const import Attribute

class CustomFormatter(logging.Formatter):
    """Custom logging formatter"""

    green = "\x1b[32;20m"
    cyan = "\x1b[36;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    log_format = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

    FORMATS = {
        logging.DEBUG: cyan + log_format + reset,
        logging.INFO: green + log_format + reset,
        logging.WARNING: yellow + log_format + reset,
        logging.ERROR: red + log_format + reset,
        logging.CRITICAL: bold_red + log_format + reset,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)
    
_LOGGER = logging.getLogger("aprilaire.mock_server")
_LOGGER.setLevel(logging.DEBUG)

ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)

ch.setFormatter(CustomFormatter())

_LOGGER.addHandler(ch)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-H", "--host", default="localhost")
    parser.add_argument("-p", "--port", default=7001)

    args = parser.parse_args()

    data = {}

    def data_received_callback(new_data):
        data.update(new_data)

    client = AprilaireClient(args.host, args.port, data_received_callback=data_received_callback, logger=_LOGGER)

    try:
        asyncio.run(client.test_connection())

        if mac_address := data.get(Attribute.MAC_ADDRESS):
            _LOGGER.info("Successfully connected to %s port %s with MAC address %s", args.host, args.port, mac_address)
        else:
            _LOGGER.error("Failed to connect to %s port %s", args.host, args.port)
    except Exception as e:
        _LOGGER.error("Failed to connect to %s port %s: %s", args.host, args.port, getattr(e, 'message', repr(e)))