"""Hardware-free tests for temperature and clock helpers."""

from system_temperature_mcp import server


def test_interpret_temperature_handles_empty_sensor_list() -> None:
    assert "センサー" in server.interpret_temperature([])


def test_interpret_temperature_uses_hottest_sensor() -> None:
    temperatures = [
        {"temperature_celsius": 45.0},
        {"temperature_celsius": 81.0},
    ]

    assert "かなり熱い" in server.interpret_temperature(temperatures)


def test_get_all_temperatures_deduplicates_same_sensor_reading(monkeypatch) -> None:
    reading = {"name": "cpu/temp", "temperature_celsius": 50.04}
    monkeypatch.setattr(server, "get_thermal_zones", lambda: [reading])
    monkeypatch.setattr(server, "get_psutil_temperatures", lambda: [reading.copy()])
    monkeypatch.setattr(server, "get_hwmon_temperatures", lambda: [])

    result = server.get_all_temperatures()

    assert len(result["temperatures"]) == 1


def test_get_current_time_returns_japan_localized_text() -> None:
    assert server.get_current_time().startswith("今は ")
