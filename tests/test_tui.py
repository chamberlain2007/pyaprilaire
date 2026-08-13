import logging
from unittest.mock import AsyncMock, Mock

import pytest

pytest.importorskip("textual", reason="the TUI requires the cli extra")

from textual.widgets import DataTable, Input, OptionList, RichLog, Select  # noqa: E402

from pyaprilaire.cli.session import DebugSession, SessionError  # noqa: E402
from pyaprilaire.cli.tui import (  # noqa: E402
    AprilaireTui,
    FormScreen,
    HelpScreen,
    PacketScreen,
    SelectionScreen,
)

# pylint: disable=wrong-import-position
from pyaprilaire.const import Action, Attribute, FunctionalDomain  # noqa: E402
from pyaprilaire.packet import Packet  # noqa: E402


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

        assert "mode (INTEGER_REQUIRED)" in app.screen.hint

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


async def test_selecting_an_option_from_the_list(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()

        await pilot.press(*"read_control")
        await pilot.pause()

        app.screen.query_one("#options", OptionList).focus()

        await pilot.press("enter")
        await pilot.pause()

        assert session.run_command.await_args.args[0].name == "read_control"


async def test_moving_through_the_options_while_filtering(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()

        options = app.screen.query_one("#options", OptionList)

        await pilot.press("down")
        await pilot.pause()

        assert options.highlighted == 1

        await pilot.press("up")
        await pilot.pause()

        assert options.highlighted == 0


async def test_a_form_can_be_submitted_with_the_button(session):
    app = AprilaireTui(session)
    session.send_raw = Mock()

    async with app.run_test() as pilot:
        await pilot.press("x")
        await pilot.pause()

        app.screen.query_one("#field-0", Input).value = "01 02"

        await pilot.click("#submit")
        await pilot.pause()

        session.send_raw.assert_called_once_with(b"\x01\x02", append_crc=False)


async def test_a_form_can_be_cancelled_with_the_button(session):
    app = AprilaireTui(session)
    session.send_raw = Mock()

    async with app.run_test() as pilot:
        await pilot.press("x")
        await pilot.pause()

        await pilot.click("#cancel")
        await pilot.pause()

        assert session.send_raw.call_count == 0


async def test_a_form_can_be_cancelled_with_escape(session):
    app = AprilaireTui(session)
    session.send_raw = Mock()

    async with app.run_test() as pilot:
        await pilot.press("x")
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert session.send_raw.call_count == 0


async def test_bad_raw_bytes_are_reported(session):
    app = AprilaireTui(session)
    session.send_raw = Mock()

    async with app.run_test() as pilot:
        await pilot.press("x")
        await pilot.pause()

        app.screen.query_one("#field-0", Input).value = "zz"

        app.screen._submit()
        await pilot.pause()

        assert session.send_raw.call_count == 0
        assert "not a valid hex byte" in session.entries[-1].message


async def test_a_failure_to_send_raw_bytes_is_reported(session):
    app = AprilaireTui(session)
    session.send_raw = Mock(side_effect=SessionError("Not connected"))

    async with app.run_test() as pilot:
        await pilot.press("x")
        await pilot.pause()

        app.screen.query_one("#field-0", Input).value = "01 02"

        app.screen._submit()
        await pilot.pause()

        assert session.entries[-1].message == "Not connected"


async def test_the_packet_hint_handles_a_bad_attribute(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()

        app.screen.query_one("#attribute", Input).value = "nope"

        await pilot.pause()

        assert app.screen.hint == "Enter an attribute to see its known fields"


async def test_a_packet_can_be_sent_with_enter(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()

        app.screen.query_one("#attribute", Input).focus()

        await pilot.press("2", "enter")
        await pilot.pause()

        assert session.send_packet.await_args.args[0].attribute == 2


async def test_a_packet_can_be_sent_with_the_button(session):
    app = AprilaireTui(session)

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press("p")
        await pilot.pause()

        app.screen.query_one("#attribute", Input).value = "2"

        await pilot.click("#submit")
        await pilot.pause()

        assert session.send_packet.await_count == 1


async def test_a_packet_can_be_cancelled_with_the_button(session):
    app = AprilaireTui(session)

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press("p")
        await pilot.pause()

        await pilot.click("#cancel")
        await pilot.pause()

        assert session.send_packet.await_count == 0


async def test_a_packet_can_be_cancelled_with_escape(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert session.send_packet.await_count == 0


async def test_a_packet_that_cannot_be_built_is_reported(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()

        app.screen.query_one("#action", Select).value = Action.WRITE
        app.screen.query_one("#attribute", Input).value = "99"

        app.screen._submit()
        await pilot.pause()

        assert session.send_packet.await_count == 0
        assert "has no known fields" in session.entries[-1].message


async def test_a_failure_to_send_a_packet_is_reported(session):
    app = AprilaireTui(session)
    session.send_packet = AsyncMock(side_effect=SessionError("Not connected"))

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()

        app.screen.query_one("#attribute", Input).value = "2"

        app.screen._submit()
        await pilot.pause()

        assert session.entries[-1].message == "Not connected"


async def test_the_help_can_be_closed_with_the_button(session):
    app = AprilaireTui(session)

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press("question_mark")
        await pilot.pause()

        await pilot.click("#cancel")
        await pilot.pause()

        assert not isinstance(app.screen, HelpScreen)


async def test_cancelling_the_parameters_of_a_function(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()

        await pilot.press(*"update_mode")
        await pilot.press("enter")
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert session.run_command.await_count == 0


async def test_a_bad_parameter_is_reported(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()

        await pilot.press(*"update_mode")
        await pilot.press("enter")
        await pilot.pause()

        await pilot.press(*"cool")
        await pilot.press("enter")
        await pilot.pause()

        assert session.run_command.await_count == 0
        assert "mode must be an integer" in session.entries[-1].message


async def test_a_failure_to_run_a_function_is_reported(session):
    app = AprilaireTui(session)
    session.run_command = AsyncMock(side_effect=SessionError("Not connected"))

    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()

        await pilot.press(*"read_control")
        await pilot.press("enter")
        await pilot.pause()

        assert session.entries[-1].message == "Not connected"


async def test_repeating_before_anything_is_sent(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("r")
        await pilot.pause()

        assert session.run_command.await_count == 0


async def test_a_failure_to_repeat_is_reported(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        app.repeat_action = AsyncMock(side_effect=SessionError("Not connected"))

        await pilot.press("r")
        await pilot.pause()

        assert session.entries[-1].message == "Not connected"


async def test_the_state_pane_is_toggled(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        state = app.query_one("#state", DataTable)

        assert not state.has_class("visible")

        await pilot.press("s")
        await pilot.pause()

        assert state.has_class("visible")


async def test_connecting_and_disconnecting(session):
    app = AprilaireTui(session)
    session.disconnect = Mock()

    async with app.run_test() as pilot:
        # Pretend the connection was made, as the session is not connected
        session.client.connected = True
        session.client.protocol = Mock()

        await pilot.press("k")
        await pilot.pause()

        session.disconnect.assert_called_once()

        session.client.connected = False
        session.client.protocol = None

        await pilot.press("k")
        await pilot.pause()

        assert session.connect.await_count == 2


async def test_a_failure_to_disconnect_is_reported(session):
    app = AprilaireTui(session)
    session.disconnect = Mock(side_effect=SessionError("Not connected"))

    async with app.run_test() as pilot:
        session.client.connected = True
        session.client.protocol = Mock()

        await pilot.press("k")
        await pilot.pause()

        assert session.entries[-1].message == "Not connected"


async def test_a_failure_to_connect_is_reported(logger):
    session = DebugSession("localhost", 7001, logger=logger, auto_status=False)
    session.connect = AsyncMock(side_effect=OSError("refused"))

    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.pause()

        assert "Unable to connect: refused" in session.entries[-1].message


async def test_writing_the_log_to_a_file(session, tmp_path, monkeypatch):
    app = AprilaireTui(session)

    monkeypatch.chdir(tmp_path)

    async with app.run_test() as pilot:
        session.log("info", "hello")

        await pilot.press("w")
        await pilot.pause()

        written = list(tmp_path.glob("aprilaire-*.log"))

        assert len(written) == 1
        assert "--- hello" in written[0].read_text()


async def test_a_failure_to_write_the_log_is_reported(session, tmp_path):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        app._log_path = lambda: str(tmp_path / "no-such-directory" / "session.log")

        await pilot.press("w")
        await pilot.pause()

        assert session.entries[-1].kind == "error"


async def test_quitting(session):
    app = AprilaireTui(session)
    session.close = AsyncMock()

    async with app.run_test() as pilot:
        await pilot.press("q")
        await pilot.pause()

        session.close.assert_awaited_once()


async def test_filtering_the_options_to_nothing(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()

        await pilot.press(*"zzzz")
        await pilot.pause()

        assert app.screen.query_one("#options", OptionList).option_count == 0

        # There is nothing to choose, so the list stays open
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, SelectionScreen)
        assert session.run_command.await_count == 0


async def test_a_function_without_a_description(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("f")
        await pilot.pause()

        # set_air_cleaning has no docstring for the dialog to describe
        await pilot.press(*"set_air_cleaning")
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, FormScreen)
        assert not app.screen.query(".description")

        app.screen.query_one("#field-0", Input).value = "1"
        app.screen.query_one("#field-1", Input).value = "2"

        app.screen._submit()
        await pilot.pause()

        assert session.run_command.await_args.args[1] == [1, 2]


async def test_a_form_without_fields(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        app.push_screen(FormScreen("Nothing to fill in", []))

        await pilot.pause()

        assert isinstance(app.screen, FormScreen)

        app.screen._submit()

        await pilot.pause()
