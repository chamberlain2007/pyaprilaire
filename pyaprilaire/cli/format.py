"""Formatting of raw bytes for display"""

from __future__ import annotations


def format_hex(data: bytes) -> str:
    """Format bytes as space separated hex"""
    return bytes(data).hex(" ") if data else ""


def format_decimal(data: bytes) -> str:
    """Format bytes as space separated decimal values"""
    return " ".join(str(value) for value in data)


def hexdump(data: bytes, width: int = 16) -> list[str]:
    """Format bytes as offset, hex and ASCII lines"""

    lines: list[str] = []

    for offset in range(0, len(data), width):
        chunk = data[offset : offset + width]

        hex_part = chunk.hex(" ").ljust(width * 3 - 1)
        ascii_part = "".join(
            chr(value) if 32 <= value < 127 else "." for value in chunk
        )

        lines.append(f"{offset:04x}  {hex_part}  |{ascii_part}|")

    return lines
