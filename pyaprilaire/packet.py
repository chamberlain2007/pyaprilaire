"""Functions for handling response data from the thermostat"""

import math
from collections.abc import Iterator
from enum import Enum
from typing import Any

from crc import Calculator, Configuration

from .const import Action, Attribute, FunctionalDomain

crc_calculator = Calculator(
    Configuration(
        width=8,
        polynomial=0x31,
        init_value=0,
        final_xor_value=0,
        reverse_input=False,
        reverse_output=False,
    )
)


class ValueType(Enum):
    """Parsable value types from data"""

    INTEGER = 1
    INTEGER_REQUIRED = 2
    TEMPERATURE = 3
    TEMPERATURE_REQUIRED = 4
    HUMIDITY = 5
    MAC_ADDRESS = 6
    TEXT = 7


MAPPING = {
    Action.READ_RESPONSE: {
        FunctionalDomain.SETUP: {
            1: [
                (None, None),  # 0 Connected To
                (None, None),  # 1 Equipment Type
                (Attribute.TEMPERATURE_SCALE, ValueType.INTEGER),
                (None, None),  # 3 Reversing Valve
                (Attribute.CONTROL_SETUP, ValueType.INTEGER),
                (None, None),  # 5 Cooling Stages / Compressor Stages
                (None, None),  # 6 Heating Stages / Aux Heat Stages
                (None, None),  # 7 Fan Control in Heating / Aux Equipment Type
                (None, None),  # 8 Extended Fan - Heat
                (None, None),  # 9 Extended Fan - Cool
                (None, None),  # 10 Internal Temp Sensor Offset
                (None, None),  # 11 Internal RH Sensor Offset
                (Attribute.AUTO_CHANGEOVER, ValueType.INTEGER),
                (Attribute.DEADBAND, ValueType.INTEGER),
                (
                    Attribute.WIRED_REMOTE_TEMPERATURE_SENSOR_INSTALLED,
                    ValueType.INTEGER,
                ),
                (Attribute.OUTDOOR_SENSOR_INSTALLED, ValueType.INTEGER),
                (None, None),  # 16 Reserved
                (Attribute.RETURN_AIR_SENSOR_INSTALLED, ValueType.INTEGER),
                (None, None),  # 18 Compressor Min Off Time
                (None, None),  # 19 Heating Min Off Time
                (None, None),  # 20 Equipment Min On Time
                (None, None),  # 21 Auto Changeover Time
                (None, None),  # 22 First Stage Differential
                (None, None),  # 23 Second Stage Differential
                (None, None),  # 24 Third Stage Differential
                (None, None),  # 25 Fourth Stage Differential
                (Attribute.AWAY_AVAILABLE, ValueType.INTEGER),
                (Attribute.HEAT_BLAST_AVAILABLE, ValueType.INTEGER),
                (None, None),  # 28 Heat Blast Offset
                (None, None),  # 29 Stage Rate
                (Attribute.PROGRESSIVE_RECOVERY_AVAILABLE, ValueType.INTEGER),
                (None, None),  # 31 Low Balance Point
                (None, None),  # 32 High Balance Point
                (Attribute.PROGRAM_FORMAT, ValueType.INTEGER),
                (None, None),  # 34 HVAC Service Reminder
                (None, None),  # 35 Reserved
                (None, None),  # 36 Turn Off WiFi Radio
                (None, None),  # 37 Reserved
                (None, None),  # 38 Support Module Controlling Temp Sensors
                (None, None),  # 39 Support Module Controlling RH Sensors
                (None, None),  # 40 Display Monitor Support Module Sensors
                (None, None),  # 41 8476 Change Air Filter Reminder
                (None, None),  # 42 8476 Change Water Panel Reminder
                (None, None),  # 43 8476 Humidifier Type
            ]
        },
        FunctionalDomain.CONTROL: {
            1: [
                (Attribute.MODE, ValueType.INTEGER_REQUIRED),
                (Attribute.FAN_MODE, ValueType.INTEGER_REQUIRED),
                (Attribute.HEAT_SETPOINT, ValueType.TEMPERATURE_REQUIRED),
                (Attribute.COOL_SETPOINT, ValueType.TEMPERATURE_REQUIRED),
            ],
            3: [
                (Attribute.DEHUMIDIFICATION_SETPOINT, ValueType.HUMIDITY),
            ],
            4: [
                (Attribute.HUMIDIFICATION_SETPOINT, ValueType.HUMIDITY),
            ],
            5: [
                (Attribute.FRESH_AIR_MODE, ValueType.INTEGER),
                (Attribute.FRESH_AIR_EVENT, ValueType.INTEGER),
            ],
            6: [
                (Attribute.AIR_CLEANING_MODE, ValueType.INTEGER),
                (Attribute.AIR_CLEANING_EVENT, ValueType.INTEGER),
            ],
            7: [
                (Attribute.THERMOSTAT_MODES, ValueType.INTEGER),
                (Attribute.AIR_CLEANING_AVAILABLE, ValueType.INTEGER),
                (Attribute.VENTILATION_AVAILABLE, ValueType.INTEGER),
                (Attribute.DEHUMIDIFICATION_AVAILABLE, ValueType.INTEGER),
                (Attribute.HUMIDIFICATION_AVAILABLE, ValueType.INTEGER),
            ],
        },
        FunctionalDomain.SCHEDULING: {
            4: [
                (Attribute.HOLD, ValueType.INTEGER),
                (Attribute.HOLD_FAN_MODE, ValueType.INTEGER),
                (Attribute.HOLD_HEAT_SETPOINT, ValueType.TEMPERATURE),
                (Attribute.HOLD_COOL_SETPOINT, ValueType.TEMPERATURE),
                (Attribute.HOLD_DEHUMIDIFICATION_SETPOINT, ValueType.HUMIDITY),
                (Attribute.HOLD_END_MINUTE, ValueType.INTEGER),
                (Attribute.HOLD_END_HOUR, ValueType.INTEGER),
                (Attribute.HOLD_END_DATE, ValueType.INTEGER),
                (Attribute.HOLD_END_MONTH, ValueType.INTEGER),
                (Attribute.HOLD_END_YEAR, ValueType.INTEGER),  # spec: add 2000
            ],
        },
        FunctionalDomain.SENSORS: {
            1: [
                (Attribute.BUILT_IN_TEMPERATURE_SENSOR_STATUS, ValueType.INTEGER),
                (Attribute.BUILT_IN_TEMPERATURE_SENSOR_VALUE, ValueType.TEMPERATURE),
                (Attribute.WIRED_REMOTE_TEMPERATURE_SENSOR_STATUS, ValueType.INTEGER),
                (
                    Attribute.WIRED_REMOTE_TEMPERATURE_SENSOR_VALUE,
                    ValueType.TEMPERATURE,
                ),
                (Attribute.WIRED_OUTDOOR_TEMPERATURE_SENSOR_STATUS, ValueType.INTEGER),
                (
                    Attribute.WIRED_OUTDOOR_TEMPERATURE_SENSOR_VALUE,
                    ValueType.TEMPERATURE,
                ),
                (Attribute.BUILT_IN_HUMIDITY_SENSOR_STATUS, ValueType.INTEGER),
                (Attribute.BUILT_IN_HUMIDITY_SENSOR_VALUE, ValueType.HUMIDITY),
                (Attribute.RAT_SENSOR_STATUS, ValueType.INTEGER),
                (Attribute.RAT_SENSOR_VALUE, ValueType.TEMPERATURE),
                (Attribute.LAT_SENSOR_STATUS, ValueType.INTEGER),
                (Attribute.LAT_SENSOR_VALUE, ValueType.TEMPERATURE),
                (
                    Attribute.WIRELESS_OUTDOOR_TEMPERATURE_SENSOR_STATUS,
                    ValueType.INTEGER,
                ),
                (
                    Attribute.WIRELESS_OUTDOOR_TEMPERATURE_SENSOR_VALUE,
                    ValueType.TEMPERATURE,
                ),
                (Attribute.WIRELESS_OUTDOOR_HUMIDITY_SENSOR_STATUS, ValueType.INTEGER),
                (Attribute.WIRELESS_OUTDOOR_HUMIDITY_SENSOR_VALUE, ValueType.HUMIDITY),
            ],
            2: [
                (
                    Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS,
                    ValueType.INTEGER,
                ),
                (
                    Attribute.INDOOR_TEMPERATURE_CONTROLLING_SENSOR_VALUE,
                    ValueType.TEMPERATURE,
                ),
                (
                    Attribute.OUTDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS,
                    ValueType.INTEGER,
                ),
                (
                    Attribute.OUTDOOR_TEMPERATURE_CONTROLLING_SENSOR_VALUE,
                    ValueType.TEMPERATURE,
                ),
                (
                    Attribute.INDOOR_HUMIDITY_CONTROLLING_SENSOR_STATUS,
                    ValueType.INTEGER,
                ),
                (
                    Attribute.INDOOR_HUMIDITY_CONTROLLING_SENSOR_VALUE,
                    ValueType.HUMIDITY,
                ),
                (
                    Attribute.OUTDOOR_HUMIDITY_CONTROLLING_SENSOR_STATUS,
                    ValueType.INTEGER,
                ),
                (
                    Attribute.OUTDOOR_HUMIDITY_CONTROLLING_SENSOR_VALUE,
                    ValueType.HUMIDITY,
                ),
            ],
            4: [
                (Attribute.OUTDOOR_SENSOR_STATUS, ValueType.INTEGER),
                (Attribute.OUTDOOR_SENSOR, ValueType.TEMPERATURE),
            ],
        },
        FunctionalDomain.STATUS: {
            1: [
                (Attribute.COS_INSTALLER_THERMOSTAT_SETTINGS, ValueType.INTEGER),
                (Attribute.COS_CONTRACTOR_INFORMATION, ValueType.INTEGER),
                (Attribute.COS_AIR_CLEANING_INSTALLER_SETTINGS, ValueType.INTEGER),
                (Attribute.COS_HUMIDITY_CONTROL_INSTALLER_SETTINGS, ValueType.INTEGER),
                (Attribute.COS_FRESH_AIR_INSTALLER_SETTINGS, ValueType.INTEGER),
                (
                    Attribute.COS_THERMOSTAT_SETPOINT_AND_MODE_SETTINGS,
                    ValueType.INTEGER,
                ),
                (Attribute.COS_DEHUMIDIFICATION_SETPOINT, ValueType.INTEGER),
                (Attribute.COS_HUMIDIFICATION_SETPOINT, ValueType.INTEGER),
                (Attribute.COS_FRESH_AIR_SETTING, ValueType.INTEGER),
                (Attribute.COS_AIR_CLEANING_SETTINGS, ValueType.INTEGER),
                (Attribute.COS_THERMOSTAT_IAQ_AVAILABLE, ValueType.INTEGER),
                (Attribute.COS_SCHEDULE_SETTINGS, ValueType.INTEGER),
                (Attribute.COS_AWAY_SETTINGS, ValueType.INTEGER),
                (Attribute.COS_SCHEDULE_DAY, ValueType.INTEGER),
                (Attribute.COS_SCHEDULE_HOLD, ValueType.INTEGER),
                (Attribute.COS_HEAT_BLAST, ValueType.INTEGER),
                (Attribute.COS_SERVICE_REMINDERS_STATUS, ValueType.INTEGER),
                (Attribute.COS_ALERTS_STATUS, ValueType.INTEGER),
                (Attribute.COS_ALERTS_SETTINGS, ValueType.INTEGER),
                (Attribute.COS_BACKLIGHT_SETTINGS, ValueType.INTEGER),
                (Attribute.COS_THERMOSTAT_LOCATION_AND_NAME, ValueType.INTEGER),
                (None, None),  # 21 Reserved
                (Attribute.COS_CONTROLLING_SENSOR_VALUES, ValueType.INTEGER),
                (Attribute.COS_OVER_THE_AIR_ODT_UPDATE_TIMEOUT, ValueType.INTEGER),
                (Attribute.COS_THERMOSTAT_STATUS, ValueType.INTEGER),
                (Attribute.COS_IAQ_STATUS, ValueType.INTEGER),
                (Attribute.COS_MODEL_AND_REVISION, ValueType.INTEGER),
                (Attribute.COS_SUPPORT_MODULE, ValueType.INTEGER),
                (Attribute.COS_LOCKOUTS, ValueType.INTEGER),
            ],
            2: [
                (Attribute.SYNCED, ValueType.INTEGER),
                (None, None),
            ],
            6: [
                (Attribute.HEATING_EQUIPMENT_STATUS, ValueType.INTEGER),
                (Attribute.COOLING_EQUIPMENT_STATUS, ValueType.INTEGER),
                (Attribute.PROGRESSIVE_RECOVERY, ValueType.INTEGER),
                (Attribute.FAN_STATUS, ValueType.INTEGER),
            ],
            7: [
                (Attribute.DEHUMIDIFICATION_STATUS, ValueType.INTEGER),
                (Attribute.HUMIDIFICATION_STATUS, ValueType.INTEGER),
                (Attribute.VENTILATION_STATUS, ValueType.INTEGER),
                (Attribute.AIR_CLEANING_STATUS, ValueType.INTEGER),
            ],
            8: [
                (Attribute.ERROR, ValueType.INTEGER),
            ],
        },
        FunctionalDomain.IDENTIFICATION: {
            1: [
                (Attribute.HARDWARE_REVISION, ValueType.INTEGER),
                (Attribute.FIRMWARE_MAJOR_REVISION, ValueType.INTEGER),
                (Attribute.FIRMWARE_MINOR_REVISION, ValueType.INTEGER),
                (Attribute.PROTOCOL_MAJOR_REVISION, ValueType.INTEGER),
                (Attribute.MODEL_NUMBER, ValueType.INTEGER),
                (Attribute.GAINSPAN_FIRMWARE_MAJOR_REVISION, ValueType.INTEGER),
                (Attribute.GAINSPAN_FIRMWARE_MINOR_REVISION, ValueType.INTEGER),
            ],
            2: [
                (Attribute.MAC_ADDRESS, ValueType.MAC_ADDRESS),
                (Attribute.FORCE_CONNECTION, ValueType.INTEGER),
                (Attribute.CONNECTION_TYPE, ValueType.INTEGER),
            ],
            4: [
                (Attribute.LOCATION, ValueType.TEXT, 7),
                (Attribute.NAME, ValueType.TEXT, 15),
            ],
            5: [
                (Attribute.LOCATION, ValueType.TEXT, 7),
                (Attribute.NAME, ValueType.TEXT, 15),
            ],
        },
    }
}

