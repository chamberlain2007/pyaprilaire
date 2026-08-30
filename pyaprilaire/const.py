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


class HvacMode(IntEnum):
    """Thermostat operating mode (spec 2.1)."""

    OFF = 1
    HEAT = 2
    COOL = 3
    EMERGENCY_HEAT = 4
    AUTO = 5


class FanMode(IntEnum):
    """Thermostat fan mode (spec 2.1)."""

    ON = 1
    AUTO = 2
    CIRCULATE = 3


class HoldType(IntEnum):
    """Schedule hold type (spec 3.4)."""

    DISABLED = 0
    TEMPORARY = 1
    PERMANENT = 2
    AWAY = 3
    VACATION = 4


class SensorStatus(IntEnum):
    """Sensor status (spec 5.1/5.2)."""

    NO_ERROR = 0
    OUT_OF_RANGE_LOW = 1
    OUT_OF_RANGE_HIGH = 2
    NOT_INSTALLED = 3
    OPEN = 4
    SHORT = 5


class HeatingEquipmentStatus(IntEnum):
    """Heating equipment status (spec 7.6 byte 0)."""

    NOT_ACTIVE = 0
    EQUIPMENT_WAIT = 1
    STAGE_1 = 2
    STAGE_1_AND_2 = 3
    STAGE_1_2_AND_3 = 4
    COMP_1 = 5
    COMP_1_AND_2 = 6
    AUX_HEAT_1 = 7
    AUX_HEAT_2 = 8
    COMP_1_ELEC_HEAT_1 = 9
    COMP_1_ELEC_HEAT_2 = 10
    COMP_1_AND_2_ELEC_HEAT_1 = 11
    COMP_1_AND_2_ELEC_HEAT_2 = 12
    ELEC_HEAT_1 = 13
    ELEC_HEAT_2 = 14


class CoolingEquipmentStatus(IntEnum):
    """Cooling equipment status (spec 7.6 byte 1)."""

    NOT_ACTIVE = 0
    EQUIPMENT_WAIT = 1
    STAGE_1 = 2
    STAGE_1_AND_2 = 3
    STAGE_1_2_AND_3 = 4
    COMP_1 = 5
    COMP_1_AND_2 = 6


class FanStatus(IntEnum):
    """Fan status (spec 7.6 byte 3)."""

    NOT_ACTIVE = 0
    ACTIVE = 1


class DehumidificationStatus(IntEnum):
    """Dehumidification status (spec 7.7 byte 0)."""

    NOT_ACTIVE = 0
    EQUIPMENT_WAIT = 1
    WHOLE_HOME_ACTIVE = 2
    OVERCOOLING_TO_DEHUMIDIFY = 3
    OFF = 4


class HumidificationStatus(IntEnum):
    """Humidification status (spec 7.7 byte 1)."""

    NOT_ACTIVE = 0
    EQUIPMENT_WAIT = 1
    ACTIVE = 2
    OFF = 3


class VentilationStatus(IntEnum):
    """Ventilation status (spec 7.7 byte 2)."""

    NOT_ACTIVE = 0
    EQUIPMENT_WAIT = 1
    ACTIVE = 2
    HIGH_TEMPERATURE_LOCKOUT = 3
    LOW_TEMPERATURE_LOCKOUT = 4
    HIGH_RH_LOCKOUT = 5
    OFF = 6


class AirCleaningStatus(IntEnum):
    """Air cleaning status (spec 7.7 byte 3)."""

    NOT_ACTIVE = 0
    EQUIPMENT_WAIT = 1
    ACTIVE = 2
    OFF = 3


class ThermostatError(IntEnum):
    """Thermostat error code (spec 7.8)."""

    NO_ERROR = 0
    E1_BUILT_IN_TEMP_SENSOR_OPEN = 1
    E2_BUILT_IN_TEMP_SENSOR_SHORT = 2
    E3_NON_VOLATILE_MEMORY_ACCESS_ERROR = 3
    E4_RESERVED = 4
    E5_ECM_COMMUNICATION_LOST = 5
    E6_REMOTE_TEMP_SENSOR_OPEN = 6
    E7_REMOTE_TEMP_SENSOR_SHORT = 7
    E8_SUPPORT_MODULE_TEMP_LOST = 8


