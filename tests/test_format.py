from pyaprilaire.cli.format import format_decimal, format_hex, hexdump


def test_format_hex():
    assert format_hex(b"\x01\x0a\xff") == "01 0a ff"
    assert format_hex(b"") == ""


def test_format_decimal():
    assert format_decimal(b"\x01\x0a\xff") == "1 10 255"


def test_hexdump():
    lines = hexdump(bytes(range(20)))

    assert len(lines) == 2
    assert lines[0].startswith("0000  00 01 02")
    assert lines[1].startswith("0010  10 11 12 13")
