"""Functions for handling response data from the thermostat"""

from __future__ import annotations

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

# A packet is a revision, a sequence number and a two byte payload length,
# followed by that many bytes and a one byte checksum
HEADER_SIZE = 4
CRC_SIZE = 1
MIN_PACKET_SIZE = HEADER_SIZE + CRC_SIZE

# A payload longer than this is taken to be a corrupt length rather than a
# packet that hasn't fully arrived yet
MAX_PAYLOAD_SIZE = 512


def split_packets(data: bytes) -> tuple[list[bytes], bytes]:
    """Split a byte stream into complete packets and a trailing remainder

    A read from a device can end part way through a packet, so the remainder
    is whatever is left of an incomplete one and belongs at the front of the
    next data received.
    """

    packets: list[bytes] = []
    index = 0

    while index < len(data):
        remaining = len(data) - index

        if remaining < HEADER_SIZE:
            break

        count = data[index + 2] << 8 | data[index + 3]

        if count > MAX_PAYLOAD_SIZE:
            # The length is nonsense, so there is no reliable way to find
            # where the next packet starts. Surface the rest as a single
            # packet so that the bytes aren't silently dropped.
            packets.append(bytes(data[index:]))
            index = len(data)
            break

        size = HEADER_SIZE + count + CRC_SIZE

        if remaining < size:
            break

        packets.append(bytes(data[index : index + size]))
        index += size

    return packets, bytes(data[index:])


def attribute_name(attribute) -> str:
    """Get the name of a decoded attribute

    The attribute is normally an :class:`~pyaprilaire.const.Attribute`, which
    is a string enum, but the name is taken defensively so that it doesn't
    depend on how the enum renders itself.
    """

    return getattr(attribute, "value", None) or str(attribute)


