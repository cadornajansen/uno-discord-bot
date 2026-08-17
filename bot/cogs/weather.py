import logging
from typing import Optional
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
from bot.utils.formatting import split_message, send_deferred_response

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

    # Official PAGASA Warnings section
    sections.append("\n**Official PAGASA Warnings**")
    active_mm_alerts = [a for a in report.alerts if a.affects_metro_manila]

    if active_mm_alerts:
        for alert in active_mm_alerts:
            sev_str = f" — {alert.severity} WARNING" if alert.severity else ""
            issued_str = (
                f"\nIssued: {alert.issued_at.strftime('%I:%M %p').lstrip('0')} (<t:{int(alert.issued_at.timestamp())}:R>)"
                if alert.issued_at
                else ""
            )
            
            entry = f"**{alert.event}**\nMetro Manila{sev_str}{issued_str}"
            if alert.associated_hazard:
                entry += f"\nAssociated Hazard: {alert.associated_hazard}"
            sections.append(entry)
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
        self.pagasa_ncr_url = (
            settings.pagasa_ncr_url
            if settings
            else "https://www.pagasa.dost.gov.ph/regional-forecast/ncrprsd"
        )

        self.weather_service = WeatherService()

    @app_commands.command(
        name="weather",
        description="Show Manila weather forecast, PAGASA warnings, and weather disruption risk.",
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
                pagasa_ncr_url=self.pagasa_ncr_url,
            )

            formatted_text = format_weather_response(report)
            await send_deferred_response(interaction, formatted_text)

        except (WeatherError, OpenMeteoError) as e:
            logger.error(f"User {interaction.user.id} '/weather' failed: {e}")
            await interaction.edit_original_response(content="Weather forecast data is currently unavailable.")

        except Exception as e:
            logger.error(f"Unexpected error executing '/weather': {e}", exc_info=True)
            await interaction.edit_original_response(content="Something went wrong while fetching weather data.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WeatherCog(bot))
