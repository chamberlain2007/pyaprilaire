"""Mock server for testing Aprilaire integration"""

from __future__ import annotations

import argparse
import asyncio
import logging

from .const import QUEUE_FREQUENCY, Action, Attribute, FunctionalDomain
from .packet import Packet

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


class _AprilaireServerProtocol(asyncio.Protocol):
    def __init__(self):
        self.transport: asyncio.Transport = None

        self.mode = 5
        self.fan_mode = 2
        self.cool_setpoint = 25
        self.heat_setpoint = 20
        self.hold = 0

        self.dehumidification_status = 0
        self.dehumidification_setpoint = 60
        self.humidification_status = 0
        self.humidification_setpoint = 30
        self.fresh_air_mode = 0
        self.fresh_air_event = 0
        self.air_cleaning_mode = 0
        self.air_cleaning_event = 0

        self.name = "Mock"
        self.location = "02134"
        self.mac_address = [1, 2, 3, 4, 5, 6]

        self.packet_queue = asyncio.Queue()

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
                data={Attribute.MAC_ADDRESS: [1, 2, 3, 4, 5, 6]},
            )
        )

        await self.packet_queue.put(
            Packet(
                Action.COS,
                FunctionalDomain.CONTROL,
                1,
                sequence=self._get_sequence(),
                data={
                    Attribute.MODE: 1,
                    Attribute.FAN_MODE: self.fan_mode,
                    Attribute.HEAT_SETPOINT: self.heat_setpoint,
                    Attribute.COOL_SETPOINT: self.cool_setpoint,
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
                    Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS: 0,
                    Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_VALUE: 25,
                    Attribute.OUTDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS: 0,
                    Attribute.OUTDOOR_TEMPERATURE_CONTROLLING_SENSOR_VALUE: 25,
                    Attribute.INDOOR_HUMIDITY_CONTROLLING_SENSOR_STATUS: 0,
                    Attribute.INDOOR_HUMIDITY_CONTROLLING_SENSOR_VALUE: 50,
                    Attribute.OUTDOOR_HUMIDITY_CONTROLLING_SENSOR_STATUS: 0,
                    Attribute.OUTDOOR_HUMIDITY_CONTROLLING_SENSOR_VALUE: 40,
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
                    Attribute.SYNCED: 1,
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
                    Attribute.DEHUMIDIFICATION_STATUS: self.dehumidification_status,
                    Attribute.HUMIDIFICATION_STATUS: self.humidification_status,
                    Attribute.VENTILATION_STATUS: 2 if self.fresh_air_mode else 0,
                    Attribute.AIR_CLEANING_STATUS: 2 if self.air_cleaning_mode else 0,
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
                    Attribute.THERMOSTAT_MODES: 6,
                    Attribute.AIR_CLEANING_AVAILABLE: 1,
                    Attribute.VENTILATION_AVAILABLE: 1,
                    Attribute.DEHUMIDIFICATION_AVAILABLE: 1,
                    Attribute.HUMIDIFICATION_AVAILABLE: 2,
                },
            )
        )

        await self.packet_queue.put(
            Packet(
                Action.COS,
                FunctionalDomain.SETUP,
                1,
                sequence=self._get_sequence(),
                data={Attribute.AWAY_AVAILABLE: 1},
            )
        )

        await self.packet_queue.put(
            Packet(
                Action.COS,
                FunctionalDomain.SCHEDULING,
                4,
                sequence=self._get_sequence(),
                data={Attribute.HOLD: self.hold},
            )
        )

        await self.packet_queue.put(
            Packet(
                Action.COS,
                FunctionalDomain.IDENTIFICATION,
                1,
                sequence=self._get_sequence(),
                data={
                    Attribute.HARDWARE_REVISION: 66,
                    Attribute.FIRMWARE_MAJOR_REVISION: 10,
                    Attribute.FIRMWARE_MINOR_REVISION: 2,
                    Attribute.PROTOCOL_MAJOR_REVISION: 15,
                    Attribute.MODEL_NUMBER: 1,
                    Attribute.GAINSPAN_FIRMWARE_MAJOR_REVISION: 14,
                    Attribute.GAINSPAN_FIRMWARE_MINOR_REVISION: 3,
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
                    Attribute.LOCATION: self.location,
                    Attribute.NAME: self.name,
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
                    Attribute.HEATING_EQUIPMENT_STATUS: {2: 2, 4: 7}.get(self.mode, 0),
                    Attribute.COOLING_EQUIPMENT_STATUS: {3: 2, 5: 2}.get(self.mode, 0),
                    Attribute.PROGRESSIVE_RECOVERY: 0,
                    Attribute.FAN_STATUS: 1
                    if self.fan_mode == 1 or self.fan_mode == 2
                    else 0,
                },
            )
        )

        await self.packet_queue.put(
            Packet(
                Action.COS,
                FunctionalDomain.CONTROL,
                3,
                sequence=self._get_sequence(),
                data={
                    Attribute.DEHUMIDIFICATION_SETPOINT: self.dehumidification_setpoint
                },
            )
        )

        await self.packet_queue.put(
            Packet(
                Action.COS,
                FunctionalDomain.CONTROL,
                4,
                sequence=self._get_sequence(),
                data={Attribute.HUMIDIFICATION_SETPOINT: self.humidification_setpoint},
            )
        )

        await self.packet_queue.put(
            Packet(
                Action.COS,
                FunctionalDomain.CONTROL,
                5,
                sequence=self._get_sequence(),
                data={
                    Attribute.FRESH_AIR_MODE: self.fresh_air_mode,
                    Attribute.FRESH_AIR_EVENT: self.fresh_air_event,
                },
            )
        )

        await self.packet_queue.put(
            Packet(
                Action.COS,
                FunctionalDomain.CONTROL,
                6,
                sequence=self._get_sequence(),
                data={
                    Attribute.AIR_CLEANING_MODE: self.air_cleaning_mode,
                    Attribute.AIR_CLEANING_EVENT: self.air_cleaning_event,
                },
            )
        )

    async def _cos_loop(self):
        """Send the current status (COS) periodically"""
        while self.transport:
            await asyncio.sleep(COS_FREQUENCY)
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
            except asyncio.QueueEmpty:
                pass

            await asyncio.sleep(QUEUE_FREQUENCY)

    def connection_made(self, transport):
        _LOGGER.info("Connection made")

        self.transport = transport

        asyncio.ensure_future(self._cos_loop())
        asyncio.ensure_future(self._queue_loop())

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
                                    Attribute.MODE: self.mode,
                                    Attribute.FAN_MODE: self.fan_mode,
                                    Attribute.HEAT_SETPOINT: self.heat_setpoint,
                                    Attribute.COOL_SETPOINT: self.cool_setpoint,
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
                                    Attribute.THERMOSTAT_MODES: 6,
                                    Attribute.AIR_CLEANING_AVAILABLE: 1,
                                    Attribute.VENTILATION_AVAILABLE: 1,
                                    Attribute.DEHUMIDIFICATION_AVAILABLE: 1,
                                    Attribute.HUMIDIFICATION_AVAILABLE: 1,
                                },
                            )
                        )
                    elif packet.attribute == 3:
                        self.packet_queue.put_nowait(
                            Packet(
                                Action.READ_RESPONSE,
                                FunctionalDomain.CONTROL,
                                3,
                                sequence=self._get_sequence(),
                                data={
                                    Attribute.DEHUMIDIFICATION_SETPOINT: self.dehumidification_setpoint
                                },
                            )
                        )
                    elif packet.attribute == 4:
                        self.packet_queue.put_nowait(
                            Packet(
                                Action.READ_RESPONSE,
                                FunctionalDomain.CONTROL,
                                4,
                                sequence=self._get_sequence(),
                                data={
                                    Attribute.HUMIDIFICATION_SETPOINT: self.humidification_setpoint
                                },
                            )
                        )
                    elif packet.attribute == 5:
                        self.packet_queue.put_nowait(
                            Packet(
                                Action.READ_RESPONSE,
                                FunctionalDomain.CONTROL,
                                5,
                                sequence=self._get_sequence(),
                                data={
                                    Attribute.FRESH_AIR_MODE: self.fresh_air_mode,
                                    Attribute.FRESH_AIR_EVENT: self.fresh_air_event,
                                },
                            )
                        )
                    elif packet.attribute == 6:
                        self.packet_queue.put_nowait(
                            Packet(
                                Action.READ_RESPONSE,
                                FunctionalDomain.CONTROL,
                                6,
                                sequence=self._get_sequence(),
                                data={
                                    Attribute.AIR_CLEANING_MODE: self.air_cleaning_mode,
                                    Attribute.AIR_CLEANING_EVENT: self.air_cleaning_event,
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
                                    Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS: 0,
                                    Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_VALUE: 25,
                                    Attribute.OUTDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS: 0,
                                    Attribute.OUTDOOR_TEMPERATURE_CONTROLLING_SENSOR_VALUE: 25,
                                    Attribute.INDOOR_HUMIDITY_CONTROLLING_SENSOR_STATUS: 0,
                                    Attribute.INDOOR_HUMIDITY_CONTROLLING_SENSOR_VALUE: 50,
                                    Attribute.OUTDOOR_HUMIDITY_CONTROLLING_SENSOR_STATUS: 0,
                                    Attribute.OUTDOOR_HUMIDITY_CONTROLLING_SENSOR_VALUE: 40,
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
                                data={Attribute.HOLD: self.hold},
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
                                data={Attribute.MAC_ADDRESS: self.mac_address},
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
                                    Attribute.LOCATION: self.location,
                                    Attribute.NAME: self.name,
                                },
                            )
                        )
            elif packet.action == Action.WRITE:
                if packet.functional_domain == FunctionalDomain.CONTROL:
                    if packet.attribute == 1:
                        if Attribute.MODE in packet.data:
                            new_mode = packet.data[Attribute.MODE]

                            if new_mode != 0:
                                self.mode = new_mode
                                self.hold = 0

                        if Attribute.FAN_MODE in packet.data:
                            new_fan_mode = packet.data[Attribute.FAN_MODE]

                            if new_fan_mode != 0:
                                self.fan_mode = new_fan_mode

                        if Attribute.HEAT_SETPOINT in packet.data:
                            new_heat_setpoint = packet.data[Attribute.HEAT_SETPOINT]

                            if new_heat_setpoint != 0:
                                self.heat_setpoint = new_heat_setpoint
                                self.hold = 1

                        if Attribute.COOL_SETPOINT in packet.data:
                            new_cool_setpoint = packet.data[Attribute.COOL_SETPOINT]

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
                                    Attribute.MODE: self.mode,
                                    Attribute.FAN_MODE: self.fan_mode,
                                    Attribute.HEAT_SETPOINT: self.heat_setpoint,
                                    Attribute.COOL_SETPOINT: self.cool_setpoint,
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
                                    Attribute.HEATING_EQUIPMENT_STATUS: {
                                        2: 2,
                                        4: 7,
                                    }.get(self.mode, 0),
                                    Attribute.COOLING_EQUIPMENT_STATUS: {
                                        3: 2,
                                        5: 2,
                                    }.get(self.mode, 0),
                                    Attribute.PROGRESSIVE_RECOVERY: 0,
                                    Attribute.FAN_STATUS: 1
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
                                data={Attribute.HOLD: self.hold},
                            )
                        )
                    elif packet.attribute == 3:
                        self.dehumidification_setpoint = packet.data[
                            Attribute.DEHUMIDIFICATION_SETPOINT
                        ]
                        self.dehumidification_status = 2

                        self.packet_queue.put_nowait(
                            Packet(
                                Action.COS,
                                FunctionalDomain.CONTROL,
                                3,
                                sequence=self._get_sequence(),
                                data={Attribute.DEHUMIDIFICATION_SETPOINT: self.dehumidification_setpoint},
                            )
                        )
                    elif packet.attribute == 4:
                        self.humidification_setpoint = packet.data[
                            Attribute.HUMIDIFICATION_SETPOINT
                        ]
                        self.humidification_status = 2

                        self.packet_queue.put_nowait(
                            Packet(
                                Action.COS,
                                FunctionalDomain.CONTROL,
                                4,
                                sequence=self._get_sequence(),
                                data={Attribute.HUMIDIFICATION_SETPOINT: self.humidification_setpoint},
                            )
                        )
                    elif packet.attribute == 5:
                        self.fresh_air_mode = packet.data[Attribute.FRESH_AIR_MODE]
                        self.fresh_air_event = packet.data[Attribute.FRESH_AIR_EVENT]

                        self.packet_queue.put_nowait(
                            Packet(
                                Action.COS,
                                FunctionalDomain.CONTROL,
                                5,
                                sequence=self._get_sequence(),
                                data={
                                    Attribute.FRESH_AIR_MODE: self.fresh_air_mode,
                                    Attribute.FRESH_AIR_EVENT: self.fresh_air_event,
                                },
                            )
                        )

                    if packet.attribute in [3, 4, 5]:
                        self.packet_queue.put_nowait(
                            Packet(
                                Action.COS,
                                FunctionalDomain.STATUS,
                                7,
                                sequence=self._get_sequence(),
                                data={
                                    Attribute.DEHUMIDIFICATION_STATUS: self.dehumidification_status,
                                    Attribute.HUMIDIFICATION_STATUS: self.humidification_status,
                                    Attribute.VENTILATION_STATUS: 2
                                    if self.fresh_air_mode
                                    else 0,
                                    Attribute.AIR_CLEANING_STATUS: 2
                                    if self.air_cleaning_mode
                                    else 0,
                                },
                            )
                        )
                    elif packet.attribute == 6:
                        self.air_cleaning_mode = packet.data[
                            Attribute.AIR_CLEANING_MODE
                        ]
                        self.air_cleaning_event = packet.data[
                            Attribute.AIR_CLEANING_EVENT
                        ]

                        self.packet_queue.put_nowait(
                            Packet(
                                Action.COS,
                                FunctionalDomain.CONTROL,
                                6,
                                sequence=self._get_sequence(),
                                data={
                                    Attribute.AIR_CLEANING_MODE: self.air_cleaning_mode,
                                    Attribute.AIR_CLEANING_EVENT: self.air_cleaning_event,
                                },
                            )
                        )

                        self.packet_queue.put_nowait(
                            Packet(
                                Action.COS,
                                FunctionalDomain.STATUS,
                                7,
                                sequence=self._get_sequence(),
                                data={
                                    Attribute.DEHUMIDIFICATION_STATUS: 2,
                                    Attribute.HUMIDIFICATION_STATUS: 2,
                                    Attribute.VENTILATION_STATUS: 2
                                    if self.fresh_air_mode
                                    else 0,
                                    Attribute.AIR_CLEANING_STATUS: 2
                                    if self.air_cleaning_mode
                                    else 0,
                                },
                            )
                        )

                elif packet.functional_domain == FunctionalDomain.SCHEDULING:
                    if packet.attribute == 4:
                        if Attribute.HOLD in packet.data:
                            self.hold = packet.data[Attribute.HOLD]

                        self.packet_queue.put_nowait(
                            Packet(
                                Action.COS,
                                FunctionalDomain.SCHEDULING,
                                4,
                                sequence=self._get_sequence(),
                                data={Attribute.HOLD: self.hold},
                            )
                        )
                elif packet.functional_domain == FunctionalDomain.STATUS:
                    if packet.attribute == 2:
                        asyncio.ensure_future(self._send_status())

    def connection_lost(self, exc: Exception | None) -> None:
        _LOGGER.info("Connection lost")
        self.transport = None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-H", "--host", default="localhost")
    parser.add_argument("-p", "--port", default=7001)

    args = parser.parse_args()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.create_task(loop.create_server(_AprilaireServerProtocol, args.host, args.port))

    _LOGGER.info("Server listening on %s port %d", args.host, args.port)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