class TemperatureScale(IntEnum):
    """Temperature scale (spec 1.3)."""

    FAHRENHEIT = 0
    CELSIUS = 1


class SimpleStatus(StrEnum):
    """Application simple status collapse used by spec 7.6/7.7 (Idle/Wait/On/Off)."""

    IDLE = "idle"
    WAIT = "wait"
    ON = "on"
    OFF = "off"


_HEATING_EQUIPMENT_SIMPLE_STATUS = {
    HeatingEquipmentStatus.NOT_ACTIVE: SimpleStatus.IDLE,
    HeatingEquipmentStatus.EQUIPMENT_WAIT: SimpleStatus.WAIT,
    HeatingEquipmentStatus.STAGE_1: SimpleStatus.ON,
    HeatingEquipmentStatus.STAGE_1_AND_2: SimpleStatus.ON,
    HeatingEquipmentStatus.STAGE_1_2_AND_3: SimpleStatus.ON,
    HeatingEquipmentStatus.COMP_1: SimpleStatus.ON,
    HeatingEquipmentStatus.COMP_1_AND_2: SimpleStatus.ON,
    HeatingEquipmentStatus.AUX_HEAT_1: SimpleStatus.ON,
    HeatingEquipmentStatus.AUX_HEAT_2: SimpleStatus.ON,
    HeatingEquipmentStatus.COMP_1_ELEC_HEAT_1: SimpleStatus.ON,
    HeatingEquipmentStatus.COMP_1_ELEC_HEAT_2: SimpleStatus.ON,
    HeatingEquipmentStatus.COMP_1_AND_2_ELEC_HEAT_1: SimpleStatus.ON,
    HeatingEquipmentStatus.COMP_1_AND_2_ELEC_HEAT_2: SimpleStatus.ON,
    HeatingEquipmentStatus.ELEC_HEAT_1: SimpleStatus.ON,
    HeatingEquipmentStatus.ELEC_HEAT_2: SimpleStatus.ON,
}

_COOLING_EQUIPMENT_SIMPLE_STATUS = {
    CoolingEquipmentStatus.NOT_ACTIVE: SimpleStatus.IDLE,
    CoolingEquipmentStatus.EQUIPMENT_WAIT: SimpleStatus.WAIT,
    CoolingEquipmentStatus.STAGE_1: SimpleStatus.ON,
    CoolingEquipmentStatus.STAGE_1_AND_2: SimpleStatus.ON,
    CoolingEquipmentStatus.STAGE_1_2_AND_3: SimpleStatus.ON,
    CoolingEquipmentStatus.COMP_1: SimpleStatus.ON,
    CoolingEquipmentStatus.COMP_1_AND_2: SimpleStatus.ON,
}

_FAN_SIMPLE_STATUS = {
    FanStatus.NOT_ACTIVE: SimpleStatus.OFF,
    FanStatus.ACTIVE: SimpleStatus.ON,
}

_DEHUMIDIFICATION_SIMPLE_STATUS = {
    DehumidificationStatus.NOT_ACTIVE: SimpleStatus.IDLE,
    DehumidificationStatus.EQUIPMENT_WAIT: SimpleStatus.IDLE,
    DehumidificationStatus.WHOLE_HOME_ACTIVE: SimpleStatus.ON,
    DehumidificationStatus.OVERCOOLING_TO_DEHUMIDIFY: SimpleStatus.ON,
    DehumidificationStatus.OFF: SimpleStatus.OFF,
}

_HUMIDIFICATION_SIMPLE_STATUS = {
    HumidificationStatus.NOT_ACTIVE: SimpleStatus.IDLE,
    HumidificationStatus.EQUIPMENT_WAIT: SimpleStatus.IDLE,
    HumidificationStatus.ACTIVE: SimpleStatus.ON,
    HumidificationStatus.OFF: SimpleStatus.OFF,
}

