from bot.services.weather_risk import (
    evaluate_disruption_risk,
    WeatherRiskLevel,
)


def test_low_risk_normal_weather():
    """Test clear sky, low rain probability, normal winds return LOW disruption risk."""
    hourly_6h = [
        {
            "precipitation_probability": 10,
            "precipitation_mm": 0.0,
            "weather_code": 0,
            "visibility_m": 10000.0,
            "wind_gust_kmh": 15.0,
        }
    ]
    alerts = []

    risk = evaluate_disruption_risk(current=None, hourly_6h=hourly_6h, alerts=alerts)
    assert risk.level == WeatherRiskLevel.LOW
    assert "No significant weather disruptions detected" in risk.reasons[0]


def test_moderate_risk_high_precip_probability():
    """Test precipitation probability >= 60% triggers MODERATE risk."""
    hourly_6h = [
        {
            "precipitation_probability": 65,
            "precipitation_mm": 1.0,
            "weather_code": 2,
            "visibility_m": 8000.0,
            "wind_gust_kmh": 20.0,
        }
    ]

    risk = evaluate_disruption_risk(current=None, hourly_6h=hourly_6h, alerts=[])
    assert risk.level == WeatherRiskLevel.MODERATE
    assert any("High rain probability (65%)" in r for r in risk.reasons)


def test_moderate_risk_moderate_rainfall():
    """Test rainfall >= 3.0 mm/hr triggers MODERATE risk."""
    hourly_6h = [
        {
            "precipitation_probability": 40,
            "precipitation_mm": 4.5,
            "weather_code": 61,
            "visibility_m": 5000.0,
            "wind_gust_kmh": 25.0,
        }
    ]

    risk = evaluate_disruption_risk(current=None, hourly_6h=hourly_6h, alerts=[])
    assert risk.level == WeatherRiskLevel.MODERATE
    assert any("Moderate rainfall forecast (4.5 mm/hr)" in r for r in risk.reasons)


def test_high_risk_thunderstorm_and_probability():
    """Test WMO thunderstorm code (95) + precipitation probability >= 70% triggers HIGH risk."""
    hourly_6h = [
        {
            "precipitation_probability": 85,
            "precipitation_mm": 8.0,
            "weather_code": 95,
            "visibility_m": 4000.0,
            "wind_gust_kmh": 45.0,
        }
    ]

    risk = evaluate_disruption_risk(current=None, hourly_6h=hourly_6h, alerts=[])
    assert risk.level == WeatherRiskLevel.HIGH
    assert any("Thunderstorms forecast with 85% rain probability" in r for r in risk.reasons)


def test_high_risk_heavy_rainfall():
    """Test heavy rainfall >= 10.0 mm/hr triggers HIGH risk."""
    hourly_6h = [
        {
            "precipitation_probability": 50,
            "precipitation_mm": 14.2,
            "weather_code": 65,
            "visibility_m": 2000.0,
            "wind_gust_kmh": 30.0,
        }
    ]

    risk = evaluate_disruption_risk(current=None, hourly_6h=hourly_6h, alerts=[])
    assert risk.level == WeatherRiskLevel.HIGH
    assert any("Heavy rainfall forecast (14.2 mm/hr)" in r for r in risk.reasons)


def test_high_risk_low_visibility():
    """Test visibility < 1000 m triggers HIGH risk."""
    hourly_6h = [
        {
            "precipitation_probability": 20,
            "precipitation_mm": 0.0,
            "weather_code": 45,
            "visibility_m": 600.0,
            "wind_gust_kmh": 10.0,
        }
    ]

    risk = evaluate_disruption_risk(current=None, hourly_6h=hourly_6h, alerts=[])
    assert risk.level == WeatherRiskLevel.HIGH
    assert any("Severely reduced visibility forecast (600 m)" in r for r in risk.reasons)


def test_high_risk_strong_gusts():
    """Test wind gusts >= 60 km/h triggers HIGH risk."""
    hourly_6h = [
        {
            "precipitation_probability": 20,
            "precipitation_mm": 0.0,
            "weather_code": 3,
            "visibility_m": 10000.0,
            "wind_gust_kmh": 68.0,
        }
    ]

    risk = evaluate_disruption_risk(current=None, hourly_6h=hourly_6h, alerts=[])
    assert risk.level == WeatherRiskLevel.HIGH
    assert any("Strong wind gusts forecast (68 km/h)" in r for r in risk.reasons)


def test_high_risk_severe_government_alert():
    """Test active severe government alert triggers HIGH risk."""
    hourly_6h = [
        {
            "precipitation_probability": 10,
            "precipitation_mm": 0.0,
            "weather_code": 1,
            "visibility_m": 10000.0,
            "wind_gust_kmh": 10.0,
        }
    ]
    alerts = [
        {"sender": "PAGASA", "event": "Heavy Rainfall Warning Signal No. 1"}
    ]

    risk = evaluate_disruption_risk(current=None, hourly_6h=hourly_6h, alerts=alerts)
    assert risk.level == WeatherRiskLevel.HIGH
    assert any("PAGASA" in r for r in risk.reasons)


def test_high_risk_from_current_wind_gust():
    """Regression test: current wind gust >= 60.0 km/h triggers HIGH risk even if hourly entries are lower."""
    current = {
        "precipitation_mm": 0.0,
        "weather_code": 1,
        "wind_gust_kmh": 69.1,
    }
    hourly_6h = [
        {
            "precipitation_probability": 20,
            "precipitation_mm": 0.0,
            "weather_code": 1,
            "visibility_m": 10000.0,
            "wind_gust_kmh": 25.0,
        }
    ]

    risk = evaluate_disruption_risk(current=current, hourly_6h=hourly_6h, alerts=[])
    assert risk.level == WeatherRiskLevel.HIGH
    assert any("Strong wind gusts forecast (69 km/h)" in r for r in risk.reasons)

