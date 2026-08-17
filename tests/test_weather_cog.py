import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest

from bot.cogs.weather import WeatherCog, format_weather_response
from bot.services.weather import (
    WeatherReport,
    CurrentWeather,
    HourlyWeather,
    WeatherAlert,
    OpenMeteoError,
)
from bot.services.weather_risk import WeatherRisk, WeatherRiskLevel


def test_format_weather_response_helper():
    """Test format_weather_response formats report, risk, PAGASA warnings, and disclaimer."""
    report = WeatherReport(
        location_name="Manila (PLM)",
        current=CurrentWeather(
            temperature_c=28.0,
            apparent_temperature_c=32.0,
            humidity_percent=85.0,
            precipitation_mm=7.2,
            rain_mm=7.2,
            weather_code=95,
            wind_speed_kmh=22.0,
            wind_gust_kmh=41.0,
        ),
        hourly=(),
        alerts=(
            WeatherAlert(
                source="PAGASA NCR-PRSD",
                event="Heavy Rainfall Warning No. 26",
                issued_at=datetime(2026, 8, 8, 11, 0, tzinfo=timezone.utc),
                severity="ORANGE",
                description="RED WARNING LEVEL: Zambales, Bataan.\nORANGE WARNING LEVEL: Metro Manila, Cavite.",
                affects_metro_manila=True,
                associated_hazard="Flooding is still threatening.",
            ),
        ),
        alert_status_note=None,
        risk=WeatherRisk(
            level=WeatherRiskLevel.HIGH,
            reasons=("Official PAGASA warning for Metro Manila: Heavy Rainfall Warning No. 26 (ORANGE WARNING)",),
        ),
    )

    text = format_weather_response(report)

    assert "**Weather — Manila (PLM)**" in text
    assert "28°C · Feels like 32°C" in text
    assert "Thunderstorms" in text
    assert "**Weather Disruption Risk: HIGH**" in text
    assert "**Official PAGASA Warnings**" in text
    assert "Heavy Rainfall Warning No. 26" in text
    assert "Metro Manila — ORANGE WARNING" in text
    assert "Issued: 11:00 AM" in text
    assert "<t:" in text
    assert ":R>" in text
    assert "Associated Hazard: Flooding is still threatening." in text
    assert "Zambales" not in text
    assert "Bataan" not in text
    assert "Batangas" not in text
    assert "*Uno's risk level is a weather-based estimate only. Class suspension decisions come from official authorities.*" in text


def test_weather_command_successful_execution():
    """Test /weather slash command callback defers and sends formatted report."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = WeatherCog(bot)

        mock_report = WeatherReport(
            location_name="Manila (PLM)",
            current=CurrentWeather(
                temperature_c=29.0,
                apparent_temperature_c=33.0,
                humidity_percent=70.0,
                precipitation_mm=0.0,
                rain_mm=0.0,
                weather_code=1,
                wind_speed_kmh=15.0,
                wind_gust_kmh=20.0,
            ),
            hourly=(),
            alerts=(),
            alert_status_note="No active PAGASA rainfall or thunderstorm warnings found for Metro Manila.",
            risk=WeatherRisk(level=WeatherRiskLevel.LOW, reasons=("Normal weather",)),
        )

        cog.weather_service.get_weather_report = AsyncMock(return_value=mock_report)

        interaction = MagicMock()
        interaction.user.id = 12345
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        interaction.delete_original_response = AsyncMock()
        interaction.followup.send = AsyncMock()

        await cog.weather.callback(cog, interaction)

        interaction.response.defer.assert_called_once()
        cog.weather_service.get_weather_report.assert_called_once()
        interaction.edit_original_response.assert_called_once()
        interaction.delete_original_response.assert_not_called()
        sent_msg = interaction.edit_original_response.call_args[1]["content"]
        assert "**Weather — Manila (PLM)**" in sent_msg
        assert "No active PAGASA rainfall or thunderstorm warnings found for Metro Manila." in sent_msg

    asyncio.run(_test())


def test_weather_command_openmeteo_failure_handled():
    """Test /weather handles OpenMeteo error gracefully without crashing."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = WeatherCog(bot)

        cog.weather_service.get_weather_report = AsyncMock(
            side_effect=OpenMeteoError("API down")
        )

        interaction = MagicMock()
        interaction.user.id = 12345
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        interaction.delete_original_response = AsyncMock()
        interaction.followup.send = AsyncMock()

        await cog.weather.callback(cog, interaction)

        interaction.response.defer.assert_called_once()
        interaction.edit_original_response.assert_called_once_with(
            content="Weather forecast data is currently unavailable."
        )
        interaction.delete_original_response.assert_not_called()

    asyncio.run(_test())
