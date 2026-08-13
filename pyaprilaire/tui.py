"""Full screen interactive session with a device

Requires the optional Textual dependency, which is installed with the `cli`
extra: `pip install pyaprilaire[cli]`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    RichLog,
    Select,
    Static,
)

from .commands import (
    ClientCommand,
    build_packet,
    describe_packet_fields,
    parse_hex_bytes,
)
from .const import Action, FunctionalDomain
from .session import (
    ERROR,
    INFO,
    RECEIVED,
    SENT,
    DebugSession,
    LogEntry,
    SessionError,
    format_entry_lines,
)

ENTRY_STYLES = {
    SENT: "cyan",
    RECEIVED: "green",
    ERROR: "bold red",
    INFO: "yellow",
}

HELP_TEXT = """
[b]Sending[/b]
  f   Run one of the functions exposed by the client
  p   Build a packet from an action, functional domain, attribute and data
  x   Write raw hex bytes exactly as entered, with an optional CRC
  r   Repeat the last thing that was sent

[b]Session[/b]
  k   Connect or disconnect
  s   Show or hide the device state
  d   Show or hide hex dumps and full payloads
  c   Clear the log
  w   Write the log to a file
  q   Quit

Every message is shown as the bytes that were on the wire and as the values
decoded from them. A frame that can't be decoded still shows its header, its
payload and whether its CRC is valid.
""".strip()


class SelectionScreen(ModalScreen[Any]):
    """A filterable list of options"""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, options: list[tuple[str, Any]]) -> None:
        super().__init__()

        self.title_text = title
        self.options = options

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.title_text, id="dialog-title")
            yield Input(placeholder="Type to filter", id="filter")
            yield OptionList(id="options")

    def on_mount(self) -> None:
        self._show_options(self.options)
        self.query_one("#filter", Input).focus()

    def _show_options(self, options: list[tuple[str, Any]]) -> None:
        """Show the given options in the list"""

        self.visible_options = options

        option_list = self.query_one("#options", OptionList)
        option_list.clear_options()
        option_list.add_options([label for label, _ in options])

        if options:
            option_list.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter the options as the user types"""

        text = event.value.strip().lower()

        self._show_options(
            [option for option in self.options if text in option[0].lower()]
        )

    def on_input_submitted(self) -> None:
        """Choose the highlighted option"""

        option_list = self.query_one("#options", OptionList)

        if option_list.highlighted is not None and self.visible_options:
            self.dismiss(self.visible_options[option_list.highlighted][1])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Choose the selected option"""
        self.dismiss(self.visible_options[event.option_index][1])

    def on_key(self, event) -> None:
        """Move through the options while the filter has focus"""

        if event.key in ("up", "down") and self.focused and self.focused.id == "filter":
            option_list = self.query_one("#options", OptionList)

            if event.key == "down":
                option_list.action_cursor_down()
            else:
                option_list.action_cursor_up()

            event.stop()

    def action_cancel(self) -> None:
        """Close without choosing an option"""
        self.dismiss(None)


class FormScreen(ModalScreen[Any]):
    """A dialog of text fields, with an optional checkbox"""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self,
        title: str,
        fields: list[tuple[str, str]],
        description: str = "",
        checkbox: str = None,
    ) -> None:
        super().__init__()

        self.title_text = title
        self.fields = fields
        self.description = description
        self.checkbox = checkbox

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.title_text, id="dialog-title")

            if self.description:
                yield Static(self.description, classes="description")

            with VerticalScroll(id="fields"):
                for index, (label, placeholder) in enumerate(self.fields):
                    yield Label(label)
                    yield Input(placeholder=placeholder, id=f"field-{index}")

            if self.checkbox:
                yield Checkbox(self.checkbox, id="checkbox")

            with Horizontal(id="buttons"):
                yield Button("Send", variant="primary", id="submit")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        if self.fields:
            self.query_one("#field-0", Input).focus()

    def _submit(self) -> None:
        """Close, returning the entered values"""

        values = [
            self.query_one(f"#field-{index}", Input).value
            for index in range(len(self.fields))
        ]

        checked = bool(self.checkbox) and self.query_one("#checkbox", Checkbox).value

        self.dismiss({"values": values, "checked": checked})

    def on_input_submitted(self) -> None:
        """Submit the form when enter is pressed in a field"""
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Submit or cancel the form"""

        if event.button.id == "submit":
            self._submit()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        """Close without submitting"""
        self.dismiss(None)


