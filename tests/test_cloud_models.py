"""Tests for cloud API v2 response models."""

from __future__ import annotations

from pyaprilaire.cloud_models import (
    Address,
    Alerts,
    Coordinates,
    DehumidifierSettings,
    DehumidifierStatus,
    DeviceRef,
    DeviceSettings,
    DeviceStatus,
    FilterService,
    Hierarchy,
    Location,
    Room,
    Sensor,
    SensorInfo,
)


# --- DeviceRef ---


def test_device_ref_from_dict():
    data = {"deviceId": "BC8D7EECB7D1", "access": "manage", "zone": 1}
    ref = DeviceRef.from_dict(data)
    assert ref.device_id == "BC8D7EECB7D1"
    assert ref.access == "manage"
    assert ref.zone == 1


def test_device_ref_defaults():
    ref = DeviceRef.from_dict({})
    assert ref.device_id == ""
    assert ref.access == ""
    assert ref.zone == 0


# --- Room ---


def test_room_from_dict():
    data = {
        "name": "Whole Home",
        "devices": [
            {"deviceId": "ABC123", "access": "manage", "zone": 1},
        ],
    }
    room = Room.from_dict(data)
    assert room.name == "Whole Home"
    assert len(room.devices) == 1
    assert room.devices[0].device_id == "ABC123"


def test_room_no_devices():
    room = Room.from_dict({"name": "Empty"})
    assert room.devices == []


# --- Coordinates / Address ---


def test_coordinates_from_dict():
    coords = Coordinates.from_dict({"latitude": 37.88, "longitude": -122.45})
    assert coords.latitude == 37.88
    assert coords.longitude == -122.45


def test_address_from_dict():
    data = {
        "postalCode": "94920",
        "climateZone": "Marine",
        "coordinates": {"latitude": 37.88, "longitude": -122.45},
        "city": None,
        "state": None,
    }
    addr = Address.from_dict(data)
    assert addr.postal_code == "94920"
    assert addr.climate_zone == "Marine"
    assert addr.coordinates is not None
    assert addr.city is None


def test_address_no_coordinates():
    addr = Address.from_dict({"postalCode": "12345"})
    assert addr.coordinates is None


# --- Location ---


def test_location_from_dict():
    data = {
        "locationId": "loc-1",
        "name": "Home",
        "timeZone": "America/Los_Angeles",
        "rooms": [
            {
                "name": "Whole Home",
                "devices": [{"deviceId": "DEV1", "access": "manage", "zone": 1}],
            }
        ],
    }
    loc = Location.from_dict(data)
    assert loc.location_id == "loc-1"
    assert loc.name == "Home"
    assert loc.time_zone == "America/Los_Angeles"
    assert loc.device_ids == ["DEV1"]


def test_location_defaults():
    loc = Location.from_dict({})
    assert loc.location_id == ""
    assert loc.rooms == []
    assert loc.device_ids == []
    assert loc.address is None


# --- Hierarchy ---


def _hierarchy_data():
    return {
        "locations": [
            {
                "locationId": "loc-1",
                "name": "Home",
                "timeZone": "America/Los_Angeles",
                "rooms": [
                    {
                        "name": "Whole Home",
                        "devices": [
                            {"deviceId": "BC8D7EECB7D1", "access": "manage", "zone": 1}
                        ],
                    }
                ],
            }
        ]
    }


def test_hierarchy_from_dict():
    h = Hierarchy.from_dict(_hierarchy_data())
    assert len(h.locations) == 1
    assert h.device_ids == ["BC8D7EECB7D1"]


def test_hierarchy_empty():
    h = Hierarchy.from_dict({})
    assert h.locations == []
    assert h.device_ids == []


def test_hierarchy_multiple_locations():
    data = {
        "locations": [
            {
                "locationId": "loc-1",
                "name": "Home",
                "timeZone": "US/Eastern",
                "rooms": [
                    {
                        "name": "Room A",
                        "devices": [{"deviceId": "DEV1", "access": "manage", "zone": 1}],
                    }
                ],
            },
            {
                "locationId": "loc-2",
                "name": "Office",
                "timeZone": "US/Pacific",
                "rooms": [
                    {
                        "name": "Room B",
                        "devices": [{"deviceId": "DEV2", "access": "view", "zone": 2}],
                    }
                ],
            },
        ]
    }
    h = Hierarchy.from_dict(data)
    assert h.device_ids == ["DEV1", "DEV2"]


# --- DeviceStatus ---


def test_device_status_from_dict():
    data = {
        "deviceId": "BC8D7EECB7D1",
        "asOf": "2026-05-25T17:44:35.171Z",
        "hardwareRev": "D",
        "firmwareRev": "1.1.3",
        "altFirmwareRev": "1.9.0",
        "model": "E080W",
    }
    status = DeviceStatus.from_dict(data)
    assert status.device_id == "BC8D7EECB7D1"
    assert status.model == "E080W"
    assert status.firmware_rev == "1.1.3"
    assert status.hardware_rev == "D"