MAPPING[Action.COS] = MAPPING[Action.READ_RESPONSE]
MAPPING[Action.WRITE] = MAPPING[Action.READ_RESPONSE]
MAPPING[Action.READ_REQUEST] = MAPPING[Action.READ_RESPONSE]


class Packet:
    def __init__(
        self,
        action: Action,
        functional_domain: FunctionalDomain,
        attribute: int,
        revision: int = 1,
        sequence: int = 0,
        count: int = 0,
        data: dict[str, Any] | None = None,
        raw_data: list[int] | None = None,
    ):
        self.action = action
        self.functional_domain = functional_domain
        self.attribute = attribute
        self.revision = revision
        self.sequence = sequence
        self.count = count
        self.data = data or {}
        self.raw_data = raw_data

        # Set by `parse`: the frame's bytes, and why it couldn't be decoded
        self.raw = b""
        self.error: str | None = None

    @property
    def payload(self) -> bytes:
        """The parsed frame's bytes after its action, functional domain and
        attribute (or a NACK's status code), excluding the CRC"""
        return self.raw[6 if self.action == Action.NACK else 7 : -1]

    @property
    def crc_valid(self) -> bool:
        """Whether the parsed frame's CRC matches its contents"""
        return bool(self.raw) and self._verify_crc(self.raw[:-1], self.raw[-1])

    @classmethod
    def get_parseable_length(self, data: bytes) -> int:
        """Return how many leading bytes of `data` make up zero or more
        complete frames.

        Spec section F: a frame is REV(1) SEQ(1) CNT(2, high byte first)
        PAYLOAD(CNT bytes) CRC(1), so frame boundaries need only REV/SEQ/CNT.
        A caller buffering a byte stream uses this to find how much of the
        buffer to hand to `parse`, leaving any trailing partial frame behind.
        """
        data_index = 0
        length = len(data)

        while data_index + 4 <= length:
            count = data[data_index + 2] << 8 | data[data_index + 3]
            frame_end = data_index + count + 5

            if frame_end > length:
                break

            data_index = frame_end

        return data_index

    @classmethod
    def parse(self, data: bytes, strict: bool = True) -> Iterator[Packet]:
        """Parse the complete frames in `data`, ignoring a trailing partial one.

        Only frames that decode against `MAPPING` with a valid CRC are yielded
        unless `strict` is False, in which case every frame is, with `raw`
        holding its bytes and `error` saying why it couldn't be decoded.
        """
        data_index = 0
        parseable_length = self.get_parseable_length(data)

        while data_index < parseable_length:
            count = data[data_index + 2] << 8 | data[data_index + 3]
            frame = bytes(data[data_index : data_index + count + 5])
            data_index += count + 5

            packet = self._parse_frame(frame)

            if not strict or (packet.error is None and packet.crc_valid):
                yield packet

    @classmethod
    def _parse_frame(self, frame: bytes) -> Packet:
        """Parse one complete frame, setting `error` if it can't be decoded"""
        revision, sequence, count = frame[0], frame[1], len(frame) - 5
        body = frame[4:-1]

        if body[:1] == bytes([Action.NACK]):
            # Spec section G: for a NACK this byte is a section H.5 status
            # code (0x00-0xFF), not a FunctionalDomain member.
            packet = NackPacket(
                body[1] if len(body) > 1 else None, revision, sequence, count
            )

            if len(body) < 2:
                packet.error = "NACK has no status code"
        else:
            action, functional_domain, attribute = [*body[:3], None, None, None][:3]

            packet = Packet(
                action, functional_domain, attribute, revision, sequence, count
            )
            packet.error = self._decode_body(packet, body)

        packet.raw = frame

        return packet

    @classmethod
    def _decode_body(self, packet: Packet, body: bytes) -> str | None:
        """Decode a frame's action, functional domain, attribute and data into
        `packet`, returning why it couldn't be decoded, or None"""
        if len(body) < 3:
            return "Frame is too short for an action, functional domain and attribute"

        try:
            packet.action = Action(packet.action)
        except ValueError:
            return "Unknown action"

        try:
            packet.functional_domain = FunctionalDomain(packet.functional_domain)
        except ValueError:
            return "Unknown functional domain"

        mapped_attributes = (
            MAPPING.get(packet.action, {})
            .get(packet.functional_domain, {})
            .get(packet.attribute)
        )

        if mapped_attributes is None:
            return "Unknown attribute"

        data_index = 3
        final_index = len(body) - 1

        for attribute_info in mapped_attributes:
            if data_index > final_index:
                break

            attribute_name, value_type, *extra_attribute_info = attribute_info

            if attribute_name is None or value_type is None:
                data_index += 1
                continue

            data_value = body[data_index]

            if value_type == ValueType.INTEGER:
                packet.data[attribute_name] = data_value
                data_index += 1
            elif value_type == ValueType.INTEGER_REQUIRED:
                if data_value != 0:
                    packet.data[attribute_name] = data_value
                data_index += 1
            elif value_type == ValueType.HUMIDITY:
                packet.data[attribute_name] = self._decode_humidity(data_value)
                data_index += 1
            elif value_type == ValueType.TEMPERATURE:
                packet.data[attribute_name] = self._decode_temperature(data_value)
                data_index += 1
            elif value_type == ValueType.TEMPERATURE_REQUIRED:
                if data_value != 0:
                    packet.data[attribute_name] = self._decode_temperature(data_value)
                data_index += 1
            elif value_type == ValueType.MAC_ADDRESS:
                if data_index + 5 > final_index:
                    return f"Frame is too short for {attribute_name}"

                packet.data[attribute_name] = ":".join(
                    f"{value:02x}" for value in body[data_index : data_index + 6]
                )
                data_index += 6
            else:
                text_length = extra_attribute_info[0]

                # TEXT consumes text_length bytes plus one trailing byte.
                if data_index + text_length > final_index:
                    return f"Frame is too short for {attribute_name}"

                text = body[data_index : data_index + text_length]

                packet.data[attribute_name] = "".join(
                    " " if value == 0 else chr(value) for value in text
                ).strip(" ")
                data_index += text_length + 1

        return None

    @classmethod
    def _generate_crc(self, lst: list[int]):
        """Generate a CRC checksum"""
        return crc_calculator.checksum(bytes(lst))

    @classmethod
    def _verify_crc(self, lst: list[int], crc: int):
        """Verify a CRC checksum"""
        return crc_calculator.verify(bytes(lst), crc)

    @classmethod
    def _encode_temperature(self, temperature: float) -> int:
        """Encode a temperature value for sending to the thermostat"""
        is_negative = temperature < 0
        is_fraction = temperature % 1 >= 0.5

        return (
            math.floor(abs(temperature))
            + (64 if is_fraction else 0)
            + (128 if is_negative else 0)
        )

    @classmethod
    def _decode_temperature(self, raw_value: int) -> float:
        """Decode a temperature value from the thermostat"""
        temperature_value = float(int(raw_value & 63))

        raw_value = raw_value >> 6
        has_fraction = bool(raw_value & 1)
        if has_fraction:
            temperature_value += 0.5

        raw_value = raw_value >> 1
        is_positive = raw_value & 1 == 0
        if not is_positive:
            temperature_value = -temperature_value

        return temperature_value

    @classmethod
    def _decode_humidity(self, raw_value: int) -> int:
        """Decode a humidity value from the thermostat"""
        if raw_value < 0 or raw_value > 100:
            return None
        return raw_value

    @classmethod
    def _encode_int_value(self, value: int):
        return ((value >> 8) & 0xFF, value & 0xFF)

    def serialize(self) -> bytes:
        if isinstance(self, NackPacket):
            payload = [int(Action.NACK), self.status_code]
        else:
            payload = [int(self.action), int(self.functional_domain), self.attribute]

            if self.raw_data is not None:
                payload.extend(self.raw_data)
            elif (
                self.action == Action.WRITE
                or self.action == Action.READ_RESPONSE
                or self.action == Action.COS
            ):
                mapped_attributes = MAPPING[self.action][self.functional_domain][
                    self.attribute
                ]

                if self.action == Action.WRITE and not any(
                    self.data.get(attribute_info[0]) is not None
                    for attribute_info in mapped_attributes
                    if attribute_info[0] is not None
                ):
                    # Spec section G: an all-NULL payload changes nothing on
                    # the device, so such a write is rejected as a mistake.
                    raise ValueError(
                        f"Write to {self.functional_domain!s}/{self.attribute} "
                        "has no populated fields - every mapped field would "
                        "serialize as NULL, making this write a no-op"
                    )

                for attribute_info in mapped_attributes:
                    attribute_name, value_type, extra_attribute_info = (
                        attribute_info[0],
                        attribute_info[1],
                        attribute_info[2:],
                    )

                    data_value = self.data.get(attribute_name)

                    if data_value is None:
                        # Spec section G: NULL (0x00) leaves a field
                        # unmodified, but must still occupy as many bytes as a
                        # populated value of this ValueType would.
                        if value_type == ValueType.MAC_ADDRESS:
                            payload.extend([0] * 6)
                        elif value_type == ValueType.TEXT:
                            text_length = extra_attribute_info[0]
                            payload.extend([0] * (text_length + 1))
                        else:
                            payload.append(0)
                    elif (
                        value_type == ValueType.INTEGER
                        or value_type == ValueType.INTEGER_REQUIRED
                        or value_type == ValueType.HUMIDITY
                    ):
                        payload.append(data_value)
                    elif (
                        value_type == ValueType.TEMPERATURE
                        or value_type == ValueType.TEMPERATURE_REQUIRED
                    ):
                        payload.append(self._encode_temperature(data_value))
                    elif value_type == ValueType.MAC_ADDRESS:
                        payload.extend(data_value)
                    elif value_type == ValueType.TEXT:
                        text_length = extra_attribute_info[0]

                        for i in range(0, text_length + 1):
                            if i >= len(data_value):
                                payload.append(0)
                            else:
                                payload.append(ord(data_value[i]))
                    else:  # pragma: no cover
                        # Guards against a ValueType member added without a
                        # branch above.
                        payload.append(0)

        payload_length_high, payload_length_low = self._encode_int_value(len(payload))
        result = [1, self.sequence, payload_length_high, payload_length_low]
        result.extend(payload)
        result.append(self._generate_crc(result))
        return bytes(result)

    def __eq__(self, other):
        return (
            self.action == other.action
            and self.functional_domain == other.functional_domain
            and self.attribute == other.attribute
            and self.data == other.data
        )


class NackPacket(Packet):
    def __init__(
        self,
        status_code: int,
        revision: int = 1,
        sequence: int = 0,
        count: int = 0,
    ):
        super().__init__(
            Action.NACK, FunctionalDomain.NACK, 0, revision, sequence, count
        )

        self.status_code = status_code
