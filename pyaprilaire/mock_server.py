"""Mock server for testing Aprilaire integration"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timedelta

from .const import (
    QUEUE_FREQUENCY,
    Action,
    AirCleaningStatus,
    Attribute,
    CoolingEquipmentStatus,
    DehumidificationStatus,
    FanMode,
    FanStatus,
    FunctionalDomain,
    HeatingEquipmentStatus,
    HoldType,
    HumidificationStatus,
    HvacMode,
    NackStatus,
    SensorStatus,
    TemperatureScale,
    ThermostatError,
    VentilationStatus,
)
from .packet import MAPPING, NackPacket, Packet

# The COS Subscriptions channels (spec 7.1), in wire order, taken straight
# from packet.py's schema for STATUS 0x01 so the mock's mask can never drift
# out of step with what the parser produces. Byte 21 is Reserved and appears
# here as None: it has no attribute name, is never subscribable, and only
# occupies its structurally-required place in the message.
# How long a temporary hold (spec 3.4) created by a setpoint write lasts.
# Real hardware ends one at the next scheduled transition; the mock has no
# schedule, so it picks a fixed duration and reports the resulting end time
# rather than leaving the hold end fields at a meaningless zero.
TEMPORARY_HOLD_HOURS = 2

COS_SUBSCRIPTION_ATTRIBUTES = [
    attribute_info[0]
    for attribute_info in MAPPING[Action.READ_RESPONSE][FunctionalDomain.STATUS][1]
]


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


def _describe_nack_status(status_code: int) -> str:
    """Name a NACK status code (spec H.5) for logging, falling back to the
    raw value for a code the spec doesn't define."""
    try:
        return f"{NackStatus(status_code).name} (0x{status_code:02X})"
    except ValueError:
        return f"0x{status_code:02X}"


