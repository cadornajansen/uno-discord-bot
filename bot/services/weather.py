from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import re
from typing import Optional, Sequence
import zoneinfo
from bs4 import BeautifulSoup
import httpx

from bot.services.weather_risk import (
    WeatherRisk,
    evaluate_disruption_risk,
)

logger = logging.getLogger(__name__)

# WMO Weather Code Descriptions
WMO_DESCRIPTIONS = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorms",
    96: "Thunderstorms with slight hail",
    99: "Thunderstorms with heavy hail",
}


def format_wmo_code(code: int) -> str:
    """Return human-readable description for WMO weather code."""
    return WMO_DESCRIPTIONS.get(code, f"Weather Code {code}")


class WeatherError(Exception):
    """Base exception for weather service operations."""

    pass


class OpenMeteoError(WeatherError):
    """Raised when fetching or parsing data from Open-Meteo fails."""

    pass


class PagasaError(WeatherError):
    """Raised when fetching or parsing PAGASA warnings fails."""

    pass


@dataclass(frozen=True)
class CurrentWeather:
    """Holds current weather conditions."""

    temperature_c: float
    apparent_temperature_c: Optional[float]
    humidity_percent: Optional[float]
    precipitation_mm: Optional[float]
    rain_mm: Optional[float]
    weather_code: int
    wind_speed_kmh: Optional[float]
    wind_gust_kmh: Optional[float]


@dataclass(frozen=True)
class HourlyWeather:
    """Holds hourly forecast conditions."""

    time: datetime
    precipitation_probability: Optional[int]
    precipitation_mm: Optional[float]
    rain_mm: Optional[float]
    weather_code: int
    visibility_m: Optional[float]
    wind_speed_kmh: Optional[float]
    wind_gust_kmh: Optional[float]


@dataclass(frozen=True)
class WeatherAlert:
    """Holds official government weather warning information."""

    source: str
    event: str
    issued_at: Optional[datetime]
    severity: Optional[str]
    description: str
    affects_metro_manila: bool
    associated_hazard: Optional[str] = None


@dataclass(frozen=True)
class WeatherReport:
    """Holds combined weather forecast, government alerts, and disruption risk."""

    location_name: str
    current: Optional[CurrentWeather]
    hourly: tuple[HourlyWeather, ...]
    alerts: tuple[WeatherAlert, ...]
    alert_status_note: Optional[str]
    risk: WeatherRisk


