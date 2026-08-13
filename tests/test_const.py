import enum
import importlib

import pyaprilaire.const


def test_str_enum_fallback(monkeypatch):
    """Before Python 3.11 there is no enum.StrEnum to import"""

    monkeypatch.delattr(enum, "StrEnum", raising=False)

    try:
        reloaded = importlib.reload(pyaprilaire.const)

        assert issubclass(reloaded.Attribute, str)
        assert reloaded.Attribute.MODE == "mode"
    finally:
        monkeypatch.undo()

        importlib.reload(pyaprilaire.const)
