from dataclasses import dataclass
from enum import Enum
import logging
from typing import Sequence

logger = logging.getLogger(__name__)


class WeatherRiskLevel(Enum):
    """Deterministically calculated class disruption risk level."""

    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


@dataclass(frozen=True)
class WeatherRisk:
    """Holds disruption risk level and human-readable explanation reasons."""

    level: WeatherRiskLevel
    reasons: tuple[str, ...]


# WMO Weather Codes grouping
THUNDERSTORM_CODES = (95, 96, 99)
RAIN_SHOWERS_CODES = (51, 52, 53, 54, 55, 56, 57, 61, 62, 63, 64, 65, 66, 67, 80, 81, 82)


def evaluate_disruption_risk(
    current: dict | None,
    hourly_6h: Sequence[dict],
    alerts: Sequence[dict],
) -> WeatherRisk:
    """Evaluate weather disruption risk for classes based on current conditions and next 6 hours forecast.

    Args:
        current: Optional dict of current weather parameters.
        hourly_6h: Sequence of hourly forecast dictionaries for the next 6 hours.
        alerts: Sequence of active government weather alert dictionaries.

    Returns:
        WeatherRisk dataclass instance.
    """
    high_reasons = []
    moderate_reasons = []

    # 1. Evaluate Government Alerts
    for alert in alerts:
        event = alert.get("event", "")
        sender = alert.get("sender", "")
        event_lower = event.lower()

        is_severe_alert = any(
            kw in event_lower
            for kw in (
                "severe",
                "extreme",
                "warning",
                "typhoon",
                "signal",
                "heavy rainfall warning",
                "torrential",
            )
        )

        if is_severe_alert:
            high_reasons.append(f"Severe government alert in effect: {event} ({sender})")
        else:
            moderate_reasons.append(f"Government alert in effect: {event} ({sender})")

    # 2. Evaluate Forecast & Current Parameters
    max_precip_prob = 0
    max_precip_mm = 0.0
    min_visibility_m = 999999.0
    max_wind_gust = 0.0
    has_thunderstorm_code = False
    has_rain_code = False

    # Incorporate current conditions if present
    if isinstance(current, dict):
        c_precip = current.get("precipitation_mm") or 0.0
        c_code = current.get("weather_code") or 0
        c_gust = current.get("wind_gust_kmh") or 0.0

        if c_precip > max_precip_mm:
            max_precip_mm = c_precip
        if c_gust > max_wind_gust:
            max_wind_gust = c_gust
        if c_code in THUNDERSTORM_CODES:
            has_thunderstorm_code = True
        if c_code in RAIN_SHOWERS_CODES:
            has_rain_code = True

    # Incorporate next 6 hours forecast entries
    for item in hourly_6h:
        prob = item.get("precipitation_probability") or 0
        precip = item.get("precipitation_mm") or 0.0
        code = item.get("weather_code") or 0
        vis = item.get("visibility_m")
        gust = item.get("wind_gust_kmh") or 0.0

        if prob > max_precip_prob:
            max_precip_prob = prob
        if precip > max_precip_mm:
            max_precip_mm = precip
        if vis is not None and vis < min_visibility_m:
            min_visibility_m = vis
        if gust > max_wind_gust:
            max_wind_gust = gust

        if code in THUNDERSTORM_CODES:
            has_thunderstorm_code = True
        if code in RAIN_SHOWERS_CODES:
            has_rain_code = True

    # Check HIGH Risk Heuristics
    if has_thunderstorm_code and max_precip_prob >= 70:
        high_reasons.append(f"Thunderstorms forecast with {max_precip_prob}% rain probability")

    if max_precip_mm >= 10.0:
        high_reasons.append(f"Heavy rainfall forecast ({max_precip_mm:.1f} mm/hr)")

    if min_visibility_m < 1000.0:
        high_reasons.append(f"Severely reduced visibility forecast ({int(min_visibility_m)} m)")

    if max_wind_gust >= 60.0:
        high_reasons.append(f"Strong wind gusts forecast ({int(max_wind_gust)} km/h)")

    if high_reasons:
        return WeatherRisk(level=WeatherRiskLevel.HIGH, reasons=tuple(dict.fromkeys(high_reasons)))

    # Check MODERATE Risk Heuristics
    if max_precip_prob >= 60:
        moderate_reasons.append(f"High rain probability ({max_precip_prob}%)")

    if max_precip_mm >= 3.0:
        moderate_reasons.append(f"Moderate rainfall forecast ({max_precip_mm:.1f} mm/hr)")

    if has_rain_code or has_thunderstorm_code:
        moderate_reasons.append("Rain or showers forecast within class hours")

    if min_visibility_m < 3000.0:
        moderate_reasons.append(f"Reduced visibility forecast ({int(min_visibility_m)} m)")

    if max_wind_gust >= 40.0:
        moderate_reasons.append(f"Moderate wind gusts forecast ({int(max_wind_gust)} km/h)")

    if moderate_reasons:
        return WeatherRisk(level=WeatherRiskLevel.MODERATE, reasons=tuple(dict.fromkeys(moderate_reasons)))

    # Default LOW Risk
    return WeatherRisk(
        level=WeatherRiskLevel.LOW,
        reasons=("No significant weather disruptions detected for class hours.",),
    )
