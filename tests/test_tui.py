import logging
from unittest.mock import AsyncMock, Mock

import pytest

pytest.importorskip("textual", reason="the TUI requires the cli extra")

from textual.widgets import (  # noqa: E402
    Button,
    Checkbox,
    DataTable,
    Input,
    OptionList,
    RichLog,
)

from pyaprilaire.cli.session import DebugSession, SessionError  # noqa: E402
from pyaprilaire.cli.tui import (  # noqa: E402
    AprilaireTui,
    FormScreen,
    HelpScreen,
    RawScreen,
    SelectionScreen,
)
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


async def choose(pilot, *filter_text: str) -> None:
    """Narrow a list of options to the wanted one and choose it"""

    if filter_text:
        await pilot.press(*"".join(filter_text))

    await pilot.press("enter")
    await pilot.pause()


async def test_the_send_menu_offers_the_three_ways_to_send(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, SelectionScreen)

        labels = [label for label, _ in app.screen.options]

        assert len(labels) == 3
        assert labels[0].startswith("Client function")
        assert labels[1].startswith("Packet")
        assert labels[2].startswith("Raw hex")


async def test_the_send_menu_leads_to_a_client_function(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()

        await choose(pilot, "Client function")

        await choose(pilot, "read_control")

        assert session.run_command.await_args.args[0].name == "read_control"


async def test_the_send_menu_leads_to_the_packet_builder(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()

        await choose(pilot, "Packet")

        assert app.screen.title_text == "Choose an action"


async def test_the_send_menu_leads_to_raw_bytes(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()

        await choose(pilot, "Raw hex")

        assert isinstance(app.screen, RawScreen)


async def test_cancelling_the_send_menu(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert session.send_packet.await_count == 0
        assert session.run_command.await_count == 0


async def test_building_a_packet(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()

        assert app.screen.title_text == "Choose an action"
        await choose(pilot, "WRITE")

        assert app.screen.title_text == "Choose a functional domain"
        await choose(pilot, "CONTROL")

        # The attributes that are known for the action and domain are listed
        # with the fields they carry
        assert app.screen.title_text == "Choose an attribute"
        assert app.screen.options[0][0].startswith("1  -  mode, fan_mode")

        await choose(pilot)

        assert isinstance(app.screen, FormScreen)

        app.screen.query_one("#field-0", Input).value = "3"
        app.screen.query_one("#field-2", Input).value = "20"

        app.screen._submit()
        await pilot.pause()

        packet = session.send_packet.await_args.args[0]

        assert packet.attribute == 1
        assert packet.data["mode"] == 3
        assert packet.data["heat_setpoint"] == 20
        # A field that was left blank is still sent, as the packet needs it
        assert packet.data["cool_setpoint"] == 0


async def test_building_a_packet_that_carries_no_payload(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()

        await choose(pilot, "READ_REQUEST")
        await choose(pilot, "SENSORS")

        # A read request is complete once its attribute is known, so it is
        # sent without asking for any data
        await choose(pilot)

        packet = session.send_packet.await_args.args[0]

        assert packet.action == Action.READ_REQUEST
        assert packet.functional_domain == FunctionalDomain.SENSORS
        assert packet.attribute == 1
        assert not packet.data


async def test_building_a_packet_with_a_raw_payload(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()

        await choose(pilot, "WRITE")

        # Nothing is known about the alerts domain, so the attribute is
        # asked for rather than chosen
        await choose(pilot, "ALERTS")

        assert isinstance(app.screen, FormScreen)

        app.screen.query_one("#field-0", Input).value = "2"
        app.screen._submit()
        await pilot.pause()

        app.screen.query_one("#field-0", Input).value = "0a 0b"
        app.screen._submit()
        await pilot.pause()

        packet = session.send_packet.await_args.args[0]

        assert packet.attribute == 2
        assert packet.raw_data == [10, 11]


async def test_choosing_an_attribute_that_is_not_known(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()

        await choose(pilot, "WRITE")
        await choose(pilot, "CONTROL")
        await choose(pilot, "Another")

        assert isinstance(app.screen, FormScreen)

        app.screen.query_one("#field-0", Input).value = "99"
        app.screen._submit()
        await pilot.pause()

        app.screen.query_one("#field-0", Input).value = "01"
        app.screen._submit()
        await pilot.pause()

        packet = session.send_packet.await_args.args[0]

        assert packet.attribute == 99
        assert packet.raw_data == [1]


async def test_building_a_packet_with_a_bad_attribute(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()

        await choose(pilot, "WRITE")
        await choose(pilot, "ALERTS")

        app.screen.query_one("#field-0", Input).value = "nope"
        app.screen._submit()
        await pilot.pause()

        assert session.send_packet.await_count == 0
        assert "not a valid attribute" in session.entries[-1].message


async def test_building_a_packet_with_a_bad_field_value(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()

        await choose(pilot, "WRITE")
        await choose(pilot, "CONTROL")
        await choose(pilot)

        app.screen.query_one("#field-0", Input).value = "cool"
        app.screen._submit()
        await pilot.pause()

        assert session.send_packet.await_count == 0
        assert "mode must be an integer" in session.entries[-1].message


@pytest.mark.parametrize(
    "steps",
    [
        # The action
        [],
        # The functional domain
        ["WRITE"],
        # The attribute, chosen from those that are known
        ["WRITE", "CONTROL"],
        # The attribute, entered because none are known
        ["WRITE", "ALERTS"],
        # The fields of a known packet
        ["WRITE", "CONTROL", ""],
    ],
)
async def test_cancelling_a_step_of_a_packet(session, steps):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()

        for step in steps:
            await choose(pilot, step)

        await pilot.press("escape")
        await pilot.pause()

        assert session.send_packet.await_count == 0


async def test_cancelling_the_payload_of_a_packet(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()

        await choose(pilot, "WRITE")
        await choose(pilot, "ALERTS")

        app.screen.query_one("#field-0", Input).value = "2"
        app.screen._submit()
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert session.send_packet.await_count == 0


async def test_sending_raw_bytes(session):
    app = AprilaireTui(session)
    session.send_raw = Mock()

    async with app.run_test() as pilot:
        await pilot.press("x")
        await pilot.pause()

        assert isinstance(app.screen, RawScreen)

        app.screen.query_one("#bytes", Input).value = "01 02"

        await pilot.pause()

        assert app.screen.hint == "2 byte(s)"

        app.screen._submit()
        await pilot.pause()

        session.send_raw.assert_called_once_with(b"\x01\x02", append_crc=False)


async def test_sending_raw_bytes_with_a_crc(session):
    app = AprilaireTui(session)
    session.send_raw = Mock()

    async with app.run_test() as pilot:
        await pilot.press("x")
        await pilot.pause()

        app.screen.query_one("#bytes", Input).value = "010200030205"
        app.screen.query_one("#checkbox", Checkbox).value = True

        await pilot.pause()

        app.screen._submit()
        await pilot.pause()

        session.send_raw.assert_called_once_with(
            bytes([1, 2, 0, 3, 2, 5]), append_crc=True
        )


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


async def test_raw_bytes_can_be_sent_with_the_button(session):
    app = AprilaireTui(session)
    session.send_raw = Mock()

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press("x")
        await pilot.pause()

        app.screen.query_one("#bytes", Input).value = "01 02"

        await pilot.pause()

        await pilot.click("#submit")
        await pilot.pause()

        session.send_raw.assert_called_once_with(b"\x01\x02", append_crc=False)


async def test_raw_bytes_can_be_sent_with_enter(session):
    app = AprilaireTui(session)
    session.send_raw = Mock()

    async with app.run_test() as pilot:
        await pilot.press("x")
        await pilot.pause()

        await pilot.press(*"0102")
        await pilot.press("enter")
        await pilot.pause()

        session.send_raw.assert_called_once_with(b"\x01\x02", append_crc=False)


async def test_the_raw_dialog_can_be_cancelled_with_the_button(session):
    app = AprilaireTui(session)
    session.send_raw = Mock()

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press("x")
        await pilot.pause()

        await pilot.click("#cancel")
        await pilot.pause()

        assert session.send_raw.call_count == 0


async def test_the_raw_dialog_can_be_cancelled_with_escape(session):
    app = AprilaireTui(session)
    session.send_raw = Mock()

    async with app.run_test() as pilot:
        await pilot.press("x")
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert session.send_raw.call_count == 0


async def test_the_raw_dialog_says_what_it_expects(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("x")
        await pilot.pause()

        assert app.screen.hint == "Pairs of hex digits, with or without spaces"
        assert app.screen.query_one("#submit", Button).disabled


async def test_the_raw_dialog_rejects_anything_but_hex(session):
    app = AprilaireTui(session)
    session.send_raw = Mock()

    async with app.run_test() as pilot:
        await pilot.press("x")
        await pilot.pause()

        await pilot.press(*"0x01")
        await pilot.pause()

        assert app.screen.hint == (
            "'x' is not a hex digit. Enter pairs of hex digits, such as 01 02 0a"
        )
        assert app.screen.query_one("#submit", Button).disabled

        # There is nothing valid to send, so the dialog stays open
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, RawScreen)
        assert session.send_raw.call_count == 0


async def test_the_raw_dialog_rejects_half_a_byte(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("x")
        await pilot.pause()

        await pilot.press(*"010")
        await pilot.pause()

        assert "not a whole number of bytes" in app.screen.hint


async def test_a_failure_to_send_raw_bytes_is_reported(session):
    app = AprilaireTui(session)
    session.send_raw = Mock(side_effect=SessionError("Not connected"))

    async with app.run_test() as pilot:
        await pilot.press("x")
        await pilot.pause()

        app.screen.query_one("#bytes", Input).value = "01 02"

        await pilot.pause()

        app.screen._submit()
        await pilot.pause()

        assert session.entries[-1].message == "Not connected"


async def test_a_form_can_be_submitted_with_the_button(session):
    app = AprilaireTui(session)

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press("f")
        await pilot.pause()

        await choose(pilot, "update_mode")

        assert isinstance(app.screen, FormScreen)

        app.screen.query_one("#field-0", Input).value = "3"

        await pilot.click("#submit")
        await pilot.pause()

        assert session.run_command.await_args.args[1] == [3]


async def test_a_form_can_be_cancelled_with_the_button(session):
    app = AprilaireTui(session)

    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press("f")
        await pilot.pause()

        await choose(pilot, "update_mode")

        await pilot.click("#cancel")
        await pilot.pause()

        assert session.run_command.await_count == 0


async def test_a_form_can_be_submitted_with_enter(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()

        await choose(pilot, "WRITE")
        await choose(pilot, "ALERTS")

        # The attribute is entered rather than chosen, as none are known
        await pilot.press(*"12")
        await pilot.press("enter")
        await pilot.pause()

        await pilot.press(*"0a")
        await pilot.press("enter")
        await pilot.pause()

        assert session.send_packet.await_args.args[0].attribute == 12


async def test_a_packet_that_cannot_be_built_is_reported(session):
    app = AprilaireTui(session)

    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.pause()

        await choose(pilot, "WRITE")
        await choose(pilot, "ALERTS")

        app.screen.query_one("#field-0", Input).value = "99"
        app.screen._submit()
        await pilot.pause()

        # Nothing is known about the packet, so it can't be sent without a
        # payload to send
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

        await choose(pilot, "READ_REQUEST")
        await choose(pilot, "CONTROL")
        await choose(pilot)

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