def parse_pagasa_alerts(html: str) -> tuple[WeatherAlert, ...]:
    """Parse PAGASA NCR-PRSD HTML for active rainfall warnings and thunderstorm advisories.

    Args:
        html: Raw HTML string of the PAGASA NCR-PRSD regional forecast page.

    Returns:
        Tuple of WeatherAlert instances.
    """
    if not html or not html.strip():
        return ()

    soup = BeautifulSoup(html, "html.parser")
    alerts: list[WeatherAlert] = []
    tz = zoneinfo.ZoneInfo("Asia/Manila")

    # 1. Parse #rainfalls section
    rain_section = soup.find(id="rainfalls") or soup.select_one("#rainfalls")
    if rain_section:
        rain_text = rain_section.get_text(separator="\n").strip()

        if "heavy rainfall warning" in rain_text.lower():
            h4 = rain_section.find("h4")
            event_name = h4.get_text().strip() if h4 else "Heavy Rainfall Warning"

            issued_at = None
            match_time = re.search(
                r"Issued at:\s*(\d{1,2}:\d{2}\s*(?:AM|PM)),?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
                rain_text,
                re.IGNORECASE,
            )
            if match_time:
                time_str, date_str = match_time.group(1), match_time.group(2)
                try:
                    dt_naive = datetime.strptime(f"{date_str} {time_str}", "%d %B %Y %I:%M %p")
                    issued_at = dt_naive.replace(tzinfo=tz)
                except ValueError:
                    logger.debug(f"Could not parse PAGASA time string: '{date_str} {time_str}'")

            blocks = re.split(
                r"(RED WARNING LEVEL|ORANGE WARNING LEVEL|YELLOW WARNING LEVEL)",
                rain_text,
                flags=re.IGNORECASE,
            )

            matched_mm_severity = None
            matched_mm_hazard = None
            highest_overall_severity = None

            for i in range(1, len(blocks) - 1, 2):
                sev_name = blocks[i].strip().upper().replace(" WARNING LEVEL", "")
                block_content = blocks[i + 1]

                if highest_overall_severity is None:
                    highest_overall_severity = sev_name

                hazard_match = re.search(r"ASSOCIATED HAZARD:?\s*([^\n;]+)", block_content, re.IGNORECASE)
                raw_hazard = hazard_match.group(1).strip() if hazard_match else None

                loc_part = block_content.split("ASSOCIATED HAZARD")[0].lower()

                if "metro manila" in loc_part:
                    if matched_mm_severity is None:
                        matched_mm_severity = sev_name
                        if raw_hazard:
                            clean_hz = raw_hazard.strip(". ")
                            if clean_hz:
                                matched_mm_hazard = clean_hz[0].upper() + clean_hz[1:].lower() + "."

            final_severity = matched_mm_severity if matched_mm_severity else highest_overall_severity
            affects_mm = matched_mm_severity is not None

            alerts.append(
                WeatherAlert(
                    source="PAGASA NCR-PRSD",
                    event=event_name,
                    issued_at=issued_at,
                    severity=final_severity,
                    description=rain_text,
                    affects_metro_manila=affects_mm,
                    associated_hazard=matched_mm_hazard if affects_mm else None,
                )
            )

    # 2. Parse #thunderstorms section
    ts_section = soup.find(id="thunderstorms") or soup.select_one("#thunderstorms")
    if ts_section:
        ts_text = ts_section.get_text(separator="\n").strip()

        if ts_text and "no thunderstorm advisory issued" not in ts_text.lower():
            h4 = ts_section.find("h4")
            event_name = h4.get_text().strip() if h4 else "Thunderstorm Advisory"

            issued_at = None
            match_time = re.search(
                r"Issued at:\s*(\d{1,2}:\d{2}\s*(?:AM|PM)),?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
                ts_text,
                re.IGNORECASE,
            )
            if match_time:
                time_str, date_str = match_time.group(1), match_time.group(2)
                try:
                    dt_naive = datetime.strptime(f"{date_str} {time_str}", "%d %B %Y %I:%M %p")
                    issued_at = dt_naive.replace(tzinfo=tz)
                except ValueError:
                    pass

            affects_mm = "metro manila" in ts_text.lower()

            alerts.append(
                WeatherAlert(
                    source="PAGASA NCR-PRSD",
                    event=event_name,
                    issued_at=issued_at,
                    severity=None,
                    description=ts_text[:300],
                    affects_metro_manila=affects_mm,
                )
            )

    return tuple(alerts)


class OpenMeteoClient:
    """Client for fetching forecast data from the Open-Meteo API."""

    def __init__(self, base_url: str = "https://api.open-meteo.com/v1"):
        self.base_url = base_url.rstrip("/")

    async def fetch_forecast(
        self,
        lat: float,
        lon: float,
        tz_name: str = "Asia/Manila",
        timeout_seconds: float = 10.0,
    ) -> dict:
        """Fetch current and hourly forecast data from Open-Meteo API."""
        endpoint = f"{self.base_url}/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "timezone": tz_name,
            "forecast_days": 3,
            "current": (
                "temperature_2m,apparent_temperature,relative_humidity_2m,"
                "precipitation,rain,weather_code,wind_speed_10m,wind_gusts_10m"
            ),
            "hourly": (
                "temperature_2m,apparent_temperature,precipitation_probability,"
                "precipitation,rain,weather_code,visibility,wind_speed_10m,wind_gusts_10m"
            ),
        }

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds)) as client:
                response = await client.get(endpoint, params=params)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Open-Meteo returned HTTP error {e.response.status_code}")
            raise OpenMeteoError(f"Open-Meteo HTTP error status {e.response.status_code}") from e
        except httpx.TimeoutException as e:
            logger.error(f"Open-Meteo API request timed out after {timeout_seconds}s")
            raise OpenMeteoError(f"Open-Meteo request timed out after {timeout_seconds}s") from e
        except Exception as e:
            logger.error(f"Open-Meteo fetch failed: {e}")
            raise OpenMeteoError(f"Failed to fetch forecast from Open-Meteo: {e}") from e


