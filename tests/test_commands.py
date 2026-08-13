import pytest

from pyaprilaire.commands import (
    build_packet,
    describe_packet_fields,
    discover_client_commands,
    find_command,
    has_payload,
    known_attributes,
    mapping_fields,
    parse_enum,
    parse_field_values,
    parse_hex_bytes,
)
from pyaprilaire.const import Action, Attribute, FunctionalDomain


@pytest.fixture
def commands():
    return discover_client_commands()


def test_discover_includes_client_functions(commands):
    names = [command.name for command in commands]

    assert "read_control" in names
    assert "update_setpoint" in names
    assert "set_written_outdoor_temperature_value" in names


def test_discover_excludes_connection_management(commands):
    names = [command.name for command in commands]

    for name in (
        "start_listen",
        "start_listen_once",
        "stop_listen",
        "test_connection",
        "wait_for_response",
        "data_received",
    ):
        assert name not in names


def test_discover_resolves_parameters(commands):
    command = find_command("update_setpoint", commands)

    assert [parameter.name for parameter in command.parameters] == [
        "cool_setpoint",
        "heat_setpoint",
    ]
    assert all(parameter.annotation is float for parameter in command.parameters)
    assert all(parameter.required for parameter in command.parameters)
    assert command.signature == (
        "update_setpoint(cool_setpoint: float, heat_setpoint: float)"
    )
    assert command.description == "Send a request to update the setpoint"


def test_find_command_missing(commands):
    assert find_command("not_a_command", commands) is None


def test_parse_arguments(commands):
    command = find_command("update_setpoint", commands)

    assert command.parse_arguments(["22.5", "19"]) == [22.5, 19.0]


def test_parse_arguments_accepts_hex(commands):
    command = find_command("update_mode", commands)

    assert command.parse_arguments(["0x03"]) == [3]


def test_parse_arguments_requires_value(commands):
    command = find_command("update_mode", commands)

    with pytest.raises(ValueError, match="A value is required for mode"):
        command.parse_arguments([])


def test_parse_arguments_rejects_bad_value(commands):
    command = find_command("update_mode", commands)

    with pytest.raises(ValueError, match="mode must be an integer"):
        command.parse_arguments(["cool"])


def test_parse_arguments_rejects_extra_values(commands):
    command = find_command("update_mode", commands)

    with pytest.raises(ValueError, match="takes at most 1 argument"):
        command.parse_arguments(["1", "2"])


def test_parse_hex_bytes():
    expected = bytes([1, 2, 10, 255])

    assert parse_hex_bytes("01 02 0a ff") == expected
    assert parse_hex_bytes("0102 0aff") == expected
    assert parse_hex_bytes("0x01, 0x02, 0x0A, 0xFF") == expected
    assert parse_hex_bytes("1 2 a ff") == expected


def test_parse_hex_bytes_rejects_invalid():
    with pytest.raises(ValueError, match="not a valid hex byte"):
        parse_hex_bytes("zz")

    with pytest.raises(ValueError, match="No bytes were provided"):
        parse_hex_bytes("   ")


def test_mapping_fields():
    fields = mapping_fields(Action.WRITE, FunctionalDomain.CONTROL, 1)

    assert [field.name for field in fields] == [
        "mode",
        "fan_mode",
        "heat_setpoint",
        "cool_setpoint",
    ]


def test_mapping_fields_excludes_padding():
    fields = mapping_fields(Action.READ_RESPONSE, FunctionalDomain.SCHEDULING, 4)

    assert [field.name for field in fields] == ["hold"]


def test_mapping_fields_unknown():
    assert mapping_fields(Action.WRITE, FunctionalDomain.CONTROL, 99) == []


def test_known_attributes():
    assert known_attributes(Action.READ_REQUEST, FunctionalDomain.CONTROL) == [
        1,
        3,
        4,
        5,
        6,
        7,
    ]


def test_has_payload():
    assert has_payload(Action.WRITE)
    assert not has_payload(Action.READ_REQUEST)


def test_parse_field_values_fills_in_missing_fields():
    fields = mapping_fields(Action.WRITE, FunctionalDomain.CONTROL, 1)

    data = parse_field_values(["mode=3", "cool_setpoint=24.5"], fields)

    assert data == {
        "mode": 3,
        "fan_mode": 0,
        "heat_setpoint": 0,
        "cool_setpoint": 24.5,
    }


def test_parse_field_values_rejects_unknown_field():
    fields = mapping_fields(Action.WRITE, FunctionalDomain.CONTROL, 1)

    with pytest.raises(ValueError, match="'nope' is not a field"):
        parse_field_values(["nope=1"], fields)


def test_parse_field_values_rejects_non_pair():
    fields = mapping_fields(Action.WRITE, FunctionalDomain.CONTROL, 1)

    with pytest.raises(ValueError, match="is not a name=value pair"):
        parse_field_values(["mode"], fields)


def test_build_packet_from_fields():
    packet = build_packet(
        Action.WRITE, FunctionalDomain.CONTROL, 1, ["mode=3", "cool_setpoint=24.5"]
    )

    assert packet.data[Attribute.MODE] == 3
    assert packet.serialize()[4:7] == bytes([Action.WRITE, FunctionalDomain.CONTROL, 1])


def test_build_packet_from_payload():
    packet = build_packet(Action.WRITE, FunctionalDomain.CONTROL, 99, ["01 02"])

    assert packet.raw_data == [1, 2]
    assert packet.serialize().endswith(bytes([1, 2, packet.serialize()[-1]]))


def test_build_packet_without_payload():
    packet = build_packet(Action.READ_REQUEST, FunctionalDomain.SENSORS, 2)

    assert packet.raw_data is None
    assert packet.data == {}


def test_build_packet_requires_payload_for_unknown_write():
    with pytest.raises(ValueError, match="has no known fields"):
        build_packet(Action.WRITE, FunctionalDomain.CONTROL, 99)


def test_build_packet_rejects_fields_for_unknown_packet():
    with pytest.raises(ValueError, match="has no known fields"):
        build_packet(Action.WRITE, FunctionalDomain.CONTROL, 99, ["mode=1"])


def test_parse_enum():
    assert parse_enum(Action, "write") is Action.WRITE
    assert parse_enum(Action, "1") is Action.WRITE
    assert parse_enum(FunctionalDomain, "0x02") is FunctionalDomain.CONTROL


def test_parse_enum_rejects_unknown():
    with pytest.raises(ValueError, match="expected one of"):
        parse_enum(Action, "nope")


def test_describe_packet_fields():
    assert "mode (INTEGER_REQUIRED)" in describe_packet_fields(
        Action.WRITE, FunctionalDomain.CONTROL, 1
    )


def test_describe_packet_fields_unknown():
    description = describe_packet_fields(Action.WRITE, FunctionalDomain.CONTROL, 99)

    assert "No known fields" in description
    assert "Known attributes: 1, 3, 4, 5, 6, 7" in description


def test_describe_packet_fields_without_payload():
    description = describe_packet_fields(
        Action.READ_REQUEST, FunctionalDomain.CONTROL, 99
    )

    assert "READ_REQUEST has no payload" in description