class _AprilaireServerProtocol(asyncio.Protocol):
    def __init__(self):
        self.transport: asyncio.Transport = None

        self.mode = HvacMode.AUTO
        self.fan_mode = FanMode.AUTO
        self.cool_setpoint = 25
        self.heat_setpoint = 20
        self.hold = HoldType.DISABLED

        # When the current temporary hold ends; None whenever no hold is
        # active. See _start_temporary_hold / _scheduling_4_data.
        self.hold_end: datetime | None = None

        self.dehumidification_status = DehumidificationStatus.NOT_ACTIVE
        self.dehumidification_setpoint = 60
        self.humidification_status = HumidificationStatus.NOT_ACTIVE
        self.humidification_setpoint = 30
        self.fresh_air_mode = 0
        self.fresh_air_event = 0
        self.air_cleaning_mode = 0
        self.air_cleaning_event = 0

        # Written Outdoor Temperature Value (spec 5.4). Defaults to Timed
        # Out until the automation system writes a value.
        self.outdoor_sensor_status = SensorStatus.OPEN
        self.outdoor_sensor_value = 0

        self.error = ThermostatError.NO_ERROR

        # 8840 (spec 8.1) - the mock also serves dehumidification,
        # humidification, fresh air and thermostat-name, all of which the
        # spec marks "except 8810", so 8810 would be an inconsistent choice.
        self.model_number = 7

        self.name = "Mock"
        self.location = "02134"
        self.mac_address = [1, 2, 3, 4, 5, 6]

        # All COS subscription outputs are enabled by default (spec 7.1). A
        # WRITE to STATUS 0x01 (COS Subscriptions) overwrites this mask, and
        # a READ reports it back; see _configure_cos / _status_1_data /
        # _queue_cos.
        self.cos_mask = {
            attribute: 1
            for attribute in COS_SUBSCRIPTION_ATTRIBUTES
            if attribute is not None
        }

        self.packet_queue = asyncio.Queue()

        # Bytes received but not yet forming a complete frame; see
        # data_received.
        self.receive_buffer = bytearray()

        # Messages sent by the Thermostat use sequence numbers 128-255
        # (spec F, note 1). Starting at 127 makes the first _get_sequence()
        # call return 128.
        self.sequence = 127

    def _get_sequence(self) -> int:
        """Get and increment the current sequence number.

        Only used for messages the mock originates on its own (COS, or the
        sync burst) - read responses and NACKs instead echo the sequence of
        the request that triggered them, per spec F note 2, via _reply and
        _send_nack.
        """
        self.sequence = 128 + ((self.sequence + 1) % 128)

        return self.sequence

    def _cos_enabled(self, channel: Attribute) -> bool:
        return self.cos_mask.get(channel) == 1

    def _queue_cos(self, channel: Attribute | None, packet: Packet) -> None:
        """Queue a COS packet if its COS Subscriptions channel is enabled.

        channel=None means the message is always sent regardless of
        subscription state (e.g. Sync complete and Thermostat Error, which
        spec 7.2 calls out as always being part of a sync).
        """
        if channel is not None and not self._cos_enabled(channel):
            return

        self.packet_queue.put_nowait(packet)

    def _send_nack(self, status_code: NackStatus, sequence: int) -> None:
        """Send a NACK with the given status code (spec H.5), echoing the
        sequence number of the request it corresponds to."""
        _LOGGER.warning(
            "Sending NACK %s (0x%02X) for sequence %d",
            status_code.name,
            status_code,
            sequence,
        )
        self.packet_queue.put_nowait(NackPacket(status_code, sequence=sequence))

    def _reply(
        self, domain: FunctionalDomain, attribute: int, sequence: int, data: dict
    ) -> None:
        """Send a READ_RESPONSE, echoing the sequence number of the request
        that triggered it (spec F, note 2)."""
        self.packet_queue.put_nowait(
            Packet(
                Action.READ_RESPONSE, domain, attribute, sequence=sequence, data=data
            )
        )

    # -- Shared attribute payloads, kept in one place so every code path
    # (reads, COS, sync burst) reports the same state. --

    def _setup_1_data(self) -> dict:
        """Thermostat Installer Settings (spec 1.1).

        Only the fields packet.py maps are reported; the rest of the
        message is the structural padding Packet.serialize emits for an
        unmapped byte. Control Setup and Program Format are mapped but
        deliberately absent: this mock models neither, and inventing a value
        for them would be the kind of self-contradictory state the rest of
        these helpers exist to avoid.
        """
        return {
            # The setpoints below are Celsius - the protocol's temperature
            # encoding tops out at 63, which a Fahrenheit setpoint would
            # exceed - so reporting Fahrenheit here would contradict every
            # temperature this mock sends.
            Attribute.TEMPERATURE_SCALE: TemperatureScale.CELSIUS,
            # The mock's default mode is Auto, which needs auto changeover
            # enabled and a deadband between the two setpoints.
            Attribute.AUTO_CHANGEOVER: 1,
            Attribute.DEADBAND: 2,
            # No remote, outdoor or return air sensor: the outdoor
            # temperature this mock serves is the *written* value of spec
            # 5.4, which is what an automation system supplies precisely
            # when no outdoor sensor is installed.
            Attribute.WIRED_REMOTE_TEMPERATURE_SENSOR_INSTALLED: 0,
            Attribute.OUTDOOR_SENSOR_INSTALLED: 0,
            Attribute.RETURN_AIR_SENSOR_INSTALLED: 0,
            # Heat blast and progressive recovery aren't modeled, and
            # STATUS 0x06 accordingly always reports progressive recovery
            # as inactive.
            Attribute.HEAT_BLAST_AVAILABLE: 0,
            Attribute.PROGRESSIVE_RECOVERY_AVAILABLE: 0,
            Attribute.AWAY_AVAILABLE: 1,
        }

    def _scheduling_4_data(self) -> dict:
        """Schedule Hold (spec 3.4).

        The held fan mode and setpoints are the ones the hold is holding -
        i.e. the mock's current state - so they can't contradict what
        CONTROL 0x01 and CONTROL 0x03 report. With no hold active there is
        nothing being held: every field but the hold type is sent as NULL
        (spec section G).
        """
        if self.hold == HoldType.DISABLED:
            return {Attribute.HOLD: self.hold}

        data = {
            Attribute.HOLD: self.hold,
            Attribute.HOLD_FAN_MODE: self.fan_mode,
            Attribute.HOLD_HEAT_SETPOINT: self.heat_setpoint,
            Attribute.HOLD_COOL_SETPOINT: self.cool_setpoint,
            Attribute.HOLD_DEHUMIDIFICATION_SETPOINT: self.dehumidification_setpoint,
        }

        if self.hold_end is not None:
            data.update(
                {
                    Attribute.HOLD_END_MINUTE: self.hold_end.minute,
                    Attribute.HOLD_END_HOUR: self.hold_end.hour,
                    Attribute.HOLD_END_DATE: self.hold_end.day,
                    Attribute.HOLD_END_MONTH: self.hold_end.month,
                    # spec 3.4: the year field carries the offset from 2000.
                    Attribute.HOLD_END_YEAR: self.hold_end.year - 2000,
                }
            )

        return data

    def _start_temporary_hold(self) -> None:
        """Begin a temporary hold (spec 3.4), as a setpoint write does."""
        self.hold = HoldType.TEMPORARY
        self.hold_end = datetime.now() + timedelta(hours=TEMPORARY_HOLD_HOURS)

    def _control_1_data(self) -> dict:
        return {
            Attribute.MODE: self.mode,
            Attribute.FAN_MODE: self.fan_mode,
            Attribute.HEAT_SETPOINT: self.heat_setpoint,
            Attribute.COOL_SETPOINT: self.cool_setpoint,
        }

    def _control_7_data(self) -> dict:
        return {
            Attribute.THERMOSTAT_MODES: 6,
            Attribute.AIR_CLEANING_AVAILABLE: 1,
            Attribute.VENTILATION_AVAILABLE: 1,
            Attribute.DEHUMIDIFICATION_AVAILABLE: 1,
            Attribute.HUMIDIFICATION_AVAILABLE: 1,  # Auto (spec 2.7)
        }

    def _status_6_data(self) -> dict:
        return {
            Attribute.HEATING_EQUIPMENT_STATUS: {
                HvacMode.HEAT: HeatingEquipmentStatus.STAGE_1,
                HvacMode.EMERGENCY_HEAT: HeatingEquipmentStatus.AUX_HEAT_1,
            }.get(self.mode, HeatingEquipmentStatus.NOT_ACTIVE),
            Attribute.COOLING_EQUIPMENT_STATUS: {
                HvacMode.COOL: CoolingEquipmentStatus.STAGE_1,
                HvacMode.AUTO: CoolingEquipmentStatus.STAGE_1,
            }.get(self.mode, CoolingEquipmentStatus.NOT_ACTIVE),
            Attribute.PROGRESSIVE_RECOVERY: 0,
            Attribute.FAN_STATUS: FanStatus.ACTIVE
            if self.fan_mode in (FanMode.ON, FanMode.AUTO)
            else FanStatus.NOT_ACTIVE,
        }

    def _status_7_data(self) -> dict:
        return {
            Attribute.DEHUMIDIFICATION_STATUS: self.dehumidification_status,
            Attribute.HUMIDIFICATION_STATUS: self.humidification_status,
            Attribute.VENTILATION_STATUS: VentilationStatus.ACTIVE
            if self.fresh_air_mode
            else VentilationStatus.NOT_ACTIVE,
            Attribute.AIR_CLEANING_STATUS: AirCleaningStatus.ACTIVE
            if self.air_cleaning_mode
            else AirCleaningStatus.NOT_ACTIVE,
        }

    def _sensors_2_data(self) -> dict:
        return {
            Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS: SensorStatus.NO_ERROR,
            Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_VALUE: 25,
            Attribute.OUTDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS: SensorStatus.NO_ERROR,
            Attribute.OUTDOOR_TEMPERATURE_CONTROLLING_SENSOR_VALUE: 25,
            Attribute.INDOOR_HUMIDITY_CONTROLLING_SENSOR_STATUS: SensorStatus.NO_ERROR,
            Attribute.INDOOR_HUMIDITY_CONTROLLING_SENSOR_VALUE: 50,
            Attribute.OUTDOOR_HUMIDITY_CONTROLLING_SENSOR_STATUS: SensorStatus.NO_ERROR,
            Attribute.OUTDOOR_HUMIDITY_CONTROLLING_SENSOR_VALUE: 40,
        }

    def _identification_1_data(self) -> dict:
        return {
            Attribute.HARDWARE_REVISION: 66,
            Attribute.FIRMWARE_MAJOR_REVISION: 10,
            Attribute.FIRMWARE_MINOR_REVISION: 2,
            Attribute.PROTOCOL_MAJOR_REVISION: 15,
            Attribute.MODEL_NUMBER: self.model_number,
            Attribute.GAINSPAN_FIRMWARE_MAJOR_REVISION: 14,
            Attribute.GAINSPAN_FIRMWARE_MINOR_REVISION: 3,
        }

    async def _send_sync_burst(self) -> None:
        """Send every COS-subscribed message, then the Thermostat Error
        status, then finally the Sync-complete COS (spec 7.2): "used to
        prompt the Thermostat to send all COS subscribed messages, the
        Thermostat Error Status message, and COS Sync complete message."
        """

        self._queue_cos(
            Attribute.COS_INSTALLER_THERMOSTAT_SETTINGS,
            Packet(
                Action.COS,
                FunctionalDomain.SETUP,
                1,
                sequence=self._get_sequence(),
                data=self._setup_1_data(),
            ),
        )
        self._queue_cos(
            Attribute.COS_THERMOSTAT_SETPOINT_AND_MODE_SETTINGS,
            Packet(
                Action.COS,
                FunctionalDomain.CONTROL,
                1,
                sequence=self._get_sequence(),
                data=self._control_1_data(),
            ),
        )
        self._queue_cos(
            Attribute.COS_DEHUMIDIFICATION_SETPOINT,
            Packet(
                Action.COS,
                FunctionalDomain.CONTROL,
                3,
                sequence=self._get_sequence(),
                data={
                    Attribute.DEHUMIDIFICATION_SETPOINT: self.dehumidification_setpoint
                },
            ),
        )
        self._queue_cos(
            Attribute.COS_HUMIDIFICATION_SETPOINT,
            Packet(
                Action.COS,
                FunctionalDomain.CONTROL,
                4,
                sequence=self._get_sequence(),
                data={Attribute.HUMIDIFICATION_SETPOINT: self.humidification_setpoint},
            ),
        )
        self._queue_cos(
            Attribute.COS_FRESH_AIR_SETTING,
            Packet(
                Action.COS,
                FunctionalDomain.CONTROL,
                5,
                sequence=self._get_sequence(),
                data={
                    Attribute.FRESH_AIR_MODE: self.fresh_air_mode,
                    Attribute.FRESH_AIR_EVENT: self.fresh_air_event,
                },
            ),
        )
        self._queue_cos(
            Attribute.COS_AIR_CLEANING_SETTINGS,
            Packet(
                Action.COS,
                FunctionalDomain.CONTROL,
                6,
                sequence=self._get_sequence(),
                data={
                    Attribute.AIR_CLEANING_MODE: self.air_cleaning_mode,
                    Attribute.AIR_CLEANING_EVENT: self.air_cleaning_event,
                },
            ),
        )
        self._queue_cos(
            Attribute.COS_THERMOSTAT_IAQ_AVAILABLE,
            Packet(
                Action.COS,
                FunctionalDomain.CONTROL,
                7,
                sequence=self._get_sequence(),
                data=self._control_7_data(),
            ),
        )
        self._queue_cos(
            Attribute.COS_SCHEDULE_HOLD,
            Packet(
                Action.COS,
                FunctionalDomain.SCHEDULING,
                4,
                sequence=self._get_sequence(),
                data=self._scheduling_4_data(),
            ),
        )
        self._queue_cos(
            Attribute.COS_THERMOSTAT_LOCATION_AND_NAME,
            Packet(
                Action.COS,
                FunctionalDomain.IDENTIFICATION,
                4,
                sequence=self._get_sequence(),
                data={Attribute.LOCATION: self.location, Attribute.NAME: self.name},
            ),
        )
        self._queue_cos(
            Attribute.COS_CONTROLLING_SENSOR_VALUES,
            Packet(
                Action.COS,
                FunctionalDomain.SENSORS,
                2,
                sequence=self._get_sequence(),
                data=self._sensors_2_data(),
            ),
        )
        self._queue_cos(
            Attribute.COS_THERMOSTAT_STATUS,
            Packet(
                Action.COS,
                FunctionalDomain.STATUS,
                6,
                sequence=self._get_sequence(),
                data=self._status_6_data(),
            ),
        )
        self._queue_cos(
            Attribute.COS_IAQ_STATUS,
            Packet(
                Action.COS,
                FunctionalDomain.STATUS,
                7,
                sequence=self._get_sequence(),
                data=self._status_7_data(),
            ),
        )
        self._queue_cos(
            Attribute.COS_MODEL_AND_REVISION,
            Packet(
                Action.COS,
                FunctionalDomain.IDENTIFICATION,
                1,
                sequence=self._get_sequence(),
                data=self._identification_1_data(),
            ),
        )

        # Always sent as part of a sync, regardless of subscription state.
        self._queue_cos(
            None,
            Packet(
                Action.COS,
                FunctionalDomain.STATUS,
                8,
                sequence=self._get_sequence(),
                data={Attribute.ERROR: self.error},
            ),
        )
        self._queue_cos(
            None,
            Packet(
                Action.COS,
                FunctionalDomain.STATUS,
                2,
                sequence=self._get_sequence(),
                data={Attribute.SYNCED: 1},
            ),
        )

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

        # A fresh connection must not inherit a partial frame left over
        # from whatever connection preceded it.
        self.receive_buffer = bytearray()

        asyncio.ensure_future(self._queue_loop())

    def _configure_cos(self, packet: Packet) -> None:
        """Handle a WRITE to STATUS 0x01 (COS Subscriptions, spec 7.1).

        Every channel the client omits keeps its current value: spec section
        G defines a NULL (0) byte in a write as "leave this field
        unmodified", and Packet.parse reports those bytes as a 0 rather than
        dropping them, so an explicit 0 from the client (disable this
        channel) is indistinguishable from an omission at this layer. The
        client always writes the complete 29-byte mask, which is the case
        that matters here.
        """
        self.cos_mask.update(
            {
                attribute: value
                for attribute, value in packet.data.items()
                if attribute in self.cos_mask
            }
        )

        _LOGGER.info("Configuring COS subscriptions: %s", self._status_1_data())

    def _status_1_data(self) -> dict:
        """The current COS Subscriptions mask (spec 7.1), as reported by a
        read of STATUS 0x01.

        client.py's configure_cos() reads this before deciding whether a
        write is warranted at all, so an unanswered read here costs the
        client its read timeout on every connect and then makes it write the
        mask unconditionally.
        """
        return dict(self.cos_mask)

    def _prescan_raw_frames(self, data: bytes) -> None:
        """Walk the raw frame stream the same way Packet.parse() does, to
        catch frames it silently drops before they ever become a Packet the
        rest of this class can see: an unrecognized action (NACK 0x05), an
        unrecognized or unsupported functional domain (0x06), or an
        attribute this action/domain doesn't define (0x07) - spec H.5: "A
        NAck is sent in response to any unhandled, corrupt, or
        un-parse-able action received with a suitable status code."

        NOTE: this necessarily duplicates a small amount of Packet.parse()'s
        header-walking logic (revision/sequence/count/action/domain/
        attribute + CRC). It intentionally stays out of packet.py, which is
        outside this change's scope; see the PR description for the
        packet.py-side fix this should eventually be replaced by (yielding
        an "unparseable" marker instead of silently dropping the frame).
        """
        index = 0

        while index + 7 <= len(data):
            sequence = data[index + 1]
            count = (data[index + 2] << 8) | data[index + 3]
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
                self._send_nack(NackStatus.UNKNOWN_ACTION, sequence)
                index = next_index
                continue

            if action == Action.NACK:
                index = next_index
                continue

            try:
                domain = FunctionalDomain(domain_byte)
            except ValueError:
                self._send_nack(NackStatus.UNKNOWN_FUNCTIONAL_DOMAIN, sequence)
                index = next_index
                continue

            if (
                action == Action.READ_REQUEST
                and domain == FunctionalDomain.SETUP
                and attribute == 8
            ):
                # Reset (spec 1.8) is write-only and has no MAPPING schema.
                self._send_nack(NackStatus.ATTRIBUTE_NOT_READABLE, sequence)
            elif action not in MAPPING or domain not in MAPPING[action]:
                self._send_nack(NackStatus.UNKNOWN_FUNCTIONAL_DOMAIN, sequence)
            elif attribute not in MAPPING[action][domain]:
                self._send_nack(NackStatus.UNKNOWN_ATTRIBUTE, sequence)

            index = next_index

    def _handle_read_request(self, packet: Packet) -> None:
        domain = packet.functional_domain
        attribute = packet.attribute
        sequence = packet.sequence

        if domain == FunctionalDomain.SETUP:
            if attribute == 1:
                self._reply(FunctionalDomain.SETUP, 1, sequence, self._setup_1_data())
            else:
                self._send_nack(NackStatus.UNKNOWN_ATTRIBUTE, sequence)
        elif domain == FunctionalDomain.CONTROL:
            if attribute == 1:
                self._reply(
                    FunctionalDomain.CONTROL, 1, sequence, self._control_1_data()
                )
            elif attribute == 3:
                self._reply(
                    FunctionalDomain.CONTROL,
                    3,
                    sequence,
                    {
                        Attribute.DEHUMIDIFICATION_SETPOINT: self.dehumidification_setpoint
                    },
                )
            elif attribute == 4:
                self._reply(
                    FunctionalDomain.CONTROL,
                    4,
                    sequence,
                    {Attribute.HUMIDIFICATION_SETPOINT: self.humidification_setpoint},
                )
            elif attribute == 5:
                self._reply(
                    FunctionalDomain.CONTROL,
                    5,
                    sequence,
                    {
                        Attribute.FRESH_AIR_MODE: self.fresh_air_mode,
                        Attribute.FRESH_AIR_EVENT: self.fresh_air_event,
                    },
                )
            elif attribute == 6:
                self._reply(
                    FunctionalDomain.CONTROL,
                    6,
                    sequence,
                    {
                        Attribute.AIR_CLEANING_MODE: self.air_cleaning_mode,
                        Attribute.AIR_CLEANING_EVENT: self.air_cleaning_event,
                    },
                )
            elif attribute == 7:
                self._reply(
                    FunctionalDomain.CONTROL, 7, sequence, self._control_7_data()
                )
            else:
                self._send_nack(NackStatus.UNKNOWN_ATTRIBUTE, sequence)
        elif domain == FunctionalDomain.SENSORS:
            if attribute == 2:
                self._reply(
                    FunctionalDomain.SENSORS, 2, sequence, self._sensors_2_data()
                )
            else:
                self._send_nack(NackStatus.UNKNOWN_ATTRIBUTE, sequence)
        elif domain == FunctionalDomain.SCHEDULING:
            if attribute == 4:
                self._reply(
                    FunctionalDomain.SCHEDULING,
                    4,
                    sequence,
                    self._scheduling_4_data(),
                )
            else:
                self._send_nack(NackStatus.UNKNOWN_ATTRIBUTE, sequence)
        elif domain == FunctionalDomain.STATUS:
            if attribute == 1:
                self._reply(FunctionalDomain.STATUS, 1, sequence, self._status_1_data())
            elif attribute == 2:
                # Sync is write-only (spec 7.2).
                self._send_nack(NackStatus.ATTRIBUTE_NOT_READABLE, sequence)
            elif attribute == 6:
                self._reply(FunctionalDomain.STATUS, 6, sequence, self._status_6_data())
            elif attribute == 7:
                self._reply(FunctionalDomain.STATUS, 7, sequence, self._status_7_data())
            elif attribute == 8:
                self._reply(
                    FunctionalDomain.STATUS, 8, sequence, {Attribute.ERROR: self.error}
                )
            else:
                self._send_nack(NackStatus.UNKNOWN_ATTRIBUTE, sequence)
        elif domain == FunctionalDomain.IDENTIFICATION:
            if attribute == 1:
                self._reply(
                    FunctionalDomain.IDENTIFICATION,
                    1,
                    sequence,
                    self._identification_1_data(),
                )
            elif attribute == 2:
                self._reply(
                    FunctionalDomain.IDENTIFICATION,
                    2,
                    sequence,
                    {Attribute.MAC_ADDRESS: self.mac_address},
                )
            elif attribute == 4 or attribute == 5:
                # Echo whichever attribute was requested - the client
                # correlates responses by (domain, attribute), so replying
                # to a 0x05 request with 0x04 (as this mock used to)
                # resolves against the wrong key.
                self._reply(
                    FunctionalDomain.IDENTIFICATION,
                    attribute,
                    sequence,
                    {Attribute.LOCATION: self.location, Attribute.NAME: self.name},
                )
            else:
                self._send_nack(NackStatus.UNKNOWN_ATTRIBUTE, sequence)
        else:
            self._send_nack(NackStatus.UNKNOWN_FUNCTIONAL_DOMAIN, sequence)

    def _write_control_1(self, packet: Packet) -> None:
        data = packet.data

        if Attribute.MODE in data:
            self.mode = data[Attribute.MODE]
            self.hold = HoldType.DISABLED
            self.hold_end = None

        # When the current temporary hold ends; None whenever no hold is
        # active. See _start_temporary_hold / _scheduling_4_data.
        self.hold_end: datetime | None = None

        if Attribute.FAN_MODE in data:
            self.fan_mode = data[Attribute.FAN_MODE]

        if Attribute.HEAT_SETPOINT in data:
            self.heat_setpoint = data[Attribute.HEAT_SETPOINT]
            self._start_temporary_hold()

        if Attribute.COOL_SETPOINT in data:
            self.cool_setpoint = data[Attribute.COOL_SETPOINT]
            self._start_temporary_hold()

        self._queue_cos(
            Attribute.COS_THERMOSTAT_SETPOINT_AND_MODE_SETTINGS,
            Packet(
                Action.COS,
                FunctionalDomain.CONTROL,
                1,
                sequence=self._get_sequence(),
                data=self._control_1_data(),
            ),
        )
        self._queue_cos(
            Attribute.COS_THERMOSTAT_STATUS,
            Packet(
                Action.COS,
                FunctionalDomain.STATUS,
                6,
                sequence=self._get_sequence(),
                data=self._status_6_data(),
            ),
        )
        self._queue_cos(
            Attribute.COS_SCHEDULE_HOLD,
            Packet(
                Action.COS,
                FunctionalDomain.SCHEDULING,
                4,
                sequence=self._get_sequence(),
                data=self._scheduling_4_data(),
            ),
        )

    def _write_dehumidification_setpoint(self, packet: Packet) -> None:
        # spec 2.3: 0 = Off, 40-90 = %RH Set Point, everything else Reserved.
        value = packet.data.get(Attribute.DEHUMIDIFICATION_SETPOINT)

        if value is None or not (value == 0 or 40 <= value <= 90):
            self._send_nack(NackStatus.VALUE_OUT_OF_RANGE, packet.sequence)
            return

        self.dehumidification_setpoint = value
        self.dehumidification_status = DehumidificationStatus.WHOLE_HOME_ACTIVE

        self._queue_cos(
            Attribute.COS_DEHUMIDIFICATION_SETPOINT,
            Packet(
                Action.COS,
                FunctionalDomain.CONTROL,
                3,
                sequence=self._get_sequence(),
                data={
                    Attribute.DEHUMIDIFICATION_SETPOINT: self.dehumidification_setpoint
                },
            ),
        )
        self._queue_cos(
            Attribute.COS_IAQ_STATUS,
            Packet(
                Action.COS,
                FunctionalDomain.STATUS,
                7,
                sequence=self._get_sequence(),
                data=self._status_7_data(),
            ),
        )

    def _write_humidification_setpoint(self, packet: Packet) -> None:
        # spec 2.4: 0 = Off, 1-7 = Auto Mode Setpoint, 10-50 = %RH Setpoint
        # (Manual mode), everything else Reserved.
        value = packet.data.get(Attribute.HUMIDIFICATION_SETPOINT)

        if value is None or not (value == 0 or 1 <= value <= 7 or 10 <= value <= 50):
            self._send_nack(NackStatus.VALUE_OUT_OF_RANGE, packet.sequence)
            return

        self.humidification_setpoint = value
        self.humidification_status = HumidificationStatus.ACTIVE

        self._queue_cos(
            Attribute.COS_HUMIDIFICATION_SETPOINT,
            Packet(
                Action.COS,
                FunctionalDomain.CONTROL,
                4,
                sequence=self._get_sequence(),
                data={Attribute.HUMIDIFICATION_SETPOINT: self.humidification_setpoint},
            ),
        )
        self._queue_cos(
            Attribute.COS_IAQ_STATUS,
            Packet(
                Action.COS,
                FunctionalDomain.STATUS,
                7,
                sequence=self._get_sequence(),
                data=self._status_7_data(),
            ),
        )

    def _write_fresh_air(self, packet: Packet) -> None:
        self.fresh_air_mode = packet.data.get(
            Attribute.FRESH_AIR_MODE, self.fresh_air_mode
        )
        self.fresh_air_event = packet.data.get(
            Attribute.FRESH_AIR_EVENT, self.fresh_air_event
        )

        self._queue_cos(
            Attribute.COS_FRESH_AIR_SETTING,
            Packet(
                Action.COS,
                FunctionalDomain.CONTROL,
                5,
                sequence=self._get_sequence(),
                data={
                    Attribute.FRESH_AIR_MODE: self.fresh_air_mode,
                    Attribute.FRESH_AIR_EVENT: self.fresh_air_event,
                },
            ),
        )
        self._queue_cos(
            Attribute.COS_IAQ_STATUS,
            Packet(
                Action.COS,
                FunctionalDomain.STATUS,
                7,
                sequence=self._get_sequence(),
                data=self._status_7_data(),
            ),
        )

    def _write_air_cleaning(self, packet: Packet) -> None:
        self.air_cleaning_mode = packet.data.get(
            Attribute.AIR_CLEANING_MODE, self.air_cleaning_mode
        )
        self.air_cleaning_event = packet.data.get(
            Attribute.AIR_CLEANING_EVENT, self.air_cleaning_event
        )

        self._queue_cos(
            Attribute.COS_AIR_CLEANING_SETTINGS,
            Packet(
                Action.COS,
                FunctionalDomain.CONTROL,
                6,
                sequence=self._get_sequence(),
                data={
                    Attribute.AIR_CLEANING_MODE: self.air_cleaning_mode,
                    Attribute.AIR_CLEANING_EVENT: self.air_cleaning_event,
                },
            ),
        )
        self._queue_cos(
            Attribute.COS_IAQ_STATUS,
            Packet(
                Action.COS,
                FunctionalDomain.STATUS,
                7,
                sequence=self._get_sequence(),
                data=self._status_7_data(),
            ),
        )

    def _write_hold(self, packet: Packet) -> None:
        if Attribute.HOLD in packet.data:
            self.hold = packet.data[Attribute.HOLD]

            if self.hold == HoldType.DISABLED:
                self.hold_end = None
            elif self.hold == HoldType.TEMPORARY and self.hold_end is None:
                self.hold_end = datetime.now() + timedelta(hours=TEMPORARY_HOLD_HOURS)

        self._queue_cos(
            Attribute.COS_SCHEDULE_HOLD,
            Packet(
                Action.COS,
                FunctionalDomain.SCHEDULING,
                4,
                sequence=self._get_sequence(),
                data=self._scheduling_4_data(),
            ),
        )

    def _write_outdoor_sensor(self, packet: Packet) -> None:
        # spec 5.4: writes always send 0 for the status byte and it should
        # not overwrite the real status - but receiving a fresh value is
        # exactly what clears a Timed Out condition, so treat it as No Error.
        self.outdoor_sensor_status = SensorStatus.NO_ERROR
        self.outdoor_sensor_value = packet.data.get(Attribute.OUTDOOR_SENSOR)

        self._queue_cos(
            None,
            Packet(
                Action.COS,
                FunctionalDomain.SENSORS,
                4,
                sequence=self._get_sequence(),
                data={
                    Attribute.OUTDOOR_SENSOR_STATUS: self.outdoor_sensor_status,
                    Attribute.OUTDOOR_SENSOR: self.outdoor_sensor_value,
                },
            ),
        )

    def _write_sync(self, packet: Packet) -> None:
        # spec 7.2: 0 and 2-255 are Reserved; only 1 starts a sync.
        if packet.data.get(Attribute.SYNCED) != 1:
            self._send_nack(NackStatus.VALUE_OUT_OF_RANGE, packet.sequence)
            return

        asyncio.ensure_future(self._send_sync_burst())

    def _handle_write(self, packet: Packet) -> None:
        domain = packet.functional_domain
        attribute = packet.attribute
        sequence = packet.sequence

        if domain == FunctionalDomain.SETUP:
            # Installer settings are spec-legal writes, but nothing in
            # client.py writes them and this mock doesn't model changing
            # them, so they're refused the same way as any other attribute
            # it can't act on.
            self._send_nack(NackStatus.UNKNOWN_ATTRIBUTE, sequence)
        elif domain == FunctionalDomain.CONTROL:
            if attribute == 1:
                self._write_control_1(packet)
            elif attribute == 3:
                self._write_dehumidification_setpoint(packet)
            elif attribute == 4:
                self._write_humidification_setpoint(packet)
            elif attribute == 5:
                self._write_fresh_air(packet)
            elif attribute == 6:
                self._write_air_cleaning(packet)
            elif attribute == 7:
                # Thermostat/IAQ Available is read-only (spec K).
                self._send_nack(NackStatus.ATTRIBUTE_READ_ONLY, sequence)
            else:
                self._send_nack(NackStatus.UNKNOWN_ATTRIBUTE, sequence)
        elif domain == FunctionalDomain.SCHEDULING:
            if attribute == 4:
                self._write_hold(packet)
            else:
                self._send_nack(NackStatus.UNKNOWN_ATTRIBUTE, sequence)
        elif domain == FunctionalDomain.SENSORS:
            if attribute == 4:
                self._write_outdoor_sensor(packet)
            elif attribute == 2:
                # Controlling Sensor Values is read-only (spec K).
                self._send_nack(NackStatus.ATTRIBUTE_READ_ONLY, sequence)
            else:
                self._send_nack(NackStatus.UNKNOWN_ATTRIBUTE, sequence)
        elif domain == FunctionalDomain.STATUS:
            if attribute == 1:
                self._configure_cos(packet)
            elif attribute == 2:
                self._write_sync(packet)
            elif attribute in (6, 7, 8):
                # Thermostat Status / IAQ Status / Thermostat Error are all
                # read-only (spec K).
                self._send_nack(NackStatus.ATTRIBUTE_READ_ONLY, sequence)
            else:
                self._send_nack(NackStatus.UNKNOWN_ATTRIBUTE, sequence)
        elif domain == FunctionalDomain.IDENTIFICATION:
            if attribute in (1, 2):
                # Revision & Model / MAC Address are read-only (spec K).
                self._send_nack(NackStatus.ATTRIBUTE_READ_ONLY, sequence)
            else:
                self._send_nack(NackStatus.UNKNOWN_ATTRIBUTE, sequence)
        else:
            self._send_nack(NackStatus.UNKNOWN_FUNCTIONAL_DOMAIN, sequence)

    def data_received(self, data: bytes) -> None:
        _LOGGER.info("Received data: %s", data.hex(" ", 1))

        # A single TCP read carries no guarantee that frame boundaries line
        # up with read boundaries - it can hold several frames, or only part
        # of one. Buffer what arrives and only act on the complete frames
        # that leaves, the same way _AprilaireClientProtocol does on the
        # other end of the socket; a mock that instead dropped a split frame
        # would make the client look broken when it isn't.
        self.receive_buffer.extend(data)

        parseable_length = Packet.get_parseable_length(self.receive_buffer)

        if parseable_length == 0:
            return

        parseable_data = bytes(self.receive_buffer[:parseable_length])
        del self.receive_buffer[:parseable_length]

        self._prescan_raw_frames(parseable_data)

        for packet in Packet.parse(parseable_data):
            if packet.action == Action.READ_REQUEST:
                self._handle_read_request(packet)
            elif packet.action == Action.WRITE:
                self._handle_write(packet)
            elif packet.action == Action.NACK:
                _LOGGER.warning(
                    "Received NACK from client, status code %s",
                    _describe_nack_status(packet.status_code),
                )
            else:
                _LOGGER.warning(
                    "Ignoring unexpected %s packet from client", packet.action
                )

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