class PagasaAlertClient:
    """Client for fetching official regional weather warnings from PAGASA NCR-PRSD."""

    def __init__(self, base_url: str = "https://www.pagasa.dost.gov.ph/regional-forecast/ncrprsd"):
        self.base_url = base_url

    async def fetch_alerts(
        self,
        url: Optional[str] = None,
        timeout_seconds: float = 10.0,
    ) -> tuple[WeatherAlert, ...]:
        """Fetch and parse official weather warnings from PAGASA NCR-PRSD."""
        target_url = url or self.base_url
        headers = {"User-Agent": "Uno-AI-Discord-Bot/1.0"}

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds), follow_redirects=True) as client:
                response = await client.get(target_url, headers=headers)
                response.raise_for_status()
                return parse_pagasa_alerts(response.text)
        except httpx.HTTPStatusError as e:
            logger.error(f"PAGASA returned HTTP status {e.response.status_code}")
            raise PagasaError(f"PAGASA HTTP error status {e.response.status_code}") from e
        except httpx.TimeoutException as e:
            logger.error(f"PAGASA request timed out after {timeout_seconds}s")
            raise PagasaError(f"PAGASA request timed out after {timeout_seconds}s") from e
        except Exception as e:
            logger.error(f"PAGASA fetch failed: {e}")
            raise PagasaError(f"Failed to fetch PAGASA warnings: {e}") from e


