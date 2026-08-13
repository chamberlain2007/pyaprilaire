"""Discovery of the commands that can be sent interactively to a device

The functions exposed by :class:`~pyaprilaire.client.AprilaireClient` are
discovered by reflection rather than being listed by hand, so a command added
to the client is immediately available to the interactive tools.
"""

from __future__ import annotations

import inspect
import typing
from dataclasses import dataclass, field
from typing import Any, Callable

from .client import AprilaireClient
from .const import Action, FunctionalDomain
from .frame import attribute_name
from .packet import MAPPING, Packet, ValueType

# Methods that manage the connection itself rather than sending a command
EXCLUDED_COMMANDS = {
    "create_protocol",
    "data_received",
    "start_listen",
    "start_listen_once",
    "state_changed",
    "stop_listen",
    "test_connection",
    "wait_for_response",
}

_TYPE_NAMES = {
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
}

_TRUE_VALUES = {"1", "true", "t", "yes", "y", "on"}
_FALSE_VALUES = {"0", "false", "f", "no", "n", "off"}


@dataclass
class CommandParameter:
    """A single parameter of a client command"""

    name: str
    annotation: type = None
    default: Any = inspect.Parameter.empty

    @property
    def required(self) -> bool:
        """Whether a value must be provided for the parameter"""
        return self.default is inspect.Parameter.empty

    @property
    def type_name(self) -> str:
        """The display name of the parameter type"""
        return self.annotation.__name__ if self.annotation else "any"

    @property
    def display(self) -> str:
        """The parameter as it would appear in a signature"""

        display = f"{self.name}: {self.type_name}"

        if not self.required:
            display += f" = {self.default}"

        return display

    def parse(self, text: str) -> Any:
        """Convert entered text into a value for the parameter

        Raises:
            ValueError: the text is not valid for the parameter type
        """

        text = text.strip()

        if not text:
            if self.required:
                raise ValueError(f"A value is required for {self.name}")

            return self.default

        if self.annotation is bool:
            if text.lower() in _TRUE_VALUES:
                return True

            if text.lower() in _FALSE_VALUES:
                return False

            raise ValueError(f"{self.name} must be true or false, got '{text}'")

        if self.annotation is int:
            try:
                # Base zero so that hex and binary literals are accepted
                return int(text, 0)
            except ValueError:
                raise ValueError(
                    f"{self.name} must be an integer, got '{text}'"
                ) from None

        if self.annotation is float:
            try:
                return float(text)
            except ValueError:
                raise ValueError(
                    f"{self.name} must be a number, got '{text}'"
                ) from None

        return text


@dataclass
class ClientCommand:
    """A function exposed by the client that can be sent to a device"""

    name: str
    description: str = ""
    parameters: list[CommandParameter] = field(default_factory=list)

    @property
    def signature(self) -> str:
        """The command as it would appear in a signature"""

        parameters = ", ".join(parameter.display for parameter in self.parameters)

        return f"{self.name}({parameters})"

    def parse_arguments(self, values: list[str]) -> list[Any]:
        """Convert entered text for each parameter into argument values

        Raises:
            ValueError: too many values, or a value is not valid
        """

        if len(values) > len(self.parameters):
            raise ValueError(
                f"{self.name} takes at most {len(self.parameters)} argument(s),"
                f" got {len(values)}"
            )

        arguments = []

        for index, parameter in enumerate(self.parameters):
            value = values[index] if index < len(values) else ""

            arguments.append(parameter.parse(value))

        return arguments


def _resolve_annotations(method: Callable) -> dict[str, Any]:
    """Resolve the annotations of a method to types where possible"""

    try:
        return typing.get_type_hints(method)
    except Exception:  # pylint: disable=broad-except
        # Fall back to matching the annotation text, as the modules use
        # postponed evaluation of annotations
        return {
            name: _TYPE_NAMES.get(parameter.annotation)
            for name, parameter in inspect.signature(method).parameters.items()
        }


def _describe_command(name: str, method: Callable) -> ClientCommand:
    """Describe a single client method as a command"""

    annotations = _resolve_annotations(method)

    parameters = [
        CommandParameter(
            name=parameter_name,
            annotation=annotations.get(parameter_name),
            default=parameter.default,
        )
        for parameter_name, parameter in inspect.signature(method).parameters.items()
        if parameter_name != "self"
    ]

    description = inspect.getdoc(method) or ""

    return ClientCommand(
        name=name,
        description=description.strip().splitlines()[0] if description else "",
        parameters=parameters,
    )


def discover_client_commands(
    client_class: type = AprilaireClient,
) -> list[ClientCommand]:
    """Discover the commands exposed by the client"""

    commands = [
        _describe_command(name, method)
        for name, method in inspect.getmembers(
            client_class, inspect.iscoroutinefunction
        )
        if not name.startswith("_") and name not in EXCLUDED_COMMANDS
    ]

    return sorted(commands, key=lambda command: command.name)


def find_command(name: str, commands: list[ClientCommand] = None) -> ClientCommand:
    """Find a command by name, or return None if there is no such command"""

    for command in commands if commands is not None else discover_client_commands():
        if command.name == name:
            return command

    return None


@dataclass
class MappingField:
    """A named value within the payload of a known packet"""

    name: str
    value_type: ValueType

    @property
    def type_name(self) -> str:
        """The display name of the value type"""
        return self.value_type.name

    def parse(self, text: str) -> Any:
        """Convert entered text into a value for the field

        Raises:
            ValueError: the text is not valid for the field type
        """

        text = text.strip()

        if not text:
            return "" if self.value_type == ValueType.TEXT else 0

        if self.value_type == ValueType.TEXT:
            return text

        if self.value_type == ValueType.MAC_ADDRESS:
            return list(parse_hex_bytes(text))

        if self.value_type in (
            ValueType.TEMPERATURE,
            ValueType.TEMPERATURE_REQUIRED,
        ):
            try:
                return float(text)
            except ValueError:
                raise ValueError(
                    f"{self.name} must be a number, got '{text}'"
                ) from None

        try:
            return int(text, 0)
        except ValueError:
            raise ValueError(f"{self.name} must be an integer, got '{text}'") from None


