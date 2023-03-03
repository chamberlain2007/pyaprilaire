"""Mock server for testing Aprilaire integration"""

from __future__ import annotations

import argparse
from asyncio import (
    ensure_future,
    new_event_loop,
    set_event_loop,
    sleep,
    Queue,
    QueueEmpty,
    Protocol,
    Transport,
)
import logging

from .const import Action, FunctionalDomain, QUEUE_FREQUENCY
from .packet import NackPacket, Packet

COS_FREQUENCY = 30


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


class _AprilaireServerProtocol(Protocol):
    def __init__(self):
        self.transport: Transport = None

        self.mode = 5
        self.fan_mode = 2
        self.cool_setpoint = 25
        self.heat_setpoint = 20
        self.hold = 0

        self.name = "Mock"
        self.location = "02134"
        self.mac_address = [1, 2, 3, 4, 5, 6]

        self.packet_queue = Queue()

        self.sequence = 0

    def _get_sequence(self):
        """Get and increment the current sequence"""
        self.sequence = (self.sequence + 1) % 128

        return self.sequence

    async def _send_status(self):
        """Send the current status"""

        await self.packet_queue.put(
            Packet(
                Action.READ_RESPONSE,
                FunctionalDomain.IDENTIFICATION,
                2,
                sequence=self._get_sequence(),
                data={"mac_address": [1, 2, 3, 4, 5, 6]},
            )
        )

        await self.packet_queue.put(
            Packet(
                Action.COS,
                FunctionalDomain.CONTROL,
                1,
                sequence=self._get_sequence(),
                data={
                    "mode": 1,
                    "fan_mode": self.fan_mode,
                    "heat_setpoint": self.heat_setpoint,
                    "cool_setpoint": self.cool_setpoint,
                },
            )
        )

        await self.packet_queue.put(
            Packet(
                Action.COS,
                FunctionalDomain.SENSORS,
                2,
                sequence=self._get_sequence(),
                data={
                    "indoor_temperature_controlling_sensor_status": 0,
                    "indoor_temperature_controlling_sensor_value": 25,
                    "outdoor_temperature_controlling_sensor_status": 0,
                    "outdoor_temperature_controlling_sensor_value": 25,
                    "indoor_humidity_controlling_sensor_status": 0,
                    "indoor_humidity_controlling_sensor_value": 50,
                    "outdoor_humidity_controlling_sensor_status": 0,
                    "outdoor_humidity_controlling_sensor_value": 40,
                },
            )
        )

        await self.packet_queue.put(
            Packet(
                Action.COS,
                FunctionalDomain.STATUS,
                2,
                sequence=self._get_sequence(),
                data={
                    "synced": 1,
                },
            )
        )

        await self.packet_queue.put(
            Packet(
                Action.COS,
                FunctionalDomain.STATUS,
                7,
                sequence=self._get_sequence(),
                data={
                    "dehumidification_status": 2,
                    "humidification_status": 2,
                    "ventilation_status": 2,
                    "air_cleaning_status": 2,
                },
            )
        )

        await self.packet_queue.put(
            Packet(
                Action.COS,
                FunctionalDomain.CONTROL,
                7,
                sequence=self._get_sequence(),
                data={
                    "thermostat_modes": 6,
                    "air_cleaning_available": 1,
                    "ventilation_available": 1,
                    "dehumidification_available": 1,
                    "humidification_available": 1,
                },
            )
        )

        await self.packet_queue.put(
            Packet(
                Action.COS,
                FunctionalDomain.SETUP,
                1,
                sequence=self._get_sequence(),
                data={"away_available": 1},
            )
        )

        await self.packet_queue.put(
            Packet(
                Action.COS,
                FunctionalDomain.SCHEDULING,
                4,
                sequence=self._get_sequence(),
                data={"hold": self.hold},
            )
        )

        await self.packet_queue.put(
            Packet(
                Action.COS,
                FunctionalDomain.IDENTIFICATION,
                1,
                sequence=self._get_sequence(),
                data={
                    "hardware_revision": 66,
                    "firmware_major_revision": 10,
                    "firmware_minor_revision": 2,
                    "protocol_major_revision": 15,
                    "model_number": 1,
                    "gainspan_firmware_major_revision": 14,
                    "gainspan_firmware_minor_revision": 3,
                },
            )
        )

        await self.packet_queue.put(
            Packet(
                Action.COS,
                FunctionalDomain.IDENTIFICATION,
                4,
                sequence=self._get_sequence(),
                data={
                    "location": self.location,
                    "name": self.name,
                },
            )
        )

        await self.packet_queue.put(
            Packet(
                Action.COS,
                FunctionalDomain.STATUS,
                6,
                sequence=self._get_sequence(),
                data={
                    "heating_equipment_status": {2: 2, 4: 7}.get(self.mode, 0),
                    "cooling_equipment_status": {3: 2, 5: 2}.get(self.mode, 0),
                    "progressive_recovery": 0,
                    "fan_status": 1 if self.fan_mode == 1 or self.fan_mode == 2 else 0,
                },
            )
        )

    async def _cos_loop(self):
        """Send the current status (COS) periodically"""
        while self.transport:
            await sleep(COS_FREQUENCY)
            await self._send_status()

    async def _queue_loop(self):
        """Periodically send items from the queue"""
        while self.transport:
            try:
                packet: Packet

                while packet := self.packet_queue.get_nowait():
                    if self.transport:
                        serialized_packet = packet.serialize()

                        _LOGGER.info("Sent data: %s", serialized_packet.hex(" "))

                        self.transport.write(serialized_packet)
            except QueueEmpty:
                pass

            await sleep(QUEUE_FREQUENCY)

    def connection_made(self, transport):
        _LOGGER.info("Connection made")

        self.transport = transport

        ensure_future(self._cos_loop())
        ensure_future(self._queue_loop())

    def data_received(self, data: bytes) -> None:
        _LOGGER.info("Received data: %s", data.hex(" ", 1))

        parsed_packets = Packet.parse(data)

        for packet in parsed_packets:
            if packet.action == Action.READ_REQUEST:
                if packet.functional_domain == FunctionalDomain.CONTROL:
                    if packet.attribute == 1:
                        self.packet_queue.put_nowait(
                            Packet(
                                Action.READ_RESPONSE,
                                FunctionalDomain.CONTROL,
                                1,
                                sequence=self._get_sequence(),
                                data={
                                    "mode": self.mode,
                                    "fan_mode": self.fan_mode,
                                    "heat_setpoint": self.heat_setpoint,
                                    "cool_setpoint": self.cool_setpoint,
                                },
                            )
                        )
                    elif packet.attribute == 7:
                        self.packet_queue.put_nowait(
                            Packet(
                                Action.READ_RESPONSE,
                                FunctionalDomain.CONTROL,
                                7,
                                sequence=self._get_sequence(),
                                data={
                                    "thermostat_modes": 6,
                                    "air_cleaning_available": 1,
                                    "ventilation_available": 1,
                                    "dehumidification_available": 1,
                                    "humidification_available": 1,
                                },
                            )
                        )
                elif packet.functional_domain == FunctionalDomain.SENSORS:
                    if packet.attribute == 2:
                        self.packet_queue.put_nowait(
                            Packet(
                                Action.READ_RESPONSE,
                                FunctionalDomain.SENSORS,
                                2,
                                sequence=self._get_sequence(),
                                data={
                                    "indoor_temperature_controlling_sensor_status": 0,
                                    "indoor_temperature_controlling_sensor_value": 25,
                                    "outdoor_temperature_controlling_sensor_status": 0,
                                    "outdoor_temperature_controlling_sensor_value": 25,
                                    "indoor_humidity_controlling_sensor_status": 0,
                                    "indoor_humidity_controlling_sensor_value": 50,
                                    "outdoor_humidity_controlling_sensor_status": 0,
                                    "outdoor_humidity_controlling_sensor_value": 40,
                                },
                            )
                        )
                elif packet.functional_domain == FunctionalDomain.SCHEDULING:
                    if packet.attribute == 4:
                        self.packet_queue.put_nowait(
                            Packet(
                                Action.READ_RESPONSE,
                                FunctionalDomain.SCHEDULING,
                                4,
                                sequence=self._get_sequence(),
                                data={"hold": self.hold},
                            )
                        )
                elif packet.functional_domain == FunctionalDomain.IDENTIFICATION:
                    if packet.attribute == 2:
                        self.packet_queue.put_nowait(
                            Packet(
                                Action.READ_RESPONSE,
                                FunctionalDomain.IDENTIFICATION,
                                2,
                                sequence=self._get_sequence(),
                                data={"mac_address": self.mac_address},
                            )
                        )
                    elif packet.attribute == 4 or packet.attribute == 5:
                        self.packet_queue.put_nowait(
                            Packet(
                                Action.READ_RESPONSE,
                                FunctionalDomain.IDENTIFICATION,
                                4,
                                sequence=self._get_sequence(),
                                data={
                                    "location": self.location,
                                    "name": self.name,
                                },
                            )
                        )
            elif packet.action == Action.WRITE:
                if packet.functional_domain == FunctionalDomain.CONTROL:
                    if packet.attribute == 1:
                        if "mode" in packet.data:
                            new_mode = packet.data["mode"]

                            if new_mode != 0:
                                self.mode = new_mode
                                self.hold = 0

                        if "fan_mode" in packet.data:
                            new_fan_mode = packet.data["fan_mode"]

                            if new_fan_mode != 0:
                                self.fan_mode = new_fan_mode

                        if "heat_setpoint" in packet.data:
                            new_heat_setpoint = packet.data["heat_setpoint"]

                            if new_heat_setpoint != 0:
                                self.heat_setpoint = new_heat_setpoint
                                self.hold = 1

                        if "cool_setpoint" in packet.data:
                            new_cool_setpoint = packet.data["cool_setpoint"]

                            if new_cool_setpoint != 0:
                                self.cool_setpoint = new_cool_setpoint
                                self.hold = 1

                        self.packet_queue.put_nowait(
                            Packet(
                                Action.COS,
                                FunctionalDomain.CONTROL,
                                1,
                                sequence=self._get_sequence(),
                                data={
                                    "mode": self.mode,
                                    "fan_mode": self.fan_mode,
                                    "heat_setpoint": self.heat_setpoint,
                                    "cool_setpoint": self.cool_setpoint,
                                },
                            )
                        )

                        self.packet_queue.put_nowait(
                            Packet(
                                Action.COS,
                                FunctionalDomain.STATUS,
                                6,
                                sequence=self._get_sequence(),
                                data={
                                    "heating_equipment_status": {2: 2, 4: 7}.get(
                                        self.mode, 0
                                    ),
                                    "cooling_equipment_status": {3: 2, 5: 2}.get(
                                        self.mode, 0
                                    ),
                                    "progressive_recovery": 0,
                                    "fan_status": 1
                                    if self.fan_mode == 1 or self.fan_mode == 2
                                    else 0,
                                },
                            )
                        )

                        self.packet_queue.put_nowait(
                            Packet(
                                Action.COS,
                                FunctionalDomain.SCHEDULING,
                                4,
                                sequence=self._get_sequence(),
                                data={"hold": self.hold},
                            )
                        )

                elif packet.functional_domain == FunctionalDomain.SCHEDULING:
                    if packet.attribute == 4:
                        if "hold" in packet.data:
                            self.hold = packet.data["hold"]

                        self.packet_queue.put_nowait(
                            Packet(
                                Action.COS,
                                FunctionalDomain.SCHEDULING,
                                4,
                                sequence=self._get_sequence(),
                                data={"hold": self.hold},
                            )
                        )
                elif packet.functional_domain == FunctionalDomain.STATUS:
                    if packet.attribute == 2:
                        ensure_future(self._send_status())

    def connection_lost(self, exc: Exception | None) -> None:
        _LOGGER.info("Connection lost")
        self.transport = None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-H", "--host", default="localhost")
    parser.add_argument("-p", "--port", default=7001)

    args = parser.parse_args()

    loop = new_event_loop()
    set_event_loop(loop)

    loop.create_task(loop.create_server(_AprilaireServerProtocol, args.host, args.port))

    _LOGGER.info("Server listening on %s port %d", args.host, args.port)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
