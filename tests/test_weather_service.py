import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from bot.services.weather import (
    OpenMeteoClient,
    PagasaAlertClient,
    WeatherService,
    OpenMeteoError,
    PagasaError,
    parse_pagasa_alerts,
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


def test_parse_pagasa_alerts_from_fixture_html():
    """Test parse_pagasa_alerts using local fixture HTML."""
    fixture_path = Path("tests/fixtures/pagasa_ncrprsd.html")
    html_content = fixture_path.read_text(encoding="utf-8")

    alerts = parse_pagasa_alerts(html_content)

    assert len(alerts) == 2

    # 1. Rainfall Warning
    rf_alert = alerts[0]
    assert rf_alert.source == "PAGASA NCR-PRSD"
    assert "Heavy Rainfall Warning No. 26" in rf_alert.event
    assert rf_alert.severity == "ORANGE"
    assert rf_alert.affects_metro_manila is True
    assert rf_alert.issued_at is not None
    assert rf_alert.issued_at.tzinfo is not None

    # 2. Thunderstorm Advisory
    ts_alert = alerts[1]
    assert ts_alert.source == "PAGASA NCR-PRSD"
    assert "Thunderstorm Advisory No. 5" in ts_alert.event
    assert ts_alert.affects_metro_manila is True


def test_parse_pagasa_alerts_red_elsewhere_orange_metro_manila():
    """Test RED level elsewhere + ORANGE level Metro Manila targets ORANGE for Metro Manila."""
    html = """
    <div id="rainfalls">
      <h4>Heavy Rainfall Warning No. 10 #NCR_PRSD</h4>
      <p>Issued at: 08:00 AM, 08 August 2026</p>
      <p>RED WARNING LEVEL: Zambales, Bataan.</p>
      <p>ORANGE WARNING LEVEL: Metro Manila, Cavite.</p>
    </div>
    """

    alerts = parse_pagasa_alerts(html)
    assert len(alerts) == 1
    assert alerts[0].severity == "ORANGE"
    assert alerts[0].affects_metro_manila is True


def test_parse_pagasa_alerts_metro_manila_hazard_isolation():
    """Test Metro Manila receives ONLY its block's associated hazard and NOT a neighboring RED block's hazard."""
    html = """
    <div id="rainfalls">
      <h4>Heavy Rainfall Warning No. 26 #NCR_PRSD</h4>
      <p>Issued at: 11:00 AM, 08 August 2026</p>
      <p>RED WARNING LEVEL: Zambales, Bataan.</p>
      <p>ASSOCIATED HAZARD: Serious FLOODING is expected in low-lying areas.</p>
      <p>ORANGE WARNING LEVEL: Metro Manila, Cavite.</p>
      <p>ASSOCIATED HAZARD: FLOODING is still THREATENING.</p>
    </div>
    """

    alerts = parse_pagasa_alerts(html)
    assert len(alerts) == 1
    alert = alerts[0]

    assert alert.severity == "ORANGE"
    assert alert.affects_metro_manila is True
    assert alert.associated_hazard == "Flooding is still threatening."
    assert "Serious FLOODING" not in (alert.associated_hazard or "")


def test_parse_pagasa_alerts_unrelated_province_does_not_affect_metro_manila():
    """Test warning for unrelated provinces (no Metro Manila) flags affects_metro_manila=False."""
    html = """
    <div id="rainfalls">
      <h4>Heavy Rainfall Warning No. 12 #NCR_PRSD</h4>
      <p>RED WARNING LEVEL: Zambales, Bataan, Tarlac.</p>
    </div>
    """

    alerts = parse_pagasa_alerts(html)
    assert len(alerts) == 1
    assert alerts[0].severity == "RED"
    assert alerts[0].affects_metro_manila is False


def test_parse_pagasa_alerts_no_thunderstorm_advisory_message():
    """Test text 'As of today, there is no Thunderstorm Advisory Issued.' returns no thunderstorm alert."""
    html = """
    <div id="thunderstorms">
      <p>As of today, there is no Thunderstorm Advisory Issued.</p>
    </div>
    """

    alerts = parse_pagasa_alerts(html)
    assert len(alerts) == 0


def test_pagasa_client_http_errors_handled():
    """Test PagasaAlertClient handles HTTP failures and timeouts gracefully by raising PagasaError."""
    async def _test():
        client = PagasaAlertClient()

        with patch("httpx.AsyncClient.get", side_effect=httpx.TimeoutException("Timeout")):
            with pytest.raises(PagasaError, match="request timed out"):
                await client.fetch_alerts("https://example.com")

    asyncio.run(_test())


def test_weather_service_degrades_cleanly_when_pagasa_fails():
    """Test WeatherService returns forecast report cleanly when PAGASA fetch fails."""
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
        service.pagasa_client.fetch_alerts = AsyncMock(side_effect=PagasaError("HTTP 500"))

        report = await service.get_weather_report(
            lat=14.5869,
            lon=120.9762,
            pagasa_ncr_url="https://example.com",
        )

        assert report.current is not None
        assert report.current.temperature_c == 28.0
        assert report.alert_status_note == "Official PAGASA warning data is temporarily unavailable."
        assert len(report.alerts) == 0
        assert report.risk.level == WeatherRiskLevel.LOW

    asyncio.run(_test())