def mapping_fields(
    action: Action, functional_domain: FunctionalDomain, attribute: int
) -> list[MappingField]:
    """Get the named payload fields of a packet, if the packet is known

    Unnamed padding within the payload is excluded, as it is filled in
    automatically when the packet is serialized.
    """

    attributes = MAPPING.get(action, {}).get(functional_domain, {}).get(attribute)

    if not attributes:
        return []

    return [
        MappingField(
            name=attribute_name(attribute_info[0]), value_type=attribute_info[1]
        )
        for attribute_info in attributes
        if attribute_info[0] is not None and attribute_info[1] is not None
    ]


def known_attributes(action: Action, functional_domain: FunctionalDomain) -> list[int]:
    """Get the attributes that are known for an action and functional domain"""

    return sorted(MAPPING.get(action, {}).get(functional_domain, {}))


def has_payload(action: Action) -> bool:
    """Whether a packet with the given action carries a payload"""

    return action in (Action.WRITE, Action.READ_RESPONSE, Action.COS)


def parse_field_values(values: list[str], fields: list[MappingField]) -> dict[str, Any]:
    """Parse name=value pairs into the data of a packet

    Every named field of the packet is included in the result, as a packet
    can only be serialized when all of its fields have a value.

    Raises:
        ValueError: a value is not a name=value pair, names an unknown field,
            or is not valid for the field
    """

    fields_by_name = {mapping_field.name: mapping_field for mapping_field in fields}

    data: dict[str, Any] = {}

    for value in values:
        if "=" not in value:
            raise ValueError(f"'{value}' is not a name=value pair")

        name, _, text = value.partition("=")
        name = name.strip()

        if name not in fields_by_name:
            raise ValueError(
                f"'{name}' is not a field of this packet."
                f" Fields: {', '.join(fields_by_name)}"
            )

        data[name] = fields_by_name[name].parse(text)

    for name, mapping_field in fields_by_name.items():
        if name not in data:
            data[name] = mapping_field.parse("")

    return data


def build_packet(
    action: Action,
    functional_domain: FunctionalDomain,
    attribute: int,
    values: list[str] = None,
) -> Packet:
    """Build a packet from its parts

    The values are either name=value pairs for a packet with known fields, or
    the raw payload as hex.

    Raises:
        ValueError: the values are not valid for the packet
    """

    values = [value for value in (values or []) if value]

    if any("=" in value for value in values):
        fields = mapping_fields(action, functional_domain, attribute)

        if not fields:
            raise ValueError(
                f"{action.name} {functional_domain.name} attribute {attribute}"
                " has no known fields, so a raw payload must be given"
            )

        return Packet(
            action,
            functional_domain,
            attribute,
            data=parse_field_values(values, fields),
        )

    if values:
        return Packet(
            action,
            functional_domain,
            attribute,
            raw_data=list(parse_hex_bytes(" ".join(values))),
        )

    if has_payload(action) and not mapping_fields(action, functional_domain, attribute):
        raise ValueError(
            f"{action.name} {functional_domain.name} attribute {attribute}"
            " has no known fields, so a raw payload must be given"
        )

    return Packet(action, functional_domain, attribute)


def describe_packet_fields(
    action: Action, functional_domain: FunctionalDomain, attribute: int
) -> str:
    """Describe the known payload fields of a packet in a single line"""

    fields = mapping_fields(action, functional_domain, attribute)

    if fields:
        return "Fields: " + ", ".join(
            f"{mapping_field.name} ({mapping_field.type_name})"
            for mapping_field in fields
        )

    attributes = known_attributes(action, functional_domain)

    if has_payload(action):
        description = "No known fields, enter the payload as hex."
    else:
        description = f"{action.name} has no payload."

    if attributes:
        description += " Known attributes: " + ", ".join(
            str(known) for known in attributes
        )

    return description


def parse_hex_bytes(text: str) -> bytes:
    """Parse text as a sequence of hex bytes

    Bytes may be separated by spaces or commas or not at all, and may
    optionally be prefixed with 0x, so all of the following are equivalent:
    `01 02 0a`, `0102 0a`, `0x01, 0x02, 0x0A`.

    Raises:
        ValueError: the text is not a valid sequence of hex bytes
    """

    tokens = text.replace(",", " ").split()

    if not tokens:
        raise ValueError("No bytes were provided")

    data = bytearray()

    for token in tokens:
        if token.lower().startswith("0x"):
            token = token[2:]

        if not token:
            raise ValueError("No bytes were provided")

        if len(token) == 1:
            token = f"0{token}"

        try:
            data.extend(bytes.fromhex(token))
        except ValueError:
            raise ValueError(f"'{token}' is not a valid hex byte") from None

    return bytes(data)


def parse_enum(enum_class, text: str):
    """Parse text as either the name or the value of an enum member

    Raises:
        ValueError: the text does not match a member of the enum
    """

    text = text.strip()

    try:
        return enum_class[text.upper()]
    except KeyError:
        pass

    try:
        return enum_class(int(text, 0))
    except ValueError:
        names = ", ".join(member.name for member in enum_class)

        raise ValueError(f"'{text}' is not valid, expected one of: {names}") from None
