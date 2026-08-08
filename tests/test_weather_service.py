import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from bot.services.weather import (
    OpenMeteoClient,
    OpenWeatherClient,
    WeatherService,
    OpenMeteoError,
    OpenWeatherError,
    format_wmo_code,
)
from bot.services.weather_risk import WeatherRiskLevel


def test_wmo_code_formatter_descriptions():
    """Test format_wmo_code maps codes to human-readable descriptions."""
    assert format_wmo_code(0) == "Clear sky"
    assert format_wmo_code(3) == "Overcast"
    assert format_wmo_code(63) == "Moderate rain"
    assert format_wmo_code(95) == "Thunderstorms"
    assert format_wmo_code(999) == "Weather Code 999"


def test_open_meteo_client_parses_forecast():
    """Test OpenMeteoClient fetches and parses current and hourly weather data."""
    async def _test():
        client = OpenMeteoClient()

        mock_payload = {
            "current": {
                "temperature_2m": 28.5,
                "apparent_temperature": 32.0,
                "relative_humidity_2m": 80,
                "precipitation": 2.5,
                "rain": 2.5,
                "weather_code": 95,
                "wind_speed_10m": 18.0,
                "wind_gusts_10m": 35.0,
            },
            "hourly": {
                "time": ["2026-08-08T12:00", "2026-08-08T13:00"],
                "precipitation_probability": [75, 85],
                "precipitation": [2.5, 5.0],
                "rain": [2.5, 5.0],
                "weather_code": [95, 95],
                "visibility": [8000.0, 5000.0],
                "wind_speed_10m": [18.0, 22.0],
                "wind_gusts_10m": [35.0, 42.0],
            },
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_payload
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            data = await client.fetch_forecast(14.5869, 120.9762)

            assert "current" in data
            assert data["current"]["temperature_2m"] == 28.5
            assert data["current"]["weather_code"] == 95

    asyncio.run(_test())


def test_open_meteo_client_timeout_handled():
    """Test OpenMeteoClient raises OpenMeteoError on timeout."""
    async def _test():
        client = OpenMeteoClient()

        with patch("httpx.AsyncClient.get", side_effect=httpx.TimeoutException("Timeout")):
            with pytest.raises(OpenMeteoError, match="request timed out"):
                await client.fetch_forecast(14.5869, 120.9762)

    asyncio.run(_test())


def test_open_weather_client_parses_pagasa_alerts():
    """Test OpenWeatherClient parses government alerts and preserves PAGASA sender."""
    async def _test():
        client = OpenWeatherClient()

        mock_payload = {
            "alerts": [
                {
                    "sender_name": "PAGASA",
                    "event": "Heavy Rainfall Warning",
                    "start": 1700000000,
                    "end": 1700010000,
                    "description": "Heavy rainfall expected over Metro Manila.",
                }
            ]
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_payload
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            alerts = await client.fetch_alerts(14.5869, 120.9762, api_key="dummy_key")

            assert len(alerts) == 1
            assert alerts[0].sender == "PAGASA"
            assert alerts[0].event == "Heavy Rainfall Warning"

    asyncio.run(_test())


def test_weather_service_degrades_cleanly_when_openweather_key_missing():
    """Test WeatherService returns weather report even when OpenWeather API key is empty."""
    async def _test():
        service = WeatherService()

        mock_meteo_payload = {
            "current": {"temperature_2m": 28.0, "weather_code": 1},
            "hourly": {
                "time": ["2026-08-08T12:00"],
                "precipitation_probability": [10],
                "precipitation": [0.0],
                "weather_code": [1],
            },
        }

        service.open_meteo_client.fetch_forecast = AsyncMock(return_value=mock_meteo_payload)

        report = await service.get_weather_report(
            lat=14.5869,
            lon=120.9762,
            openweather_api_key="",
        )

        assert report.current is not None
        assert report.current.temperature_c == 28.0
        assert report.alert_status_note == "Official alert integration is not configured."
        assert len(report.alerts) == 0
        assert report.risk.level == WeatherRiskLevel.LOW

    asyncio.run(_test())


def test_weather_service_degrades_cleanly_when_openweather_fails():
    """Test WeatherService handles OpenWeather failure gracefully without breaking forecast."""
    async def _test():
        service = WeatherService()

        mock_meteo_payload = {
            "current": {"temperature_2m": 29.0, "weather_code": 0},
            "hourly": {
                "time": ["2026-08-08T12:00"],
                "precipitation_probability": [5],
                "precipitation": [0.0],
                "weather_code": [0],
            },
        }

        service.open_meteo_client.fetch_forecast = AsyncMock(return_value=mock_meteo_payload)
        service.open_weather_client.fetch_alerts = AsyncMock(side_effect=OpenWeatherError("API error"))

        report = await service.get_weather_report(
            lat=14.5869,
            lon=120.9762,
            openweather_api_key="valid_key",
        )

        assert report.current is not None
        assert report.alert_status_note == "Official alert data is temporarily unavailable."
        assert len(report.alerts) == 0

    asyncio.run(_test())
