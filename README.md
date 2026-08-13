# pyaprilaire

pyaprilaire is a library to interact with Aprilaire thermostats.

# Compatibility

aprilaire-ha is generally compatible with Aprilaire [Home Automation](https://www.aprilairepartners.com/technical-information-options/home-automation-technical-information) 8800-series and [Zone Control](https://www.aprilairepartners.com/technical-information-options/zoning-technical-information) 6000-series thermostats. However, due to the number of physical models, it has not been tested on all models.

# Prerequisites

In order to connect to the thermostat, you will need to enable automation mode. This involves going into the Contractor Menu on your thermostat and changing the Connection Type to Automation. Please look up the instructions for your model, as this can vary between models.

# Interactive session

An interactive tool is included for talking to a device directly. It connects to a thermostat, sends commands to it, and shows every message in both its raw hex form and its decoded form.

```
pip install pyaprilaire[cli]
python -m pyaprilaire.cli --host 192.168.1.5
```

Installing the package also provides this as the `pyaprilaire` command. The port can be specified with `-p PORT_NUMBER`, and defaults to 7001.

## Sending commands

Pressing enter asks which of the three ways to send something you want, and each of them is also a key of its own. Every list can be narrowed by typing, and escape goes back a step without sending anything.

- **A client function** (`f`). The functions exposed by `AprilaireClient`, such as `update_setpoint` or `read_sensors`, are listed with their parameters. Choosing one prompts for the values it needs.
- **A packet** (`p`). The action, the functional domain and then the attribute are each chosen from a list, where the attributes that are known are shown along with the fields they carry, and any other attribute can be entered by number. A packet whose fields are known is then filled in a field at a time; one whose fields aren't takes its payload as hex; and an action that carries no payload, such as a read request, is sent as soon as its attribute is known. The sequence number and CRC are filled in as usual.
- **Raw bytes** (`x`). The bytes are written exactly as entered, with nothing added or corrected, so deliberately malformed packets can be sent to see how a device responds. A calculated CRC can optionally be appended.

Bytes are entered as pairs of hex digits, with or without spaces between them, so `01 02 0a` and `01020a` are the same three bytes. Anything else is rejected rather than guessed at, and the raw bytes dialog says what is wrong as you type.

## Reading messages

Each message, in both directions, is shown as the bytes that were on the wire, the header broken down into its parts, whether the CRC is valid, and the decoded values. A packet that the library can't act on, such as one for an undocumented attribute or with a bad CRC, still shows its header and payload, so unknown messages can be explored. `d` toggles hex dumps and full payloads.

Messages are shown as they arrive, and the current state of the device, built up from everything received so far, can be shown alongside them with `s`. Press `?` for the full list of keys.

## Options

| Option | Description |
| --- | --- |
| `--no-tui` | Use the line based interface instead of the full screen one, which also avoids needing Textual |
| `--json` | Write each message as a JSON object on its own line, in [newline delimited JSON](https://github.com/ndjson/ndjson-spec) form. Without `--output` these go to stdout, which implies `--no-tui` so that stdout carries nothing else |
| `-o`, `--output PATH` | Also write every message to a file, as newline delimited JSON when `--json` is given and as text otherwise |
| `-i`, `--input PATH` | Run the commands in a file, then carry on interactively. `-` reads them from standard input, which implies `--no-tui` |
| `--test-connection` | Connect, report whether the device answers and exit, with a status of 0 if it did and 1 if it did not |
| `--wait SECONDS` | How long to stay connected after scripted commands run out, so that the responses to them arrive (default: 2) |
| `-f`, `--follow` | Stay connected after scripted commands run out, until interrupted |
| `--no-auto-status` | Don't send the usual startup requests when connecting, so that only the commands you send appear |
| `--reconnect` | Keep reconnecting when the connection is lost or refused |
| `--detail` | Start with hex dumps and full payloads shown |

The full screen interface gives way to the line based one whenever something else needs the terminal: `--no-tui`, JSON on stdout, commands piped in, or `--test-connection`. Capturing to a file and running a script from one both work either way.

```
python -m pyaprilaire.cli --no-tui --json --output capture.ndjson
```

## Testing a connection

To check whether a device is reachable and answering, without starting a session:

```
python -m pyaprilaire.cli --host 192.168.1.5 --test-connection
```

It connects, asks for the MAC address and waits up to five seconds for an answer, then exits with a status of 0 if it got one and 1 if it did not, which is what a script or a health check needs. The exchange is shown, and recorded to `--output` if one is given.

## Scripting

The line based interface takes the same commands as text, and `help` lists them. Those commands can also be read from a file with `--input`, or piped in:

```
echo "update_mode 3" | python -m pyaprilaire.cli --host 192.168.1.5
```

A line starting with `{` is read as a JSON record instead, so a script can be written as newline delimited JSON:

```json
{"command": "update_setpoint", "arguments": [23.5, 19]}
{"packet": {"action": "WRITE", "domain": "CONTROL", "attribute": 1, "data": {"mode": 3}}}
{"raw": "01 02 00 03 02 05 02 c9", "append_crc": false}
{"wait": 2}
```

The records written by `--json` are themselves valid input, so a captured session can be replayed against a device. What was sent is sent again, byte for byte, and what was received is ignored:

```
python -m pyaprilaire.cli --json --output capture.ndjson --input script.ndjson
python -m pyaprilaire.cli --input capture.ndjson
```

Note that a replayed packet carries the sequence number it was captured with, as it is sent exactly as it was recorded.

Responses arrive after the command that caused them, so the session stays open for `--wait` seconds once the commands run out, or until interrupted with `--follow`. A script that ends in `quit` leaves immediately instead. When there is a terminal, `--input` runs the script and then continues interactively, in the full screen interface as well as the line based one.

# Development

## Linting

This project uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting. After installing the `dev` extra (`pip install -e .[dev]`), enable the pre-commit hooks with:

```
pre-commit install
```

This will automatically lint and format staged Python files on each commit. You can also run it manually against the whole repo with `pre-commit run --all-files`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for commit message and pull request conventions, including [Conventional Commits](https://www.conventionalcommits.org/).

## Mock server

During development, it is necessary to connect to a thermostat, but this can be problematic as a thermostat only allows a single connection at a time. There is a mock server that can be run to expose a local server for development that emulates a thermostat.

```
pip install pyaprilaire[mock_server]
python -m pyaprilaire.mock_server
```

The mock server is a subpackage of its own so that anything it needs stays out of the library's dependencies. It only uses the standard library today, so the extra installs nothing beyond the library itself.

The port can be specified with `-p PORT_NUMBER`. The default port is 7001.

The interactive session can be pointed at the mock server in the same way as at a real device, which is a good way to try it out:

```
python -m pyaprilaire.cli --host localhost
```

# Caution regarding device limitations

Due to limitations of the thermostats, only one home automation connection to a device is permitted at one time (the Aprilaire app is not included in this limitation as it uses a separate protocol). Attempting to connecting multiple times to the same thermostat simultaneously can cause various issues, including the thermostat becoming unresponsive and shutting down. If this does occur, power cycling the thermostat should restore functionality.

The socket that is exposed by the thermostat can be unreliable in general. In some cases, it can silently drop the connection or otherwise stop responding. The integration handles this by quietly disconnecting and reconnecting every hour, which generally improves stability. In some cases, however, there may be periods where the change of state (COS) packets aren't received, potentially causing stale data to be shown until the connection is reset. *If this happens to you frequently and you are able to capture the packets at the time via Wireshark showing the state of the socket, this data would be valuable to share.*