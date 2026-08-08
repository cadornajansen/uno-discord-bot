import logging
from typing import Optional
import zoneinfo
import discord
from discord import app_commands
from discord.ext import commands

from bot.services.weather import (
    WeatherService,
    WeatherReport,
    WeatherError,
    OpenMeteoError,
    format_wmo_code,
)
from bot.services.weather_risk import WeatherRiskLevel
from bot.utils.formatting import split_message

logger = logging.getLogger(__name__)


def format_weather_response(report: WeatherReport) -> str:
    """Format WeatherReport into compact markdown response string."""
    sections = [f"**Weather — {report.location_name}**"]

    # Current weather section
    curr = report.current
    if curr:
        temp_str = f"{int(round(curr.temperature_c))}°C"
        feels_str = f"Feels like {int(round(curr.apparent_temperature_c))}°C" if curr.apparent_temperature_c is not None else ""
        header_line = f"{temp_str} · {feels_str}" if feels_str else temp_str
        sections.append(header_line)

        wmo_desc = format_wmo_code(curr.weather_code)
        sections.append(wmo_desc)

        # Rain & Wind metrics from current or next 3 hours
        details = []
        if curr.humidity_percent is not None:
            details.append(f"Humidity: {int(curr.humidity_percent)}%")
        if curr.precipitation_mm is not None and curr.precipitation_mm > 0:
            details.append(f"Rainfall: {curr.precipitation_mm:.1f} mm")
        if curr.wind_speed_kmh is not None:
            wind_line = f"Wind: {int(round(curr.wind_speed_kmh))} km/h"
            if curr.wind_gust_kmh is not None and curr.wind_gust_kmh > curr.wind_speed_kmh:
                wind_line += f" · Gusts: {int(round(curr.wind_gust_kmh))} km/h"
            details.append(wind_line)

        if details:
            sections.append(" · ".join(details))

    # Next 3 hours forecast summary
    if report.hourly:
        next_3h = report.hourly[:3]
        h_parts = []
        for h in next_3h:
            h_time_str = h.time.strftime("%I %p").lstrip("0")
            prob_str = f"{h.precipitation_probability}%" if h.precipitation_probability is not None else "0%"
            h_parts.append(f"{h_time_str}: {prob_str} rain")
        sections.append("\n**Next 3 Hours**\n" + " · ".join(h_parts))

    # Disruption Risk section
    risk_level_str = report.risk.level.value
    sections.append(f"\n**Weather Disruption Risk: {risk_level_str}**")
    for reason in report.risk.reasons:
        sections.append(f"• {reason}")

    # Official Government Weather Alerts section
    sections.append("\n**Official Weather Alerts**")
    if report.alerts:
        for alert in report.alerts:
            sender_prefix = f"{alert.sender} — " if alert.sender else ""
            valid_end_str = alert.end.strftime("%I:%M %p").lstrip("0")
            sections.append(f"{sender_prefix}{alert.event}\nValid until {valid_end_str}")
    elif report.alert_status_note:
        sections.append(report.alert_status_note)

    # Footer Disclaimer
    sections.append(
        "\n*Uno's risk level is a weather-based estimate only. Class suspension decisions come from official authorities.*"
    )

    return "\n".join(sections)


class WeatherCog(commands.Cog):
    """Cog handling /weather command, forecast retrieval, PAGASA alerts, and disruption risk."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        settings = getattr(bot, "settings", None)

        self.lat = settings.weather_latitude if settings else 14.5869
        self.lon = settings.weather_longitude if settings else 120.9762
        self.location_name = settings.weather_location_name if settings else "Manila (PLM)"
        self.tz_name = settings.weather_timezone if settings else "Asia/Manila"
        self.openweather_api_key = settings.openweather_api_key if settings else ""
        self.openweather_base_url = settings.openweather_base_url if settings else "https://api.openweathermap.org"

        self.weather_service = WeatherService()

    @app_commands.command(
        name="weather",
        description="Show Manila weather forecast, government alerts, and weather disruption risk.",
    )
    async def weather(self, interaction: discord.Interaction) -> None:
        """Slash command /weather"""
        await interaction.response.defer()

        try:
            report = await self.weather_service.get_weather_report(
                lat=self.lat,
                lon=self.lon,
                location_name=self.location_name,
                tz_name=self.tz_name,
                openweather_api_key=self.openweather_api_key,
                openweather_base_url=self.openweather_base_url,
            )

            formatted_text = format_weather_response(report)
            chunks = split_message(formatted_text, limit=2000)

            for chunk in chunks:
                await interaction.followup.send(chunk)

        except (WeatherError, OpenMeteoError) as e:
            logger.error(f"User {interaction.user.id} '/weather' failed: {e}")
            await interaction.followup.send("Weather forecast data is currently unavailable.")

        except Exception as e:
            logger.error(f"Unexpected error executing '/weather': {e}", exc_info=True)
            await interaction.followup.send("Something went wrong while fetching weather data.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WeatherCog(bot))