class WeatherService:
    """Service managing weather forecast retrieval, PAGASA alert integration, and risk calculation."""

    def __init__(
        self,
        open_meteo_client: Optional[OpenMeteoClient] = None,
        pagasa_client: Optional[PagasaAlertClient] = None,
    ):
        self.open_meteo_client = open_meteo_client or OpenMeteoClient()
        self.pagasa_client = pagasa_client or PagasaAlertClient()

    async def get_weather_report(
        self,
        lat: float = 14.5869,
        lon: float = 120.9762,
        location_name: str = "Manila (PLM)",
        tz_name: str = "Asia/Manila",
        pagasa_ncr_url: str = "https://www.pagasa.dost.gov.ph/regional-forecast/ncrprsd",
    ) -> WeatherReport:
        """Fetch combined forecast and PAGASA warnings and evaluate disruption risk."""
        # 1. Fetch Open-Meteo forecast data
        meteo_data = await self.open_meteo_client.fetch_forecast(lat=lat, lon=lon, tz_name=tz_name)

        current_raw = meteo_data.get("current", {})
        hourly_raw = meteo_data.get("hourly", {})

        current_obj = CurrentWeather(
            temperature_c=float(current_raw.get("temperature_2m", 0.0)),
            apparent_temperature_c=float(current_raw.get("apparent_temperature")) if current_raw.get("apparent_temperature") is not None else None,
            humidity_percent=float(current_raw.get("relative_humidity_2m")) if current_raw.get("relative_humidity_2m") is not None else None,
            precipitation_mm=float(current_raw.get("precipitation")) if current_raw.get("precipitation") is not None else None,
            rain_mm=float(current_raw.get("rain")) if current_raw.get("rain") is not None else None,
            weather_code=int(current_raw.get("weather_code", 0)),
            wind_speed_kmh=float(current_raw.get("wind_speed_10m")) if current_raw.get("wind_speed_10m") is not None else None,
            wind_gust_kmh=float(current_raw.get("wind_gusts_10m")) if current_raw.get("wind_gusts_10m") is not None else None,
        )

        hourly_times = hourly_raw.get("time", [])
        hourly_probs = hourly_raw.get("precipitation_probability", [])
        hourly_precips = hourly_raw.get("precipitation", [])
        hourly_rains = hourly_raw.get("rain", [])
        hourly_codes = hourly_raw.get("weather_code", [])
        hourly_vis = hourly_raw.get("visibility", [])
        hourly_winds = hourly_raw.get("wind_speed_10m", [])
        hourly_gusts = hourly_raw.get("wind_gusts_10m", [])

        tz = zoneinfo.ZoneInfo(tz_name)
        parsed_hourly = []

        for idx, time_str in enumerate(hourly_times):
            dt = datetime.fromisoformat(time_str).replace(tzinfo=tz)
            parsed_hourly.append(
                HourlyWeather(
                    time=dt,
                    precipitation_probability=int(hourly_probs[idx]) if idx < len(hourly_probs) and hourly_probs[idx] is not None else None,
                    precipitation_mm=float(hourly_precips[idx]) if idx < len(hourly_precips) and hourly_precips[idx] is not None else None,
                    rain_mm=float(hourly_rains[idx]) if idx < len(hourly_rains) and hourly_rains[idx] is not None else None,
                    weather_code=int(hourly_codes[idx]) if idx < len(hourly_codes) and hourly_codes[idx] is not None else 0,
                    visibility_m=float(hourly_vis[idx]) if idx < len(hourly_vis) and hourly_vis[idx] is not None else None,
                    wind_speed_kmh=float(hourly_winds[idx]) if idx < len(hourly_winds) and hourly_winds[idx] is not None else None,
                    wind_gust_kmh=float(hourly_gusts[idx]) if idx < len(hourly_gusts) and hourly_gusts[idx] is not None else None,
                )
            )

        # 2. Fetch PAGASA warnings with graceful degradation
        alerts: tuple[WeatherAlert, ...] = ()
        alert_status_note: Optional[str] = None

        try:
            alerts = await self.pagasa_client.fetch_alerts(url=pagasa_ncr_url)
            mm_alerts = [a for a in alerts if a.affects_metro_manila]
            if not mm_alerts:
                alert_status_note = "No active PAGASA rainfall or thunderstorm warnings found for Metro Manila."
        except Exception as e:
            logger.warning(f"PAGASA warnings fetch degraded: {e}")
            alert_status_note = "Official PAGASA warning data is temporarily unavailable."

        # 3. Evaluate Disruption Risk over next 6 hours
        hourly_6h_dicts = []
        for h in parsed_hourly[:6]:
            hourly_6h_dicts.append({
                "precipitation_probability": h.precipitation_probability,
                "precipitation_mm": h.precipitation_mm,
                "weather_code": h.weather_code,
                "visibility_m": h.visibility_m,
                "wind_gust_kmh": h.wind_gust_kmh,
            })

        alerts_dicts = []
        for a in alerts:
            alerts_dicts.append({
                "source": a.source,
                "event": a.event,
                "severity": a.severity,
                "affects_metro_manila": a.affects_metro_manila,
            })

        current_dict = {
            "precipitation_mm": current_obj.precipitation_mm,
            "weather_code": current_obj.weather_code,
            "wind_gust_kmh": current_obj.wind_gust_kmh,
        } if current_obj else None

        risk = evaluate_disruption_risk(
            current=current_dict,
            hourly_6h=hourly_6h_dicts,
            alerts=alerts_dicts,
        )

        return WeatherReport(
            location_name=location_name,
            current=current_obj,
            hourly=tuple(parsed_hourly),
            alerts=alerts,
            alert_status_note=alert_status_note,
            risk=risk,
        )
