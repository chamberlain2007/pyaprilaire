"""Constants for the Aprilaire integration"""

from __future__ import annotations

from enum import Enum, IntEnum

try:
    from enum import StrEnum
except ImportError:

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
    14: "8840M",
    28: "6003",
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
    OUTDOOR_SENSOR_STATUS = "outdoor_sensor_status"
    OUTDOOR_SENSOR = "outdoor_sensor"

    # Schedule Hold (spec 3.4)
    HOLD_FAN_MODE = "hold_fan_mode"
    HOLD_HEAT_SETPOINT = "hold_heat_setpoint"
    HOLD_COOL_SETPOINT = "hold_cool_setpoint"
    HOLD_DEHUMIDIFICATION_SETPOINT = "hold_dehumidification_setpoint"
    HOLD_END_MINUTE = "hold_end_minute"
    HOLD_END_HOUR = "hold_end_hour"
    HOLD_END_DATE = "hold_end_date"
    HOLD_END_MONTH = "hold_end_month"
    HOLD_END_YEAR = "hold_end_year"

    # Thermostat Installer Settings (spec 1.1)
    TEMPERATURE_SCALE = "temperature_scale"
    CONTROL_SETUP = "control_setup"
    AUTO_CHANGEOVER = "auto_changeover"
    DEADBAND = "deadband"
    WIRED_REMOTE_TEMPERATURE_SENSOR_INSTALLED = (
        "wired_remote_temperature_sensor_installed"
    )
    OUTDOOR_SENSOR_INSTALLED = "outdoor_sensor_installed"
    RETURN_AIR_SENSOR_INSTALLED = "return_air_sensor_installed"
    HEAT_BLAST_AVAILABLE = "heat_blast_available"
    PROGRESSIVE_RECOVERY_AVAILABLE = "progressive_recovery_available"
    PROGRAM_FORMAT = "program_format"

    # MAC Address (spec 8.2)
    FORCE_CONNECTION = "force_connection"
    CONNECTION_TYPE = "connection_type"

    # COS Subscriptions (spec 7.1)
    COS_INSTALLER_THERMOSTAT_SETTINGS = "cos_installer_thermostat_settings"
    COS_CONTRACTOR_INFORMATION = "cos_contractor_information"
    COS_AIR_CLEANING_INSTALLER_SETTINGS = "cos_air_cleaning_installer_settings"
    COS_HUMIDITY_CONTROL_INSTALLER_SETTINGS = "cos_humidity_control_installer_settings"
    COS_FRESH_AIR_INSTALLER_SETTINGS = "cos_fresh_air_installer_settings"
    COS_THERMOSTAT_SETPOINT_AND_MODE_SETTINGS = (
        "cos_thermostat_setpoint_and_mode_settings"
    )
    COS_DEHUMIDIFICATION_SETPOINT = "cos_dehumidification_setpoint"
    COS_HUMIDIFICATION_SETPOINT = "cos_humidification_setpoint"
    COS_FRESH_AIR_SETTING = "cos_fresh_air_setting"
    COS_AIR_CLEANING_SETTINGS = "cos_air_cleaning_settings"
    COS_THERMOSTAT_IAQ_AVAILABLE = "cos_thermostat_iaq_available"
    COS_SCHEDULE_SETTINGS = "cos_schedule_settings"
    COS_AWAY_SETTINGS = "cos_away_settings"
    COS_SCHEDULE_DAY = "cos_schedule_day"
    COS_SCHEDULE_HOLD = "cos_schedule_hold"
    COS_HEAT_BLAST = "cos_heat_blast"
    COS_SERVICE_REMINDERS_STATUS = "cos_service_reminders_status"
    COS_ALERTS_STATUS = "cos_alerts_status"
    COS_ALERTS_SETTINGS = "cos_alerts_settings"
    COS_BACKLIGHT_SETTINGS = "cos_backlight_settings"
    COS_THERMOSTAT_LOCATION_AND_NAME = "cos_thermostat_location_and_name"
    COS_CONTROLLING_SENSOR_VALUES = "cos_controlling_sensor_values"
    COS_OVER_THE_AIR_ODT_UPDATE_TIMEOUT = "cos_over_the_air_odt_update_timeout"
    COS_THERMOSTAT_STATUS = "cos_thermostat_status"
    COS_IAQ_STATUS = "cos_iaq_status"
    COS_MODEL_AND_REVISION = "cos_model_and_revision"
    COS_SUPPORT_MODULE = "cos_support_module"
    COS_LOCKOUTS = "cos_lockouts"
