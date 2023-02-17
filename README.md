# pyaprilaire

pyaprilaire is a library to interact with Aprilaire thermostats.

# Compatibility

pyaprilaire is compatible with many models of Aprilaire thermostats. It is tested with an Aprilaire 6045m, but it should work with other 6000- and 8000-series thermostats.

# Prerequisites

In order to connect to the thermostat, you will need to enable automation mode. This involves going into the Contractor Menu on your thermostat and changing the Connection Type to Automation. Please look up the instructions for your model, as this can vary between models.

# Development

## Mock server

During development, it is necessary to connect to a thermostat, but this can be problematic as a thermostat only allows a single connection at a time. There is a mock server that can be run to expose a local server for development that emulates a thermostat.

```
python3 -m pyaprilaire.mock_server
```

The port can be specified with `-p PORT_NUMBER`. The default port is 7001.