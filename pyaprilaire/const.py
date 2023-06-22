"""Constants for the Aprilaire integration"""

from __future__ import annotations

from enum import Enum, IntEnum

try:
    from enum import StrEnum
except:

    class StrEnum(str, Enum):
        pass


class Action(IntEnum):
    """An action for commands"""

    NONE = 0
    WRITE = 1
    READ_REQUEST = 2
    READ_RESPONSE = 3
    COS = 5
    NACK = 6


class FunctionalDomain(IntEnum):
    """A functional domain for commands"""

    NONE = 0
    SETUP = 1
    CONTROL = 2
    SCHEDULING = 3
    ALERTS = 4
    SENSORS = 5
    LOCKOUT = 6
    STATUS = 7
    IDENTIFICATION = 8
    MESSAGING = 9
    DISPLAY = 10
    WEATHER = 13
    FIRMWARE_UPDATE = 14
    DEBUG_COMMANDS = 15
    NACK = 16


# Known model numbers per Aprilaire. Additional models may be discovered.
MODELS = {
    0: "8476W",
    1: "8810",
    2: "8620W",
    3: "8820",
    4: "8910W",
    5: "8830",
    6: "8920W",
    7: "8840",
    28: "6045M",
}

QUEUE_FREQUENCY = 0.5


class Attribute(StrEnum):
    ERROR = "error"
    AVAILABLE = "available"
    CONNECTED = "connected"
    CONNECTING = "connecting"
    RECONNECTING = "reconnecting"
    STOPPED = "stopped"

    AWAY_AVAILABLE = "away_available"
    MODE = "mode"
    FAN_MODE = "fan_mode"
    HEAT_SETPOINT = "heat_setpoint"
    COOL_SETPOINT = "cool_setpoint"
    DEHUMIDIFICATION_SETPOINT = "dehumidification_setpoint"
    HUMIDIFICATION_SETPOINT = "humidification_setpoint"
    FRESH_AIR_MODE = "fresh_air_mode"
    FRESH_AIR_EVENT = "fresh_air_event"
    AIR_CLEANING_MODE = "air_cleaning_mode"
    AIR_CLEANING_EVENT = "air_cleaning_event"
    THERMOSTAT_MODES = "thermostat_modes"
    AIR_CLEANING_AVAILABLE = "air_cleaning_available"
    VENTILATION_AVAILABLE = "ventilation_available"
    DEHUMIDIFICATION_AVAILABLE = "dehumidification_available"
    HUMIDIFICATION_AVAILABLE = "humidification_available"
    HOLD = "hold"
    BUILT_IN_TEMPERATURE_SENSOR_STATUS = "built_in_temperature_sensor_status"
    BUILT_IN_TEMPERATURE_SENSOR_VALUE = "built_in_temperature_sensor_value"
    WIRED_REMOTE_TEMPERATURE_SENSOR_STATUS = "wired_remote_temperature_sensor_status"
    WIRED_REMOTE_TEMPERATURE_SENSOR_VALUE = "wired_remote_temperature_sensor_value"
    WIRED_OUTDOOR_TEMPERATURE_SENSOR_STATUS = "wired_outdoor_temperature_sensor_status"
    WIRED_OUTDOOR_TEMPERATURE_SENSOR_VALUE = "wired_outdoor_temperature_sensor_value"
    BUILT_IN_HUMIDITY_SENSOR_STATUS = "built_in_humidity_sensor_status"
    BUILT_IN_HUMIDITY_SENSOR_VALUE = "built_in_humidity_sensor_value"
    RAT_SENSOR_STATUS = "rat_sensor_status"
    RAT_SENSOR_VALUE = "rat_sensor_value"
    LAT_SENSOR_STATUS = "lat_sensor_status"
    LAT_SENSOR_VALUE = "lat_sensor_value"
    WIRELESS_OUTDOOR_TEMPERATURE_SENSOR_STATUS = (
        "wireless_outdoor_temperature_sensor_status"
    )
    WIRELESS_OUTDOOR_TEMPERATURE_SENSOR_VALUE = (
        "wireless_outdoor_temperature_sensor_value"
    )
    WIRELESS_OUTDOOR_HUMIDITY_SENSOR_STATUS = "wireless_outdoor_humidity_sensor_status"
    WIRELESS_OUTDOOR_HUMIDITY_SENSOR_VALUE = "wireless_outdoor_humidity_sensor_value"
    INDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS = (
        "indoor_temperature_controlling_sensor_status"
    )
    INDOOR_TEMPERATURE_CONTROLLING_SENSOR_VALUE = (
        "indoor_temperature_controlling_sensor_value"
    )
    OUTDOOR_TEMPERATURE_CONTROLLING_SENSOR_STATUS = (
        "outdoor_temperature_controlling_sensor_status"
    )
    OUTDOOR_TEMPERATURE_CONTROLLING_SENSOR_VALUE = (
        "outdoor_temperature_controlling_sensor_value"
    )
    INDOOR_HUMIDITY_CONTROLLING_SENSOR_STATUS = (
        "indoor_humidity_controlling_sensor_status"
    )
    INDOOR_HUMIDITY_CONTROLLING_SENSOR_VALUE = (
        "indoor_humidity_controlling_sensor_value"
    )
    OUTDOOR_HUMIDITY_CONTROLLING_SENSOR_STATUS = (
        "outdoor_humidity_controlling_sensor_status"
    )
    OUTDOOR_HUMIDITY_CONTROLLING_SENSOR_VALUE = (
        "outdoor_humidity_controlling_sensor_value"
    )
    SYNCED = "synced"
    HEATING_EQUIPMENT_STATUS = "heating_equipment_status"
    COOLING_EQUIPMENT_STATUS = "cooling_equipment_status"
    PROGRESSIVE_RECOVERY = "progressive_recovery"
    FAN_STATUS = "fan_status"
    DEHUMIDIFICATION_STATUS = "dehumidification_status"
    HUMIDIFICATION_STATUS = "humidification_status"
    VENTILATION_STATUS = "ventilation_status"
    AIR_CLEANING_STATUS = "air_cleaning_status"
    HARDWARE_REVISION = "hardware_revision"
    FIRMWARE_MAJOR_REVISION = "firmware_major_revision"
    FIRMWARE_MINOR_REVISION = "firmware_minor_revision"
    PROTOCOL_MAJOR_REVISION = "protocol_major_revision"
    MODEL_NUMBER = "model_number"
    GAINSPAN_FIRMWARE_MAJOR_REVISION = "gainspan_firmware_major_revision"
    GAINSPAN_FIRMWARE_MINOR_REVISION = "gainspan_firmware_minor_revision"
    MAC_ADDRESS = "mac_address"
    LOCATION = "location"
    NAME = "name"