class PacketScreen(ModalScreen[Any]):
    """A dialog for building a packet from its parts"""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self) -> None:
        super().__init__()

        # The description of the currently selected packet, kept so that it
        # can be shown and checked without reading it back out of the widget
        self.hint = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Send a packet", id="dialog-title")

            yield Label("Action")
            yield Select(
                [(action.name, action) for action in Action],
                value=Action.READ_REQUEST,
                allow_blank=False,
                id="action",
            )

            yield Label("Functional domain")
            yield Select(
                [(domain.name, domain) for domain in FunctionalDomain],
                value=FunctionalDomain.CONTROL,
                allow_blank=False,
                id="domain",
            )

            yield Label("Attribute")
            yield Input(placeholder="1", id="attribute")

            yield Static("", id="fields-hint", classes="description")

            yield Label("Data")
            yield Input(
                placeholder="name=value pairs, or the payload as hex",
                id="values",
            )

            with Horizontal(id="buttons"):
                yield Button("Send", variant="primary", id="submit")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#attribute", Input).focus()
        self._update_hint()

    def _update_hint(self) -> None:
        """Describe the fields of the currently selected packet"""

        attribute_text = self.query_one("#attribute", Input).value.strip()

        try:
            attribute = int(attribute_text, 0) if attribute_text else None
        except ValueError:
            attribute = None

        if attribute is None:
            self.hint = "Enter an attribute to see its known fields"
        else:
            self.hint = describe_packet_fields(
                self.query_one("#action", Select).value,
                self.query_one("#domain", Select).value,
                attribute,
            )

        self.query_one("#fields-hint", Static).update(self.hint)

    def on_select_changed(self) -> None:
        """Update the hint when the action or domain changes"""
        self._update_hint()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Update the hint when the attribute changes"""

        if event.input.id == "attribute":
            self._update_hint()

    def _submit(self) -> None:
        """Close, returning the parts of the packet"""

        self.dismiss(
            {
                "action": self.query_one("#action", Select).value,
                "domain": self.query_one("#domain", Select).value,
                "attribute": self.query_one("#attribute", Input).value,
                "values": self.query_one("#values", Input).value,
            }
        )

    def on_input_submitted(self) -> None:
        """Submit the packet when enter is pressed in a field"""
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Submit or cancel the packet"""

        if event.button.id == "submit":
            self._submit()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        """Close without sending"""
        self.dismiss(None)


class HelpScreen(ModalScreen[None]):
    """A dialog describing what the tool can do"""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("pyaprilaire interactive session", id="dialog-title")
            yield Static(HELP_TEXT)

            with Horizontal(id="buttons"):
                yield Button("Close", variant="primary", id="cancel")

    def on_button_pressed(self) -> None:
        """Close the help"""
        self.dismiss(None)

    def action_cancel(self) -> None:
        """Close the help"""
        self.dismiss(None)


