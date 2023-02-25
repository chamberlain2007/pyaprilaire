# pyaprilaire

pyaprilaire is a library to interact with Aprilaire thermostats.

# Compatibility

aprilaire-ha is generally compatible with Aprilaire [Home Automation](https://www.aprilairepartners.com/technical-information-options/home-automation-technical-information) 8800-series and [Zone Control](https://www.aprilairepartners.com/technical-information-options/zoning-technical-information) 6000-series thermostats. However, due to the number of physical models, it has not been tested on all models.

# Prerequisites

In order to connect to the thermostat, you will need to enable automation mode. This involves going into the Contractor Menu on your thermostat and changing the Connection Type to Automation. Please look up the instructions for your model, as this can vary between models.

# Development

## Mock server

During development, it is necessary to connect to a thermostat, but this can be problematic as a thermostat only allows a single connection at a time. There is a mock server that can be run to expose a local server for development that emulates a thermostat.

```
python -m pyaprilaire.mock_server
```

The port can be specified with `-p PORT_NUMBER`. The default port is 7001.

# Caution regarding device limitations

Due to limitations of the thermostats, only one home automation connection to a device is permitted at one time (the Aprilaire app is not included in this limitation as it uses a separate protocol). Attempting to connecting multiple times to the same thermostat simultaneously can cause various issues, including the thermostat becoming unresponsive and shutting down. If this does occur, power cycling the thermostat should restore functionality.

The socket that is exposed by the thermostat can be unreliable in general. In some cases, it can silently drop the connection or otherwise stop responding. The integration handles this by quietly disconnecting and reconnecting every hour, which generally improves stability. In some cases, however, there may be periods where the change of state (COS) packets aren't received, potentially causing stale data to be shown until the connection is reset. *If this happens to you frequently and you are able to capture the packets at the time via Wireshark showing the state of the socket, this data would be valuable to share.*