def _enum_name(enum_class, value: int) -> str:
    """Get the name of an enum value, falling back to the raw value"""

    if value is None:
        return "?"

    try:
        return enum_class(value).name
    except ValueError:
        return f"UNKNOWN({value})"


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
                (Attribute.AWAY_AVAILABLE, ValueType.INTEGER),
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
                (Attribute.BUILT_IN_TEMPERATURE_SENSOR_STATUS, ValueType.INTEGER),
                (Attribute.BUILT_IN_TEMPERATURE_SENSOR_VALUE, ValueType.TEMPERATURE),
                (
                    Attribute.WIRED_REMOTE_TEMPERATURE_SENSOR_STATUS,
                    ValueType.INTEGER,
                ),
                (
                    Attribute.WIRED_REMOTE_TEMPERATURE_SENSOR_VALUE,
                    ValueType.TEMPERATURE,
                ),
                (
                    Attribute.WIRED_OUTDOOR_TEMPERATURE_SENSOR_STATUS,
                    ValueType.INTEGER,
                ),
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
                (
                    Attribute.WIRELESS_OUTDOOR_HUMIDITY_SENSOR_STATUS,
                    ValueType.INTEGER,
                ),
                (
                    Attribute.WIRELESS_OUTDOOR_HUMIDITY_SENSOR_VALUE,
                    ValueType.HUMIDITY,
                ),
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
            2: [
                (Attribute.SYNCED, ValueType.INTEGER),
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
    # Filled in when a packet is parsed from data, so that what arrived can be
    # shown exactly as it was on the wire. A packet that is being built to be
    # sent has none of it, as it doesn't exist as bytes until it is serialized
    raw: bytes = b""
    payload: bytes = b""
    crc: int = None
    crc_valid: bool = True
    error: str = None

    # Only a NACK has one, but every packet answers to it so that a packet can
    # be described without knowing which kind it is
    nack_attribute: int = None

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

    @property
    def action_name(self) -> str:
        """The name of the action, or a placeholder when it is unknown"""
        return _enum_name(Action, self.action)

    @property
    def functional_domain_name(self) -> str:
        """The name of the functional domain, or a placeholder when unknown"""
        return _enum_name(FunctionalDomain, self.functional_domain)

    @property
    def summary(self) -> str:
        """A one line description of what the packet addresses"""

        if self.action is None:
            return "empty packet"

        if self.action == Action.NACK:
            return f"NACK attribute {self.nack_attribute}"

        return (
            f"{self.action_name} {self.functional_domain_name}"
            f" attribute {self.attribute}"
        )

    @property
    def decoded(self) -> list[tuple[str, Any]]:
        """The decoded values the packet carries, in the order they appear"""

        values: list[tuple[str, Any]] = []

        if self.action == Action.NACK:
            values.append(("nack_attribute", self.nack_attribute))

        values.extend((attribute_name(key), value) for key, value in self.data.items())

        return values

    @classmethod
    def parse(self, data: bytes, strict: bool = True) -> Iterator[Packet]:
        """Parse the packets in a sequence of bytes

        Only packets that are understood, and whose checksum is correct, are
        returned by default, as there is nothing to be done with the rest.

        Tools that debug a device need the opposite, so strict=False returns a
        packet for everything instead. Those packets carry the bytes they were
        parsed from, whether the checksum was valid, the payload that couldn't
        be decoded and what was wrong with them.
        """

        index = 0

        while index < len(data):
            if len(data) - index < HEADER_SIZE:
                # There is no length to read, so whatever is left is all there
                # is to describe
                count = 0
            else:
                count = data[index + 2] << 8 | data[index + 3]

            size = HEADER_SIZE + count + CRC_SIZE

            packet = self._parse_packet(bytes(data[index : index + size]), strict)

            if packet is not None:
                yield packet

            index += size

    @classmethod
    def _parse_packet(self, raw: bytes, strict: bool = True) -> Packet:
        """Parse a single packet from the bytes it occupies

        Returns:
            The packet, or None when it can't be acted on and strict is set
        """

        if len(raw) < MIN_PACKET_SIZE:
            if strict:
                return None

            return self._unparsed(
                raw, error="Packet is too short to contain a header and a checksum"
            )

        count = raw[2] << 8 | raw[3]
        body = raw[HEADER_SIZE:-1]

        error = None

        if len(body) != count:
            error = (
                f"Length mismatch: header declares {count} byte(s),"
                f" packet contains {len(body)}"
            )

        if not body:
            if strict:
                return None

            packet = Packet(None, None, None, raw[0], raw[1], count)

            return self._parsed(
                packet, raw, payload=b"", error=error or "Packet has no action"
            )

        action = int(body[0])

        if action == Action.NACK:
            # A NACK carries the attribute it rejected where the functional
            # domain would normally be, and so has neither
            packet = NackPacket(
                int(body[1]) if len(body) > 1 else None, raw[0], raw[1], count
            )

            return self._parsed(packet, raw, payload=bytes(body[2:]), error=error)

        functional_domain = int(body[1]) if len(body) > 1 else None
        attribute = int(body[2]) if len(body) > 2 else None
        payload = bytes(body[3:])

        try:
            action = Action(action)
            functional_domain = FunctionalDomain(functional_domain)
        except ValueError:
            if strict:
                return None

            packet = Packet(
                action,
                functional_domain,
                attribute,
                raw[0],
                raw[1],
                count,
                raw_data=list(payload),
            )

            return self._parsed(packet, raw, payload=payload, error=error)

        if (
            action not in MAPPING
            or functional_domain not in MAPPING[action]
            or attribute not in MAPPING[action][functional_domain]
        ):
            if strict:
                return None

            packet = Packet(
                action,
                functional_domain,
                attribute,
                raw[0],
                raw[1],
                count,
                raw_data=list(payload),
            )

            return self._parsed(packet, raw, payload=payload, error=error)

        packet = Packet(action, functional_domain, attribute, raw[0], raw[1], count)

        try:
            self._decode_payload(packet, raw, count)
        except (IndexError, ValueError) as exc:
            if strict:
                return None

            error = error or f"Unable to decode the payload: {exc!r}"

        packet = self._parsed(packet, raw, payload=payload, error=error)

        if strict and not packet.crc_valid:
            return None

        return packet

    @classmethod
    def _unparsed(self, raw: bytes, error: str) -> Packet:
        """Build a packet for bytes that aren't a packet at all"""

        packet = Packet(None, None, None)
        packet.raw = bytes(raw)
        packet.error = error

        return packet

    @classmethod
    def _parsed(self, packet: Packet, raw: bytes, payload: bytes, error: str) -> Packet:
        """Record how a packet appeared on the wire"""

        packet.raw = bytes(raw)
        packet.payload = payload
        packet.crc = raw[-1]
        packet.crc_valid = self._verify_crc(raw[:-1], raw[-1])
        packet.error = error

        return packet

    @classmethod
    def _decode_payload(self, packet: Packet, raw: bytes, count: int) -> None:
        """Decode the payload of a known packet into its named attributes

        Raises:
            IndexError: the payload ends before the packet says it should
        """

        attributes = MAPPING[packet.action][packet.functional_domain][packet.attribute]

        # The payload starts after the header, action, functional domain and
        # attribute, and ends before the checksum
        final_index = count + 3
        data_index = 7
        attribute_index = 0

        while data_index <= final_index:
            if data_index >= len(raw) - CRC_SIZE:
                raise IndexError("the payload is shorter than the packet declares")

            if attribute_index >= len(attributes):
                data_index += 1
                continue

            attribute_info = attributes[attribute_index]

            name, value_type, extra_attribute_info = (
                attribute_info[0],
                attribute_info[1],
                attribute_info[2:],
            )

            if name is None or value_type is None:
                data_index += 1
                attribute_index += 1
                continue

            data_value = raw[data_index]

            if value_type == ValueType.INTEGER:
                packet.data[name] = data_value
                data_index += 1
            elif value_type == ValueType.INTEGER_REQUIRED:
                if data_value is not None and data_value != 0:
                    packet.data[name] = data_value
                data_index += 1
            elif value_type == ValueType.HUMIDITY:
                packet.data[name] = self._decode_humidity(data_value)
                data_index += 1
            elif value_type == ValueType.TEMPERATURE:
                packet.data[name] = self._decode_temperature(data_value)
                data_index += 1
            elif value_type == ValueType.TEMPERATURE_REQUIRED:
                if data_value is not None and data_value != 0:
                    packet.data[name] = self._decode_temperature(data_value)
                data_index += 1
            elif value_type == ValueType.MAC_ADDRESS:
                mac_address_components = []

                for _ in range(0, 6):
                    mac_address_components.append(f"{raw[data_index]:x}")
                    data_index += 1

                packet.data[name] = ":".join(mac_address_components)
            elif value_type == ValueType.TEXT:
                text_length = extra_attribute_info[0]

                text = ""

                for _ in range(0, text_length):
                    current_value = (
                        " " if raw[data_index] == 0 else chr(raw[data_index])
                    )
                    text += current_value
                    data_index += 1

                data_index += 1

                packet.data[name] = text.strip(" ")

            attribute_index += 1

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
                    attribute_name, value_type, extra_attribute_info = (
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
        nack_attribute: int,
        revision: int = 1,
        sequence: int = 0,
        count: int = 0,
    ):
        super().__init__(
            Action.NACK, FunctionalDomain.NACK, 0, revision, sequence, count
        )

        self.nack_attribute = nack_attribute