class AprilaireTui(App):
    """Full screen interactive session with a device"""

    CSS = """
    #body {
        height: 1fr;
    }

    #log {
        width: 2fr;
        border: round $accent;
        padding: 0 1;
    }

    #state {
        width: 42;
        border: round $accent;
        display: none;
    }

    #state.visible {
        display: block;
    }

    #dialog {
        width: 84;
        max-width: 90%;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        background: $surface;
        border: thick $accent;
    }

    #dialog-title {
        text-style: bold;
        width: 100%;
        padding-bottom: 1;
    }

    #dialog Input, #dialog Select {
        margin-bottom: 1;
    }

    #fields {
        height: auto;
        max-height: 20;
    }

    .description {
        color: $text-muted;
        padding-bottom: 1;
    }

    #buttons {
        height: auto;
        padding-top: 1;
    }

    #buttons Button {
        margin-right: 2;
    }
    """

    BINDINGS = [
        Binding("f", "functions", "Functions"),
        Binding("p", "packet", "Packet"),
        Binding("x", "raw", "Raw hex"),
        Binding("r", "repeat", "Repeat"),
        Binding("k", "toggle_connection", "Connect"),
        Binding("s", "toggle_state", "State"),
        Binding("d", "toggle_detail", "Detail"),
        Binding("c", "clear", "Clear"),
        Binding("w", "write_log", "Save"),
        Binding("question_mark", "help", "Help", key_display="?"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, session: DebugSession, detail: bool = False) -> None:
        super().__init__()

        self.session = session
        self.detail = detail
        self.repeat_action = None

        self.title = "pyaprilaire"

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="body"):
            yield RichLog(id="log", wrap=True, markup=False, auto_scroll=True)
            yield DataTable(id="state", cursor_type="row", zebra_stripes=True)

        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#state", DataTable)
        table.add_columns("Attribute", "Value")

        self.session.add_entry_listener(self._on_entry)
        self.session.add_state_listener(self._on_state)

        self._update_status()
        self.set_interval(1, self._update_status)

        self._connect()

    def _update_status(self) -> None:
        """Keep the connection state in the header up to date"""

        self.sub_title = (
            f"{self.session.host}:{self.session.port} - {self.session.status_text}"
        )

    def _on_entry(self, entry: LogEntry) -> None:
        """Show a new entry in the log"""
        self.query_one("#log", RichLog).write(self._render_entry(entry))

    def _on_state(self, state: dict[str, Any]) -> None:
        """Refresh the device state"""

        table = self.query_one("#state", DataTable)
        table.clear()

        for name in sorted(state):
            table.add_row(name, str(state[name]))

    def _render_entry(self, entry: LogEntry) -> Text:
        """Render an entry as styled text"""

        style = ENTRY_STYLES.get(entry.kind, "")

        text = Text()

        for index, line in enumerate(format_entry_lines(entry, self.detail)):
            if index:
                text.append("\n")

            text.append(line, style=style if index == 0 else f"dim {style}".strip())

        return text

    def _refresh_log(self) -> None:
        """Redraw every entry, for when the level of detail changes"""

        log = self.query_one("#log", RichLog)
        log.clear()

        for entry in self.session.entries:
            log.write(self._render_entry(entry))

    def _report(self, exc: Exception) -> None:
        """Show a failed command in the log"""
        self.session.log(ERROR, str(exc) or repr(exc))

    @work
    async def _connect(self) -> None:
        """Connect to the device"""

        try:
            await self.session.connect()
        except (OSError, SessionError) as exc:
            self.session.log(ERROR, f"Unable to connect: {exc}")

        self._update_status()

    def action_toggle_connection(self) -> None:
        """Connect to or disconnect from the device"""

        if self.session.connected:
            try:
                self.session.disconnect()
            except SessionError as exc:
                self._report(exc)

            self._update_status()
        else:
            self._connect()

    def action_toggle_state(self) -> None:
        """Show or hide the device state"""
        self.query_one("#state", DataTable).toggle_class("visible")

    def action_toggle_detail(self) -> None:
        """Show or hide hex dumps and full payloads"""

        self.detail = not self.detail

        self._refresh_log()
        self.notify(f"Detail {'on' if self.detail else 'off'}")

    def action_clear(self) -> None:
        """Clear the log"""

        self.session.clear()
        self.query_one("#log", RichLog).clear()

    def action_help(self) -> None:
        """Show what the tool can do"""
        self.push_screen(HelpScreen())

    def _log_path(self) -> str:
        """Where to write the log to"""
        return f"aprilaire-{datetime.now():%Y%m%d-%H%M%S}.log"

    def action_write_log(self) -> None:
        """Write the log to a file"""

        path = self._log_path()

        try:
            with open(path, "w", encoding="utf-8") as log_file:
                for entry in self.session.entries:
                    for line in format_entry_lines(entry, self.detail):
                        log_file.write(f"{line}\n")
        except OSError as exc:
            self._report(exc)
            return

        self.notify(f"Wrote {path}")

    def action_repeat(self) -> None:
        """Send the last thing that was sent again"""

        if not self.repeat_action:
            self.notify("Nothing has been sent yet")
            return

        self._repeat()

    @work
    async def _repeat(self) -> None:
        """Run the stored repeat action"""

        try:
            await self.repeat_action()
        except (SessionError, ValueError) as exc:
            self._report(exc)

    def action_functions(self) -> None:
        """Run one of the functions exposed by the client"""
        self._choose_function()

    @work
    async def _choose_function(self) -> None:
        """Choose a client function and prompt for its parameters"""

        options = [
            (
                f"{command.signature}"
                + (f"  -  {command.description}" if command.description else ""),
                command,
            )
            for command in self.session.commands
        ]

        command: ClientCommand = await self.push_screen_wait(
            SelectionScreen("Run a client function", options)
        )

        if not command:
            return

        arguments: list[Any] = []

        if command.parameters:
            result = await self.push_screen_wait(
                FormScreen(
                    command.signature,
                    [
                        (parameter.display, parameter.type_name)
                        for parameter in command.parameters
                    ],
                    description=command.description,
                )
            )

            if not result:
                return

            try:
                arguments = command.parse_arguments(result["values"])
            except ValueError as exc:
                self._report(exc)
                return

        async def run() -> None:
            await self.session.run_command(command, arguments)

        self.repeat_action = run

        try:
            await run()
        except SessionError as exc:
            self._report(exc)

    def action_packet(self) -> None:
        """Build and send a packet"""
        self._build_packet()

    @work
    async def _build_packet(self) -> None:
        """Prompt for the parts of a packet and send it"""

        result = await self.push_screen_wait(PacketScreen())

        if not result:
            return

        try:
            attribute = int(result["attribute"].strip() or "0", 0)
        except ValueError:
            self.session.log(ERROR, f"'{result['attribute']}' is not a valid attribute")
            return

        try:
            packet = build_packet(
                result["action"],
                result["domain"],
                attribute,
                result["values"].split(),
            )
        except ValueError as exc:
            self._report(exc)
            return

        async def run() -> None:
            await self.session.send_packet(packet)

        self.repeat_action = run

        try:
            await run()
        except SessionError as exc:
            self._report(exc)

    def action_raw(self) -> None:
        """Write raw bytes to the device"""
        self._send_raw()

    @work
    async def _send_raw(self) -> None:
        """Prompt for raw bytes and write them to the device"""

        result = await self.push_screen_wait(
            FormScreen(
                "Send raw bytes",
                [("Bytes", "01 02 00 03 02 05 02 c9")],
                description=(
                    "The bytes are written exactly as entered, so the sequence"
                    " number and CRC are not corrected."
                ),
                checkbox="Append a calculated CRC",
            )
        )

        if not result:
            return

        try:
            data = parse_hex_bytes(result["values"][0])
        except ValueError as exc:
            self._report(exc)
            return

        async def run() -> None:
            self.session.send_raw(data, append_crc=result["checked"])

        self.repeat_action = run

        try:
            await run()
        except SessionError as exc:
            self._report(exc)

    async def action_quit(self) -> None:
        """Leave the session"""

        await self.session.close()

        self.exit()
