"""Data models for the Aprilaire cloud API (v2 - aprilaire.io) responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DeviceRef:
    """Reference to a device within a room."""

    device_id: str
    access: str
    zone: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceRef:
        return cls(
            device_id=data.get("deviceId", ""),
            access=data.get("access", ""),
            zone=int(data.get("zone", 0)),
        )


@dataclass
class Room:
    """A room containing devices."""

    name: str
    devices: list[DeviceRef]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Room:
        return cls(
            name=data.get("name", ""),
            devices=[
                DeviceRef.from_dict(d) for d in data.get("devices", [])
            ],
        )


@dataclass
class Coordinates:
    """Geographic coordinates."""

    latitude: float
    longitude: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Coordinates:
        return cls(
            latitude=float(data.get("latitude", 0)),
            longitude=float(data.get("longitude", 0)),
        )


@dataclass
class Address:
    """Location address."""

    postal_code: str
    climate_zone: str
    coordinates: Coordinates | None
    city: str | None
    state: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Address:
        coords_data = data.get("coordinates")
        return cls(
            postal_code=data.get("postalCode", ""),
            climate_zone=data.get("climateZone", ""),
            coordinates=Coordinates.from_dict(coords_data) if coords_data else None,
            city=data.get("city"),
            state=data.get("state"),
        )


@dataclass
class Location:
    """A location containing rooms and devices."""

    location_id: str
    name: str
    time_zone: str
    address: Address | None
    rooms: list[Room]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Location:
        addr_data = data.get("address")
        return cls(
            location_id=data.get("locationId", ""),
            name=data.get("name", ""),
            time_zone=data.get("timeZone", ""),
            address=Address.from_dict(addr_data) if addr_data else None,
            rooms=[Room.from_dict(r) for r in data.get("rooms", [])],
        )

    @property
    def device_ids(self) -> list[str]:
        return [
            d.device_id
            for room in self.rooms
            for d in room.devices
        ]


@dataclass
class Hierarchy:
    """Top-level hierarchy response."""

    locations: list[Location]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Hierarchy:
        return cls(
            locations=[
                Location.from_dict(loc) for loc in data.get("locations", [])
            ],
        )

    @property
    def device_ids(self) -> list[str]:
        return [
            did
            for loc in self.locations
            for did in loc.device_ids
        ]


@dataclass
class DeviceStatus:
    """Response from GET /{deviceId}/status."""

    device_id: str
    as_of: str
    hardware_rev: str
    firmware_rev: str
    alt_firmware_rev: str
    model: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceStatus:
        return cls(
            device_id=data.get("deviceId", ""),
            as_of=data.get("asOf", ""),
            hardware_rev=data.get("hardwareRev", ""),
            firmware_rev=data.get("firmwareRev", ""),
            alt_firmware_rev=data.get("altFirmwareRev", ""),
            model=data.get("model", ""),
        )


@dataclass
class Alerts:
    """Alert flags from the dehumidifier status."""

    high_temp: bool
    low_hum: bool
    high_hum: bool
    low_temp: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Alerts:
        return cls(
            high_temp=bool(data.get("highTemp", False)),
            low_hum=bool(data.get("lowHum", False)),
            high_hum=bool(data.get("highHum", False)),
            low_temp=bool(data.get("lowTemp", False)),
        )


@dataclass
class FilterService:
    """Filter service status."""

    needs_service: bool
    remaining: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FilterService:
        return cls(
            needs_service=bool(data.get("needsService", False)),
            remaining=int(data.get("remaining", 0)),
        )


@dataclass
class Sensor:
    """A humidity or temperature sensor reading."""

    reading: float
    uid: int
    is_controlling: bool
    sensor_type: str
    is_wireless: bool
    status: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Sensor:
        return cls(
            reading=float(data.get("reading", 0)),
            uid=int(data.get("uid", 0)),
            is_controlling=bool(data.get("isControlling", False)),
            sensor_type=data.get("type", ""),
            is_wireless=bool(data.get("isWireless", False)),
            status=data.get("status", ""),
        )


@dataclass
class DehumidifierStatus:
    """Response from GET /{deviceId}/status/dehumidifier."""

    device_id: str
    as_of: str
    equipment_status: str
    alerts: Alerts
    fan_time_hours: int
    filter_service: FilterService
    hum_sensors: list[Sensor]
    temp_sensors: list[Sensor]
    is_comp_on: bool
    is_dehum_fan_on: bool
    is_hvac_fan_on: bool
    wifi_rssi: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DehumidifierStatus:
        return cls(
            device_id=data.get("deviceId", ""),
            as_of=data.get("asOf", ""),
            equipment_status=data.get("equipmentStatus", ""),
            alerts=Alerts.from_dict(data.get("alerts", {})),
            fan_time_hours=int(data.get("fanTimeHours", 0)),
            filter_service=FilterService.from_dict(data.get("filterService", {})),
            hum_sensors=[Sensor.from_dict(s) for s in data.get("humSensors", [])],
            temp_sensors=[Sensor.from_dict(s) for s in data.get("tempSensors", [])],
            is_comp_on=bool(data.get("isCompOn", False)),
            is_dehum_fan_on=bool(data.get("isDehumFanOn", False)),
            is_hvac_fan_on=bool(data.get("isHvacFanOn", False)),
            wifi_rssi=int(data.get("wifiRSSI", 0)),
        )


@dataclass
class SensorInfo:
    """Sensor info from device settings."""

    uid: int
    display_name: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SensorInfo:
        return cls(
            uid=int(data.get("uid", 0)),
            display_name=data.get("dispName", ""),
        )


@dataclass
class DehumidifierSettings:
    """Dehumidifier settings from GET /{deviceId}/settings."""

    mode: str
    humidity_setpoint: int
    sensors: list[SensorInfo]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DehumidifierSettings:
        return cls(
            mode=data.get("mode", ""),
            humidity_setpoint=int(data.get("humiditySetpoint", 0)),
            sensors=[SensorInfo.from_dict(s) for s in data.get("sensors", [])],
        )


@dataclass
class DeviceSettings:
    """Response from GET /{deviceId}/settings."""

    device_id: str
    as_of: str
    dehumidifier: DehumidifierSettings | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceSettings:
        dehum_data = data.get("dehumidifier")
        return cls(
            device_id=data.get("deviceId", ""),
            as_of=data.get("asOf", ""),
            dehumidifier=(
                DehumidifierSettings.from_dict(dehum_data) if dehum_data else None
            ),
        )