def test_device_status_defaults():
    status = DeviceStatus.from_dict({})
    assert status.device_id == ""
    assert status.model == ""


# --- Alerts / FilterService / Sensor ---


def test_alerts_from_dict():
    alerts = Alerts.from_dict(
        {"highTemp": True, "lowHum": False, "highHum": True, "lowTemp": False}
    )
    assert alerts.high_temp is True
    assert alerts.low_hum is False
    assert alerts.high_hum is True
    assert alerts.low_temp is False


def test_alerts_defaults():
    alerts = Alerts.from_dict({})
    assert alerts.high_temp is False
    assert alerts.low_temp is False


def test_filter_service_from_dict():
    fs = FilterService.from_dict({"needsService": True, "remaining": 42})
    assert fs.needs_service is True
    assert fs.remaining == 42


def test_sensor_from_dict():
    data = {
        "reading": 47,
        "uid": 1,
        "isControlling": True,
        "type": "inlet-air",
        "isWireless": False,
        "status": "reporting",
    }
    s = Sensor.from_dict(data)
    assert s.reading == 47.0
    assert s.uid == 1
    assert s.is_controlling is True
    assert s.sensor_type == "inlet-air"
    assert s.is_wireless is False
    assert s.status == "reporting"


# --- DehumidifierStatus ---


def _dehum_status_data():
    return {
        "deviceId": "BC8D7EECB7D1",
        "asOf": "2026-05-25T20:27:36.650Z",
        "equipmentStatus": "inactive",
        "alerts": {"highTemp": False, "lowHum": False, "highHum": False, "lowTemp": False},
        "fanTimeHours": 0,
        "filterService": {"needsService": False, "remaining": 100},
        "humSensors": [
            {
                "reading": 47,
                "uid": 1,
                "isControlling": True,
                "type": "inlet-air",
                "isWireless": False,
                "status": "reporting",
            }
        ],
        "isCompOn": False,
        "isDehumFanOn": False,
        "isHvacFanOn": False,
        "tempSensors": [
            {
                "reading": 20.78,
                "uid": 1,
                "isControlling": True,
                "type": "inlet-air",
                "isWireless": False,
                "status": "reporting",
            },
            {
                "reading": 14.54,
                "uid": 4,
                "isControlling": False,
                "type": "suction",
                "isWireless": False,
                "status": "reporting",
            },
        ],
        "wifiRSSI": -43,
    }


def test_dehum_status_from_dict():
    status = DehumidifierStatus.from_dict(_dehum_status_data())
    assert status.device_id == "BC8D7EECB7D1"
    assert status.equipment_status == "inactive"
    assert status.is_comp_on is False
    assert status.is_dehum_fan_on is False
    assert status.is_hvac_fan_on is False
    assert status.wifi_rssi == -43
    assert status.fan_time_hours == 0
    assert len(status.hum_sensors) == 1
    assert status.hum_sensors[0].reading == 47.0
    assert status.hum_sensors[0].is_controlling is True
    assert len(status.temp_sensors) == 2
    assert status.filter_service.remaining == 100
    assert status.alerts.high_temp is False


def test_dehum_status_defaults():
    status = DehumidifierStatus.from_dict({})
    assert status.equipment_status == ""
    assert status.hum_sensors == []
    assert status.temp_sensors == []
    assert status.wifi_rssi == 0


# --- SensorInfo / DehumidifierSettings / DeviceSettings ---


def test_sensor_info_from_dict():
    si = SensorInfo.from_dict({"uid": 1, "dispName": "Inlet Air"})
    assert si.uid == 1
    assert si.display_name == "Inlet Air"


def test_dehumidifier_settings_from_dict():
    data = {
        "mode": "on",
        "humiditySetpoint": 50,
        "sensors": [
            {"uid": 1, "dispName": "Inlet Air"},
            {"uid": 4, "dispName": "Suction Line"},
        ],
    }
    ds = DehumidifierSettings.from_dict(data)
    assert ds.mode == "on"
    assert ds.humidity_setpoint == 50
    assert len(ds.sensors) == 2


def test_device_settings_from_dict():
    data = {
        "deviceId": "BC8D7EECB7D1",
        "asOf": "2026-05-25T20:20:41.265Z",
        "dehumidifier": {
            "mode": "on",
            "humiditySetpoint": 50,
            "sensors": [{"uid": 1, "dispName": "Inlet Air"}],
        },
    }
    settings = DeviceSettings.from_dict(data)
    assert settings.device_id == "BC8D7EECB7D1"
    assert settings.dehumidifier is not None
    assert settings.dehumidifier.mode == "on"
    assert settings.dehumidifier.humidity_setpoint == 50


def test_device_settings_no_dehumidifier():
    settings = DeviceSettings.from_dict({"deviceId": "X", "asOf": ""})
    assert settings.dehumidifier is None
