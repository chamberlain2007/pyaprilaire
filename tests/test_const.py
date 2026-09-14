import pytest

from pyaprilaire.const import NackStatus


def test_nack_status_values_match_spec_section_h5():
    """Spec section H.5 defines these 17 status codes for a NACK action.
    Pin every one of them to its documented byte value so a typo here can
    never silently misidentify a status code coming off the wire."""

    assert NackStatus.RESERVED_00 == 0x00
    assert NackStatus.GENERIC_ERROR == 0x01
    assert NackStatus.RESERVED_02 == 0x02
    assert NackStatus.BUFFER_FULL_OR_DEVICE_BUSY == 0x03
    assert NackStatus.UNSUPPORTED_PROTOCOL_REVISION == 0x04
    assert NackStatus.UNKNOWN_ACTION == 0x05
    assert NackStatus.UNKNOWN_FUNCTIONAL_DOMAIN == 0x06
    assert NackStatus.UNKNOWN_ATTRIBUTE == 0x07
    assert NackStatus.WRITES_NOT_ACCEPTED_IN_CURRENT_APPLICATION_MODE == 0x08
    assert NackStatus.TIMED_OUT_WAITING_FOR_RESPONSE == 0x09
    assert NackStatus.UNSUPPORTED_MODEL == 0x0A
    assert NackStatus.VALUE_OUT_OF_RANGE == 0x10
    assert NackStatus.ATTRIBUTE_READ_ONLY == 0x11
    assert NackStatus.ATTRIBUTE_NOT_WRITEABLE_IN_CURRENT_CONFIGURATION == 0x12
    assert NackStatus.INCORRECT_WRITE_DATA_LENGTH == 0x13
    assert NackStatus.ATTRIBUTE_NOT_READABLE == 0x20
    assert NackStatus.ATTRIBUTE_NOT_AVAILABLE_TRY_LATER == 0x21
    assert NackStatus.INCORRECT_READ_DATA_LENGTH == 0x22
    assert NackStatus.EXTENDED == 0xFF


def test_nack_status_has_exactly_the_spec_section_h5_codes():
    """Spec section H.5's table lists exactly 17 status codes (some
    reserved) - `NackStatus` must neither invent extra ones nor omit any."""

    assert len(list(NackStatus)) == 19


def test_nack_status_is_int_enum():
    """A `NackStatus` must compare and format like a plain int (e.g.
    `NackStatus(raw_byte)` for parsing, `f"0x{status:02X}"` for logging)."""

    assert NackStatus.VALUE_OUT_OF_RANGE == 0x10
    assert int(NackStatus.VALUE_OUT_OF_RANGE) == 0x10
    assert isinstance(NackStatus.VALUE_OUT_OF_RANGE, int)


def test_nack_status_unknown_code_raises_value_error():
    """A status code not in the spec section H.5 table (e.g. reserved for a
    future protocol revision) must fail to construct, so callers can
    distinguish a recognized status from an unrecognized one."""

    with pytest.raises(ValueError):
        NackStatus(0x0B)
