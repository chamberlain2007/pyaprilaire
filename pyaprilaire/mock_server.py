"""Mock server for testing Aprilaire integration"""

from __future__ import annotations

import argparse
import asyncio
import logging

from .const import QUEUE_FREQUENCY, Action, Attribute, FunctionalDomain
from .packet import MAPPING, NackPacket, Packet

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

        # Written Outdoor Temperature Value (spec 5.4). Defaults to Timed
        # Out until the automation system writes a value.
        self.outdoor_sensor_status = 4
        self.outdoor_sensor_value = 0

        self.error = 0  # No Error (spec 7.8)

        # All COS subscription outputs are enabled by default (spec 7.1). A
        # WRITE to STATUS 0x01 (COS Subscriptions) overwrites this mask; see
        # _configure_cos. The mock doesn't yet act on it - that lands with
        # the Sync-flow fix - it's just stored/parsed correctly for now.
        self.cos_mask = [1] * 29

        self.packet_queue = asyncio.Queue()

        # Messages sent by the Thermostat use sequence numbers 128-255
        # (spec F, note 1). Starting at 127 makes the first _get_sequence()
        # call return 128.
        self.sequence = 127

    def _get_sequence(self):
        """Get and increment the current sequence number.

        Only for messages the mock originates itself (COS). Read responses
        instead echo the sequence of the request that triggered them (spec
        F, note 2) - see the READ_RESPONSE packets below, which use
        packet.sequence rather than this method.
        """
        self.sequence = 128 + ((self.sequence + 1) % 128)

        return self.sequence

    def _send_nack(self, status_code: int, sequence: int) -> None:
        """Send a NACK with the given status code (spec H.5), echoing the
        sequence number of the request it corresponds to."""
        _LOGGER.warning("Sending NACK 0x%02X for sequence %d", status_code, sequence)
        self.packet_queue.put_nowait(NackPacket(status_code, sequence=sequence))

    def _configure_cos(self, raw_mask: list[int]) -> None:
        """Handle a WRITE to STATUS 0x01 (COS Subscriptions, spec 7.1).

        packet.py's MAPPING has no schema for this attribute - client.py
        sends it as 29 unstructured raw bytes - so Packet.parse() can't
        yield it as a Packet the way it does every other attribute; see
        _prescan_raw_frames for where this is detected instead.
        """
        _LOGGER.info("Configuring COS subscriptions: %s", raw_mask)
        self.cos_mask = raw_mask

    def _prescan_raw_frames(self, data: bytes) -> None:
        """Walk the raw frame stream the same way Packet.parse() does, to
        catch frames it silently drops before they ever become a Packet the
        rest of this class can see: an unrecognized action (NACK 0x05), an
        unrecognized or unsupported functional domain (0x06), or an
        attribute this action/domain doesn't define (0x07) - spec H.5: "A
        NAck is sent in response to any unhandled, corrupt, or
        un-parse-able action received with a suitable status code." Also
        picks out the WRITE STATUS 0x01 (COS Subscriptions) case - see
        _configure_cos - which packet.py's parser would otherwise treat the
        same as any other unmapped attribute, even though it's a legitimate,
        spec-documented one (spec 7.1), and a READ_REQUEST for SETUP 0x08
        (Reset), which has no MAPPING schema at all despite being a real,
        write-only attribute (spec 1.8) - so it gets 0x20 (write-only)
        instead of the generic 0x07 fallback.

        NOTE: this necessarily duplicates a small amount of Packet.parse()'s
        header-walking logic (revision/sequence/count/action/domain/
        attribute + CRC), since Packet.parse() itself silently drops these
        frames instead of yielding anything the mock could respond to. It
        intentionally stays out of packet.py, which is outside this
        change's scope; see the PR description for the packet.py-side fix
        this should eventually be replaced by (yielding an "unparseable"
        marker instead of silently dropping the frame).
        """
        index = 0

        while index + 7 <= len(data):
            sequence = data[index + 1]
            count = (data[index + 2] << 2) | data[index + 3]
            action_byte = data[index + 4]
            domain_byte = data[index + 5]
            attribute = data[index + 6]

            crc_index = index + count + 4
            if crc_index >= len(data):
                break

            next_index = crc_index + 1

            if not Packet._verify_crc(data[index:crc_index], data[crc_index]):
                index = next_index
                continue

            try:
                action = Action(action_byte)
            except ValueError:
                self._send_nack(0x05, sequence)
                index = next_index
                continue

            if action == Action.NACK:
                index = next_index
                continue

            try:
                domain = FunctionalDomain(domain_byte)
            except ValueError:
                self._send_nack(0x06, sequence)
                index = next_index
                continue

            if (
                action == Action.WRITE
                and domain == FunctionalDomain.STATUS
                and attribute == 1
            ):
                self._configure_cos(list(data[index + 7 : crc_index]))
            elif (
                action == Action.READ_REQUEST
                and domain == FunctionalDomain.SETUP
                and attribute == 8
            ):
                self._send_nack(0x20, sequence)
            elif action not in MAPPING or domain not in MAPPING[action]:
                self._send_nack(0x06, sequence)
            elif attribute not in MAPPING[action][domain]:
                self._send_nack(0x07, sequence)

            index = next_index

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
                    Attribute.FAN_STATUS: (
                        1 if self.fan_mode == 1 or self.fan_mode == 2 else 0
                    ),
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
                        try:
                            serialized_packet = packet.serialize()
                        except Exception:
                            _LOGGER.exception(
                                "Failed to serialize outgoing packet; dropping it "
                                "and continuing"
                            )
                            continue

                        _LOGGER.info("Sent data: %s", serialized_packet.hex(" "))

                        self.transport.write(serialized_packet)
            except asyncio.QueueEmpty:
                pass
            except Exception:
                # A real device wouldn't drop the connection because one
                # outgoing packet was bad - log it and keep the loop (and
                # therefore the connection) alive.
                _LOGGER.exception("Unexpected error in queue loop")

            await asyncio.sleep(QUEUE_FREQUENCY)

    def connection_made(self, transport):
        _LOGGER.info("Connection made")

        self.transport = transport

        asyncio.ensure_future(self._cos_loop())
        asyncio.ensure_future(self._queue_loop())

    def data_received(self, data: bytes) -> None:
        _LOGGER.info("Received data: %s", data.hex(" ", 1))

        self._prescan_raw_frames(data)

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
                                sequence=packet.sequence,
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
                                sequence=packet.sequence,
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
                                sequence=packet.sequence,
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
                                sequence=packet.sequence,
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
                                sequence=packet.sequence,
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
                                sequence=packet.sequence,
                                data={
                                    Attribute.AIR_CLEANING_MODE: self.air_cleaning_mode,
                                    Attribute.AIR_CLEANING_EVENT: self.air_cleaning_event,
                                },
                            )
                        )
                    else:
                        self._send_nack(0x07, packet.sequence)
                elif packet.functional_domain == FunctionalDomain.SENSORS:
                    if packet.attribute == 2:
                        self.packet_queue.put_nowait(
                            Packet(
                                Action.READ_RESPONSE,
                                FunctionalDomain.SENSORS,
                                2,
                                sequence=packet.sequence,
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
                    else:
                        self._send_nack(0x07, packet.sequence)
                elif packet.functional_domain == FunctionalDomain.SCHEDULING:
                    if packet.attribute == 4:
                        self.packet_queue.put_nowait(
                            Packet(
                                Action.READ_RESPONSE,
                                FunctionalDomain.SCHEDULING,
                                4,
                                sequence=packet.sequence,
                                data={Attribute.HOLD: self.hold},
                            )
                        )
                    else:
                        self._send_nack(0x07, packet.sequence)
                elif packet.functional_domain == FunctionalDomain.IDENTIFICATION:
                    if packet.attribute == 2:
                        self.packet_queue.put_nowait(
                            Packet(
                                Action.READ_RESPONSE,
                                FunctionalDomain.IDENTIFICATION,
                                2,
                                sequence=packet.sequence,
                                data={Attribute.MAC_ADDRESS: self.mac_address},
                            )
                        )
                    elif packet.attribute == 4 or packet.attribute == 5:
                        # Echo whichever attribute was requested - the
                        # client correlates responses by (domain,
                        # attribute), so replying to a 0x05 request with
                        # 0x04 (as this mock used to) resolves against the
                        # wrong key and the caller's request never resolves.
                        self.packet_queue.put_nowait(
                            Packet(
                                Action.READ_RESPONSE,
                                FunctionalDomain.IDENTIFICATION,
                                packet.attribute,
                                sequence=packet.sequence,
                                data={
                                    Attribute.LOCATION: self.location,
                                    Attribute.NAME: self.name,
                                },
                            )
                        )
                    else:
                        self._send_nack(0x07, packet.sequence)
                elif packet.functional_domain == FunctionalDomain.STATUS:
                    if packet.attribute == 2:
                        # Sync is write-only (spec 7.2).
                        self._send_nack(0x20, packet.sequence)
                    elif packet.attribute == 6:
                        self.packet_queue.put_nowait(
                            Packet(
                                Action.READ_RESPONSE,
                                FunctionalDomain.STATUS,
                                6,
                                sequence=packet.sequence,
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
                                    Attribute.FAN_STATUS: (
                                        1
                                        if self.fan_mode == 1 or self.fan_mode == 2
                                        else 0
                                    ),
                                },
                            )
                        )
                    elif packet.attribute == 7:
                        self.packet_queue.put_nowait(
                            Packet(
                                Action.READ_RESPONSE,
                                FunctionalDomain.STATUS,
                                7,
                                sequence=packet.sequence,
                                data={
                                    Attribute.DEHUMIDIFICATION_STATUS: self.dehumidification_status,
                                    Attribute.HUMIDIFICATION_STATUS: self.humidification_status,
                                    Attribute.VENTILATION_STATUS: (
                                        2 if self.fresh_air_mode else 0
                                    ),
                                    Attribute.AIR_CLEANING_STATUS: (
                                        2 if self.air_cleaning_mode else 0
                                    ),
                                },
                            )
                        )
                    elif packet.attribute == 8:
                        self.packet_queue.put_nowait(
                            Packet(
                                Action.READ_RESPONSE,
                                FunctionalDomain.STATUS,
                                8,
                                sequence=packet.sequence,
                                data={Attribute.ERROR: self.error},
                            )
                        )
                    else:
                        self._send_nack(0x07, packet.sequence)
                else:
                    self._send_nack(0x06, packet.sequence)
            elif packet.action == Action.WRITE:
                if packet.functional_domain == FunctionalDomain.CONTROL:
                    # Tracks whether attribute 3/4's out-of-range validation
                    # NACK'd the write, so the shared STATUS/7 COS below
                    # isn't sent for a write that was actually rejected.
                    write_accepted = True

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
                                    Attribute.FAN_STATUS: (
                                        1
                                        if self.fan_mode == 1 or self.fan_mode == 2
                                        else 0
                                    ),
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
                        # spec 2.3: 0 = Off, 40-90 = %RH Set Point, everything
                        # else Reserved. packet.py's humidity decoder already
                        # returns None for anything > 100; values 91-100
                        # decode fine but are still out of the spec's range.
                        new_dehumidification_setpoint = packet.data.get(
                            Attribute.DEHUMIDIFICATION_SETPOINT
                        )

                        if new_dehumidification_setpoint is None or not (
                            new_dehumidification_setpoint == 0
                            or 40 <= new_dehumidification_setpoint <= 90
                        ):
                            self._send_nack(0x10, packet.sequence)
                            write_accepted = False
                        else:
                            self.dehumidification_setpoint = (
                                new_dehumidification_setpoint
                            )
                            self.dehumidification_status = 2

                            self.packet_queue.put_nowait(
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
                    elif packet.attribute == 4:
                        # spec 2.4: 0 = Off, 1-7 = Auto Mode Setpoint, 10-50 =
                        # %RH Setpoint (Manual mode), everything else Reserved.
                        new_humidification_setpoint = packet.data.get(
                            Attribute.HUMIDIFICATION_SETPOINT
                        )

                        if new_humidification_setpoint is None or not (
                            new_humidification_setpoint == 0
                            or 1 <= new_humidification_setpoint <= 7
                            or 10 <= new_humidification_setpoint <= 50
                        ):
                            self._send_nack(0x10, packet.sequence)
                            write_accepted = False
                        else:
                            self.humidification_setpoint = new_humidification_setpoint
                            self.humidification_status = 2

                            self.packet_queue.put_nowait(
                                Packet(
                                    Action.COS,
                                    FunctionalDomain.CONTROL,
                                    4,
                                    sequence=self._get_sequence(),
                                    data={
                                        Attribute.HUMIDIFICATION_SETPOINT: self.humidification_setpoint
                                    },
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

                    if write_accepted and packet.attribute in [3, 4, 5]:
                        self.packet_queue.put_nowait(
                            Packet(
                                Action.COS,
                                FunctionalDomain.STATUS,
                                7,
                                sequence=self._get_sequence(),
                                data={
                                    Attribute.DEHUMIDIFICATION_STATUS: self.dehumidification_status,
                                    Attribute.HUMIDIFICATION_STATUS: self.humidification_status,
                                    Attribute.VENTILATION_STATUS: (
                                        2 if self.fresh_air_mode else 0
                                    ),
                                    Attribute.AIR_CLEANING_STATUS: (
                                        2 if self.air_cleaning_mode else 0
                                    ),
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
                                    Attribute.VENTILATION_STATUS: (
                                        2 if self.fresh_air_mode else 0
                                    ),
                                    Attribute.AIR_CLEANING_STATUS: (
                                        2 if self.air_cleaning_mode else 0
                                    ),
                                },
                            )
                        )
                    elif packet.attribute == 7:
                        # Thermostat/IAQ Available is read-only (spec K).
                        self._send_nack(0x11, packet.sequence)
                    elif packet.attribute not in (1, 3, 4, 5, 6):
                        self._send_nack(0x07, packet.sequence)

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
                    else:
                        self._send_nack(0x07, packet.sequence)
                elif packet.functional_domain == FunctionalDomain.SENSORS:
                    if packet.attribute == 4:
                        # spec 5.4: writes always send 0 for the status byte
                        # and it shouldn't overwrite the real status - but
                        # receiving a fresh value is exactly what clears a
                        # Timed Out condition, so treat it as No Error.
                        self.outdoor_sensor_status = 0
                        self.outdoor_sensor_value = packet.data.get(
                            Attribute.OUTDOOR_SENSOR
                        )

                        self.packet_queue.put_nowait(
                            Packet(
                                Action.COS,
                                FunctionalDomain.SENSORS,
                                4,
                                sequence=self._get_sequence(),
                                data={
                                    Attribute.OUTDOOR_SENSOR_STATUS: self.outdoor_sensor_status,
                                    Attribute.OUTDOOR_SENSOR: self.outdoor_sensor_value,
                                },
                            )
                        )
                    elif packet.attribute == 2:
                        # Controlling Sensor Values is read-only (spec K).
                        self._send_nack(0x11, packet.sequence)
                    else:
                        self._send_nack(0x07, packet.sequence)
                elif packet.functional_domain == FunctionalDomain.IDENTIFICATION:
                    if packet.attribute in (1, 2):
                        # Revision & Model / MAC Address are read-only (spec K).
                        self._send_nack(0x11, packet.sequence)
                    else:
                        self._send_nack(0x07, packet.sequence)
                elif packet.functional_domain == FunctionalDomain.STATUS:
                    if packet.attribute == 2:
                        asyncio.ensure_future(self._send_status())
                    elif packet.attribute in (6, 7, 8):
                        # Thermostat Status / IAQ Status / Thermostat Error
                        # are all read-only (spec K).
                        self._send_nack(0x11, packet.sequence)
                    else:
                        self._send_nack(0x07, packet.sequence)
                else:
                    self._send_nack(0x06, packet.sequence)

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
