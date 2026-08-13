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

There are three ways to send something to the device:

- **A client function.** The functions exposed by `AprilaireClient`, such as `update_setpoint` or `read_sensors`, are listed with their parameters. Choosing one prompts for the values it needs.
- **A packet.** Choose an action, functional domain and attribute, and provide the data as either `name=value` pairs for a packet whose fields are known, or as the raw payload in hex for one that isn't. The sequence number and CRC are filled in as usual.
- **Raw bytes.** The bytes are written exactly as entered, with nothing added or corrected, so deliberately malformed frames can be sent to see how a device responds. A calculated CRC can optionally be appended.

## Reading messages

Each message, in both directions, is shown as the bytes that were on the wire, the header broken down into its parts, whether the CRC is valid, and the decoded values. A frame that the library can't decode, such as an undocumented attribute, still shows its header and payload, so unknown messages can be explored. `d` toggles hex dumps and full payloads.

Messages are shown as they arrive, and the current state of the device, built up from everything received so far, can be shown alongside them with `s`. Press `?` for the full list of keys.

## Options

| Option | Description |
| --- | --- |
| `--no-tui` | Use the line based interface instead of the full screen one, which also avoids needing Textual |
| `--json` | Write each message as a JSON object on its own line, which implies `--no-tui` so that only JSON is written to stdout |
| `-o`, `--output PATH` | Also write every message to a file, as JSON when `--json` is given and as text otherwise |
| `--no-auto-status` | Don't send the usual startup requests when connecting, so that only the commands you send appear |
| `--reconnect` | Keep reconnecting when the connection is lost or refused |
| `--detail` | Start with hex dumps and full payloads shown |

The line based interface takes the same commands as text, and `help` lists them:

```
python -m pyaprilaire.cli --no-tui --json --output capture.ndjson
```

# Development

## Mock server

During development, it is necessary to connect to a thermostat, but this can be problematic as a thermostat only allows a single connection at a time. There is a mock server that can be run to expose a local server for development that emulates a thermostat.

```
python -m pyaprilaire.mock_server
```

The port can be specified with `-p PORT_NUMBER`. The default port is 7001.

The interactive session can be pointed at the mock server in the same way as at a real device, which is a good way to try it out:

```
python -m pyaprilaire.cli --host localhost
```

# Caution regarding device limitations

Due to limitations of the thermostats, only one home automation connection to a device is permitted at one time (the Aprilaire app is not included in this limitation as it uses a separate protocol). Attempting to connecting multiple times to the same thermostat simultaneously can cause various issues, including the thermostat becoming unresponsive and shutting down. If this does occur, power cycling the thermostat should restore functionality.

The socket that is exposed by the thermostat can be unreliable in general. In some cases, it can silently drop the connection or otherwise stop responding. The integration handles this by quietly disconnecting and reconnecting every hour, which generally improves stability. In some cases, however, there may be periods where the change of state (COS) packets aren't received, potentially causing stale data to be shown until the connection is reset. *If this happens to you frequently and you are able to capture the packets at the time via Wireshark showing the state of the socket, this data would be valuable to share.*