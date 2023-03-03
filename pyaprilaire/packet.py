"""Functions for handling response data from the thermostat"""

from __future__ import annotations

from crc import Calculator, Configuration
from enum import Enum
import math
from typing import Any

from pyaprilaire.const import Action, FunctionalDomain

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
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                ("away_available", ValueType.INTEGER),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
            ]
        },
        FunctionalDomain.CONTROL: {
            1: [
                ("mode", ValueType.INTEGER_REQUIRED),
                ("fan_mode", ValueType.INTEGER_REQUIRED),
                ("heat_setpoint", ValueType.TEMPERATURE_REQUIRED),
                ("cool_setpoint", ValueType.TEMPERATURE_REQUIRED),
            ],
            7: [
                ("thermostat_modes", ValueType.INTEGER),
                ("air_cleaning_available", ValueType.INTEGER),
                ("ventilation_available", ValueType.INTEGER),
                ("dehumidification_available", ValueType.INTEGER),
                ("humidification_available", ValueType.INTEGER),
            ],
        },
        FunctionalDomain.SCHEDULING: {
            4: [
                ("hold", ValueType.INTEGER),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
                (None, None),
            ],
        },
        FunctionalDomain.SENSORS: {
            1: [
                ("built_in_temperature_sensor_status", ValueType.INTEGER),
                ("built_in_temperature_sensor_value", ValueType.TEMPERATURE),
                (
                    "wired_remote_temperature_sensor_status",
                    ValueType.INTEGER,
                ),
                (
                    "wired_remote_temperature_sensor_value",
                    ValueType.TEMPERATURE,
                ),
                (
                    "wired_outdoor_temperature_sensor_status",
                    ValueType.INTEGER,
                ),
                (
                    "wired_outdoor_temperature_sensor_value",
                    ValueType.TEMPERATURE,
                ),
                ("built_in_humidity_sensor_status", ValueType.INTEGER),
                ("built_in_humidity_sensor_value", ValueType.HUMIDITY),
                ("rat_sensor_status", ValueType.INTEGER),
                ("rat_sensor_value", ValueType.TEMPERATURE),
                ("lat_sensor_status", ValueType.INTEGER),
                ("lat_sensor_value", ValueType.TEMPERATURE),
                (
                    "wireless_outdoor_temperature_sensor_status",
                    ValueType.INTEGER,
                ),
                (
                    "wireless_outdoor_temperature_sensor_value",
                    ValueType.TEMPERATURE,
                ),
                (
                    "wireless_outdoor_humidity_sensor_status",
                    ValueType.INTEGER,
                ),
                (
                    "wireless_outdoor_humidity_sensor_value",
                    ValueType.HUMIDITY,
                ),
            ],
            2: [
                (
                    "indoor_temperature_controlling_sensor_status",
                    ValueType.INTEGER,
                ),
                (
                    "indoor_temperature_controlling_sensor_value",
                    ValueType.TEMPERATURE,
                ),
                (
                    "outdoor_temperature_controlling_sensor_status",
                    ValueType.INTEGER,
                ),
                (
                    "outdoor_temperature_controlling_sensor_value",
                    ValueType.TEMPERATURE,
                ),
                (
                    "indoor_humidity_controlling_sensor_status",
                    ValueType.INTEGER,
                ),
                (
                    "indoor_humidity_controlling_sensor_value",
                    ValueType.HUMIDITY,
                ),
                (
                    "outdoor_humidity_controlling_sensor_status",
                    ValueType.INTEGER,
                ),
                (
                    "outdoor_humidity_controlling_sensor_value",
                    ValueType.HUMIDITY,
                ),
            ],
        },
        FunctionalDomain.STATUS: {
            2: [
                ("synced", ValueType.INTEGER),
            ],
            6: [
                ("heating_equipment_status", ValueType.INTEGER),
                ("cooling_equipment_status", ValueType.INTEGER),
                ("progressive_recovery", ValueType.INTEGER),
                ("fan_status", ValueType.INTEGER),
            ],
            7: [
                ("dehumidification_status", ValueType.INTEGER),
                ("humidification_status", ValueType.INTEGER),
                ("ventilation_status", ValueType.INTEGER),
                ("air_cleaning_status", ValueType.INTEGER),
            ],
            8: [
                ("error", ValueType.INTEGER),
            ],
        },
        FunctionalDomain.IDENTIFICATION: {
            1: [
                ("hardware_revision", ValueType.INTEGER),
                ("firmware_major_revision", ValueType.INTEGER),
                ("firmware_minor_revision", ValueType.INTEGER),
                ("protocol_major_revision", ValueType.INTEGER),
                ("model_number", ValueType.INTEGER),
                ("gainspan_firmware_major_revision", ValueType.INTEGER),
                ("gainspan_firmware_minor_revision", ValueType.INTEGER),
            ],
            2: [
                ("mac_address", ValueType.MAC_ADDRESS),
            ],
            4: [
                ("location", ValueType.TEXT, 7),
                ("name", ValueType.TEXT, 15),
            ],
            5: [
                ("location", ValueType.TEXT, 7),
                ("name", ValueType.TEXT, 15),
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
        data: dict[str, Any] = None,
        raw_data: list[int] = None,
    ):
        self.action = action
        self.functional_domain = functional_domain
        self.attribute = attribute
        self.revision = revision
        self.sequence = sequence
        self.count = count
        self.data = data or {}
        self.raw_data = raw_data

    @classmethod
    def parse(self, data: bytes) -> list[Packet]:
        data_index = 0

        while data_index < len(data):
            revision = data[data_index]
            sequence = data[data_index + 1]
            count = data[data_index + 2] << 2 | data[data_index + 3]

            action = int(data[data_index + 4])
            functional_domain = int(data[data_index + 5])
            attribute = int(data[data_index + 6])

            try:
                action = Action(action)
                functional_domain = FunctionalDomain(functional_domain)
            except:
                data_index += count + 5
                continue

            if action == Action.NACK:
                nack_attribute = int(data[data_index + 5])

                yield NackPacket(nack_attribute)

                data_index += count + 5
                continue

            if (
                action not in MAPPING
                or functional_domain not in MAPPING[action]
                or attribute not in MAPPING[action][functional_domain]
            ):
                data_index += count + 5
                continue

            packet = Packet(
                action, functional_domain, attribute, revision, sequence, count
            )

            # Skip header
            final_index = data_index + count + 3
            data_index += 7
            attribute_index = 0

            while data_index <= final_index:
                if attribute_index >= len(
                    MAPPING[action][functional_domain][attribute]
                ):
                    data_index += 1
                    pass
                else:
                    attribute_info = MAPPING[action][functional_domain][attribute][
                        attribute_index
                    ]

                    (attribute_name, value_type, extra_attribute_info) = (
                        attribute_info[0],
                        attribute_info[1],
                        attribute_info[2:],
                    )

                    if attribute_name is None or value_type is None:
                        data_index += 1
                        attribute_index += 1
                        continue

                    data_value = data[data_index]

                    if value_type == ValueType.INTEGER:
                        packet.data[attribute_name] = data_value
                        data_index += 1
                    elif value_type == ValueType.INTEGER_REQUIRED:
                        if data_value is not None and data_value != 0:
                            packet.data[attribute_name] = data_value
                        data_index += 1
                    elif value_type == ValueType.HUMIDITY:
                        packet.data[attribute_name] = self._decode_humidity(data_value)
                        data_index += 1
                    elif value_type == ValueType.TEMPERATURE:
                        packet.data[attribute_name] = self._decode_temperature(
                            data_value
                        )
                        data_index += 1
                    elif value_type == ValueType.TEMPERATURE_REQUIRED:
                        if data_value is not None and data_value != 0:
                            packet.data[attribute_name] = self._decode_temperature(
                                data_value
                            )
                        data_index += 1
                    elif value_type == ValueType.MAC_ADDRESS:
                        mac_address_components = []

                        for _ in range(0, 6):
                            mac_address_components.append(f"{data[data_index]:x}")
                            data_index += 1

                        packet.data[attribute_name] = ":".join(mac_address_components)
                    elif value_type == ValueType.TEXT:
                        text_length = extra_attribute_info[0]

                        text = ""

                        for _ in range(0, text_length):
                            current_value = (
                                " " if data[data_index] == 0 else chr(data[data_index])
                            )
                            text += current_value
                            data_index += 1

                        data_index += 1

                        text = text.strip(" ")

                        packet.data[attribute_name] = text

                    attribute_index += 1

            yield packet

            data_index += 1

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
            math.floor(temperature)
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
        if raw_value == 0 or raw_value >= 100:
            return None
        return raw_value

    @classmethod
    def _encode_int_value(self, value: int):
        return ((value >> 8) & 0xFF, value & 0xFF)

    def serialize(self) -> bytes:
        if isinstance(self, NackPacket):
            payload = [int(Action.NACK), self.nack_attribute]
        else:
            payload = [int(self.action), int(self.functional_domain), self.attribute]

            if self.raw_data is not None:
                payload.extend(self.raw_data)
            elif (
                self.action == Action.WRITE
                or self.action == Action.READ_RESPONSE
                or self.action == Action.COS
            ):
                for attribute_info in MAPPING[self.action][self.functional_domain][
                    self.attribute
                ]:
                    (attribute_name, value_type, extra_attribute_info) = (
                        attribute_info[0],
                        attribute_info[1],
                        attribute_info[2:],
                    )

                    data_value = self.data.get(attribute_name)

                    if (
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
                    else:
                        payload.append(0)

        (payload_length_high, payload_length_low) = self._encode_int_value(len(payload))
        result = [1, self.sequence, payload_length_high, payload_length_low]
        result.extend(payload)
        result.append(self._generate_crc(result))
        return bytes(result)


class NackPacket(Packet):
    def __init__(
        self,
        nack_attribute: int,
        revision: int = 1,
        sequence: int = 0,
        count: int = 0,
    ):
        super().__init__(
            Action.NACK, FunctionalDomain.NACK, 0, revision, sequence, count
        )

        self.nack_attribute = nack_attribute
