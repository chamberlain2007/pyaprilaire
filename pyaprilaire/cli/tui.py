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
    Static,
)

from ..const import Action, FunctionalDomain
from .commands import (
    ClientCommand,
    build_field_packet,
    build_packet,
    has_payload,
    known_attributes,
    mapping_fields,
    parse_hex_bytes,
)
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
  enter   Choose one of the three ways to send something
  f       Run one of the functions exposed by the client
  p       Build a packet from an action, functional domain, attribute and data
  x       Write raw hex bytes exactly as entered, with an optional CRC
  r       Repeat the last thing that was sent

[b]Session[/b]
  k       Connect or disconnect
  s       Show or hide the device state
  d       Show or hide hex dumps and full payloads
  c       Clear the log
  w       Write the log to a file
  q       Quit

Every list can be narrowed by typing, and escape goes back without sending
anything.

Every message is shown as the bytes that were on the wire and as the values
decoded from them. A frame that can't be decoded still shows its header, its
payload and whether its CRC is valid.
""".strip()

FUNCTION = "function"
PACKET = "packet"
RAW = "raw"

SEND_OPTIONS = [
    ("Client function  -  run one of the functions exposed by the client", FUNCTION),
    ("Packet  -  choose an action, functional domain, attribute and data", PACKET),
    ("Raw hex  -  write bytes exactly as entered", RAW),
]

# Chosen in place of an attribute when the wanted one isn't a known attribute
OTHER_ATTRIBUTE = object()


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
    """A dialog of text fields"""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self,
        title: str,
        fields: list[tuple[str, str]],
        description: str = "",
    ) -> None:
        super().__init__()

        self.title_text = title
        self.fields = fields
        self.description = description

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.title_text, id="dialog-title")

            if self.description:
                yield Static(self.description, classes="description")

            with VerticalScroll(id="fields"):
                for index, (label, placeholder) in enumerate(self.fields):
                    yield Label(label)
                    yield Input(placeholder=placeholder, id=f"field-{index}")

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

        self.dismiss({"values": values})

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


class RawScreen(ModalScreen[Any]):
    """A dialog for writing raw bytes, entered as hex

    The bytes are checked as they are typed, as they are written to the
    device exactly as they are entered and so can't be corrected afterwards.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self) -> None:
        super().__init__()

        # The bytes that were entered, or None while what has been entered
        # isn't a valid sequence of them, along with what to say about it
        self.data = None
        self.hint = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Send raw bytes", id="dialog-title")
            yield Static(
                "The bytes are written exactly as entered, so the sequence"
                " number and CRC are not corrected.",
                classes="description",
            )

            yield Label("Bytes as hex")
            yield Input(placeholder="01 02 00 03 02 05 02 c9", id="bytes")
            yield Static("", id="bytes-hint", classes="description")

            yield Checkbox("Append a calculated CRC", id="checkbox")

            with Horizontal(id="buttons"):
                yield Button("Send", variant="primary", id="submit")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#bytes", Input).focus()
        self._check()

    def _check(self) -> None:
        """Check what has been entered so far"""

        text = self.query_one("#bytes", Input).value

        if not text.strip():
            self.data = None
            self.hint = "Pairs of hex digits, with or without spaces"
        else:
            try:
                self.data = parse_hex_bytes(text)
            except ValueError as exc:
                self.data = None
                self.hint = str(exc)
            else:
                self.hint = f"{len(self.data)} byte(s)"

        self.query_one("#bytes-hint", Static).update(self.hint)
        self.query_one("#submit", Button).disabled = self.data is None

    def on_input_changed(self) -> None:
        """Check the bytes as they are typed"""
        self._check()

    def _submit(self) -> None:
        """Close, returning the bytes to write"""

        if self.data is None:
            return

        self.dismiss(
            {
                "data": self.data,
                "checked": self.query_one("#checkbox", Checkbox).value,
            }
        )

    def on_input_submitted(self) -> None:
        """Send the bytes when enter is pressed"""
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Send the bytes, or close without sending them"""

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
        Binding("enter", "send", "Send"),
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

    async def _send(self, run) -> None:
        """Send something, and remember it so that it can be repeated"""

        self.repeat_action = run

        try:
            await run()
        except SessionError as exc:
            self._report(exc)

    def action_send(self) -> None:
        """Choose one of the ways of sending something"""
        self._choose_what_to_send()

    @work
    async def _choose_what_to_send(self) -> None:
        """Choose one of the ways of sending something and follow it through"""

        choice = await self.push_screen_wait(
            SelectionScreen("What would you like to send?", SEND_OPTIONS)
        )

        if choice == FUNCTION:
            await self._function_flow()
        elif choice == PACKET:
            await self._packet_flow()
        elif choice == RAW:
            await self._raw_flow()

    def action_functions(self) -> None:
        """Run one of the functions exposed by the client"""
        self._choose_function()

    @work
    async def _choose_function(self) -> None:
        """Choose a client function and run it"""
        await self._function_flow()

    async def _function_flow(self) -> None:
        """Choose a client function, prompt for its parameters and run it"""

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

        await self._send(run)

    def action_packet(self) -> None:
        """Build and send a packet"""
        self._build_packet()

    @work
    async def _build_packet(self) -> None:
        """Build a packet and send it"""
        await self._packet_flow()

    async def _packet_flow(self) -> None:
        """Choose each part of a packet in turn and send it"""

        action = await self.push_screen_wait(
            SelectionScreen(
                "Choose an action",
                [(f"{member.name}  -  {int(member)}", member) for member in Action],
            )
        )

        if action is None:
            return

        functional_domain = await self.push_screen_wait(
            SelectionScreen(
                "Choose a functional domain",
                [
                    (f"{member.name}  -  {int(member)}", member)
                    for member in FunctionalDomain
                ],
            )
        )

        if functional_domain is None:
            return

        attribute = await self._choose_attribute(action, functional_domain)

        if attribute is None:
            return

        try:
            packet = await self._packet_data(action, functional_domain, attribute)
        except ValueError as exc:
            self._report(exc)
            return

        if packet is None:
            return

        async def run() -> None:
            await self.session.send_packet(packet)

        await self._send(run)

    async def _choose_attribute(
        self, action: Action, functional_domain: FunctionalDomain
    ) -> int:
        """Choose the attribute of a packet, from those known or by number"""

        options = [
            (self._attribute_label(action, functional_domain, attribute), attribute)
            for attribute in known_attributes(action, functional_domain)
        ]

        if options:
            options.append(("Another attribute...", OTHER_ATTRIBUTE))

            attribute = await self.push_screen_wait(
                SelectionScreen("Choose an attribute", options)
            )

            if attribute is not OTHER_ATTRIBUTE:
                return attribute

        result = await self.push_screen_wait(
            FormScreen(
                f"{action.name} {functional_domain.name}",
                [("Attribute", "1")],
                description=(
                    "No attributes are known for this action and functional"
                    " domain, so enter the number of one."
                    if not options
                    else "The number of the attribute to send."
                ),
            )
        )

        if not result:
            return None

        text = result["values"][0].strip()

        try:
            return int(text, 0)
        except ValueError:
            self.session.log(ERROR, f"'{text}' is not a valid attribute")
            return None

    def _attribute_label(
        self, action: Action, functional_domain: FunctionalDomain, attribute: int
    ) -> str:
        """Describe an attribute by the fields it carries"""

        names = ", ".join(
            mapping_field.name
            for mapping_field in mapping_fields(action, functional_domain, attribute)
        )

        return f"{attribute}  -  {names}" if names else str(attribute)

    async def _packet_data(
        self, action: Action, functional_domain: FunctionalDomain, attribute: int
    ):
        """Prompt for the data of a packet and build it

        Raises:
            ValueError: the data isn't valid for the packet
        """

        title = f"{action.name} {functional_domain.name} attribute {attribute}"

        # Only the actions that carry a payload have one serialized, so the
        # rest are complete as soon as their attribute is known
        if not has_payload(action):
            return build_packet(action, functional_domain, attribute)

        fields = mapping_fields(action, functional_domain, attribute)

        if fields:
            result = await self.push_screen_wait(
                FormScreen(
                    title,
                    [
                        (f"{mapping_field.name}: {mapping_field.type_name}", "0")
                        for mapping_field in fields
                    ],
                    description="A field that is left blank is sent as zero.",
                )
            )

            if not result:
                return None

            return build_field_packet(
                action,
                functional_domain,
                attribute,
                {
                    mapping_field.name: result["values"][index]
                    for index, mapping_field in enumerate(fields)
                },
            )

        result = await self.push_screen_wait(
            FormScreen(
                title,
                [("Payload as hex", "01 02 0a")],
                description=(
                    f"{action.name} carries a payload, and this packet has no"
                    " known fields, so enter it as hex."
                ),
            )
        )

        if not result:
            return None

        return build_packet(action, functional_domain, attribute, result["values"])

    def action_raw(self) -> None:
        """Write raw bytes to the device"""
        self._send_raw()

    @work
    async def _send_raw(self) -> None:
        """Write raw bytes to the device"""
        await self._raw_flow()

    async def _raw_flow(self) -> None:
        """Prompt for raw bytes and write them to the device"""

        result = await self.push_screen_wait(RawScreen())

        if not result:
            return

        async def run() -> None:
            self.session.send_raw(result["data"], append_crc=result["checked"])

        await self._send(run)

    async def action_quit(self) -> None:
        """Leave the session"""

        await self.session.close()

        self.exit()