_VENTILATION_SIMPLE_STATUS = {
    VentilationStatus.NOT_ACTIVE: SimpleStatus.IDLE,
    VentilationStatus.EQUIPMENT_WAIT: SimpleStatus.IDLE,
    VentilationStatus.ACTIVE: SimpleStatus.ON,
    VentilationStatus.HIGH_TEMPERATURE_LOCKOUT: SimpleStatus.IDLE,
    VentilationStatus.LOW_TEMPERATURE_LOCKOUT: SimpleStatus.IDLE,
    VentilationStatus.HIGH_RH_LOCKOUT: SimpleStatus.IDLE,
    VentilationStatus.OFF: SimpleStatus.OFF,
}

_AIR_CLEANING_SIMPLE_STATUS = {
    AirCleaningStatus.NOT_ACTIVE: SimpleStatus.IDLE,
    AirCleaningStatus.EQUIPMENT_WAIT: SimpleStatus.IDLE,
    AirCleaningStatus.ACTIVE: SimpleStatus.ON,
    AirCleaningStatus.OFF: SimpleStatus.OFF,
}

_SIMPLE_STATUS_MAPS: dict[type, dict[int, SimpleStatus]] = {
    HeatingEquipmentStatus: _HEATING_EQUIPMENT_SIMPLE_STATUS,
    CoolingEquipmentStatus: _COOLING_EQUIPMENT_SIMPLE_STATUS,
    FanStatus: _FAN_SIMPLE_STATUS,
    DehumidificationStatus: _DEHUMIDIFICATION_SIMPLE_STATUS,
    HumidificationStatus: _HUMIDIFICATION_SIMPLE_STATUS,
    VentilationStatus: _VENTILATION_SIMPLE_STATUS,
    AirCleaningStatus: _AIR_CLEANING_SIMPLE_STATUS,
}


def get_simple_status(
    status: HeatingEquipmentStatus
    | CoolingEquipmentStatus
    | FanStatus
    | DehumidificationStatus
    | HumidificationStatus
    | VentilationStatus
    | AirCleaningStatus,
) -> SimpleStatus:
    """Collapse a spec 7.6/7.7 equipment/IAQ status value to its application simple
    status (Idle/Wait/On/Off), per the parenthetical in those sections."""
    return _SIMPLE_STATUS_MAPS[type(status)][int(status)]


class NackStatus(IntEnum):
    """Status codes carried by a NACK action, per spec section H.5.

    Spec section G documents the byte at this position in the frame as the
    FUNCTIONAL DOMAIN / STATUS CODE field: for every other action it is a
    functional domain, but for a NACK action it is always one of these
    status codes instead (`NackPacket.status_code` in packet.py is the
    raw, undecoded value of this byte).
    """

    RESERVED_00 = 0x00
    GENERIC_ERROR = 0x01
    RESERVED_02 = 0x02
    BUFFER_FULL_OR_DEVICE_BUSY = 0x03
    UNSUPPORTED_PROTOCOL_REVISION = 0x04
    UNKNOWN_ACTION = 0x05
    UNKNOWN_FUNCTIONAL_DOMAIN = 0x06
    UNKNOWN_ATTRIBUTE = 0x07
    WRITES_NOT_ACCEPTED_IN_CURRENT_APPLICATION_MODE = 0x08
    TIMED_OUT_WAITING_FOR_RESPONSE = 0x09
    UNSUPPORTED_MODEL = 0x0A
    VALUE_OUT_OF_RANGE = 0x10
    ATTRIBUTE_READ_ONLY = 0x11
    ATTRIBUTE_NOT_WRITEABLE_IN_CURRENT_CONFIGURATION = 0x12
    INCORRECT_WRITE_DATA_LENGTH = 0x13
    ATTRIBUTE_NOT_READABLE = 0x20
    ATTRIBUTE_NOT_AVAILABLE_TRY_LATER = 0x21
    INCORRECT_READ_DATA_LENGTH = 0x22
    EXTENDED = 0xFF
