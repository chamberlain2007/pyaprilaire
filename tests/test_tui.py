import logging
from unittest.mock import AsyncMock, Mock

import pytest

pytest.importorskip("textual", reason="the TUI requires the cli extra")

from textual.widgets import DataTable, Input, RichLog  # noqa: E402

# pylint: disable=wrong-import-position
from pyaprilaire.const import Action, Attribute, FunctionalDomain  # noqa: E402
from pyaprilaire.packet import Packet  # noqa: E402
from pyaprilaire.session import DebugSession  # noqa: E402
from pyaprilaire.tui import (  # noqa: E402
    AprilaireTui,
    FormScreen,
    HelpScreen,
    PacketScreen,
    SelectionScreen,
)


@pytest.fixture
def logger():
    logger = logging.getLogger("pyaprilaire.test_tui")
    logger.propagate = False

    return logger


@pytest.fixture
def session(event_loop, logger):
    session = DebugSession("localhost", 7001, logger=logger, auto_status=False)

    # The interface is tested without a device, so nothing is sent
    session.connect = AsyncMock()
    session.run_command = AsyncMock()
    session.send_packet = AsyncMock()

    return session


async def test_entries_are_shown(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        session.record_received(
            Packet(
                Action.READ_RESPONSE,
                FunctionalDomain.SCHEDULING,
                4,
                data={Attribute.HOLD: 1},
            ).serialize()
        )

        await pilot.pause()

        lines = app.query_one("#log", RichLog).lines
        text = "\n".join(line.text for line in lines)

        assert "READ_RESPONSE SCHEDULING attribute 4" in text
        assert "hold = 1" in text
        assert "crc=" in text


async def test_state_is_shown(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        session._data_received({Attribute.MODE: 3})

        await pilot.pause()

        assert app.query_one("#state", DataTable).row_count == 1


async def test_detail_redraws_the_log(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        session.record_sent(
            Packet(Action.READ_REQUEST, FunctionalDomain.CONTROL, 1).serialize()
        )

        await pilot.press("d")
        await pilot.pause()

        lines = app.query_one("#log", RichLog).lines

        assert any("0000  01" in line.text for line in lines)


async def test_clearing_the_log(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        session.log("info", "hello")

        await pilot.press("c")
        await pilot.pause()

        assert not session.entries
        assert not app.query_one("#log", RichLog).lines


async def test_help_opens_and_closes(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("question_mark")
        await pilot.pause()

        assert isinstance(app.screen, HelpScreen)

        await pilot.press("escape")
        await pilot.pause()

        assert not isinstance(app.screen, HelpScreen)


async def test_choosing_a_function_prompts_for_its_parameters(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()

        assert isinstance(app.screen, SelectionScreen)

        await pilot.press(*"update_mode")
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, FormScreen)

        await pilot.press("3")
        await pilot.press("enter")
        await pilot.pause()

        command, arguments = session.run_command.await_args.args

        assert command.name == "update_mode"
        assert arguments == [3]


async def test_running_a_function_without_parameters(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()

        await pilot.press(*"read_control")
        await pilot.press("enter")
        await pilot.pause()

        assert session.run_command.await_args.args[0].name == "read_control"


async def test_cancelling_the_function_list(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert session.run_command.await_count == 0


async def test_building_a_packet(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()

        assert isinstance(app.screen, PacketScreen)

        app.screen.query_one("#attribute", Input).value = "1"
        app.screen.query_one("#values", Input).value = "mode=3"

        await pilot.pause()

        assert "mode (INTEGER_REQUIRED)" in str(
            app.screen.query_one("#fields-hint").content
        )

        app.screen._submit()
        await pilot.pause()

        packet = session.send_packet.await_args.args[0]

        assert packet.attribute == 1
        assert packet.data[Attribute.MODE] == 3


async def test_building_a_packet_with_a_bad_attribute(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()

        app.screen.query_one("#attribute", Input).value = "nope"

        app.screen._submit()
        await pilot.pause()

        assert session.send_packet.await_count == 0
        assert "not a valid attribute" in session.entries[-1].message


async def test_sending_raw_bytes(session):
    app = AprilaireTui(session)
    session.send_raw = Mock()

    async with app.run_test() as pilot:
        await pilot.press("x")
        await pilot.pause()

        assert isinstance(app.screen, FormScreen)

        app.screen.query_one("#field-0", Input).value = "01 02"

        app.screen._submit()
        await pilot.pause()

        session.send_raw.assert_called_once_with(b"\x01\x02", append_crc=False)


async def test_repeating_the_last_command(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()

        await pilot.press(*"read_control")
        await pilot.press("enter")
        await pilot.pause()

        await pilot.press("r")
        await pilot.pause()

        assert session.run_command.await_count == 2
