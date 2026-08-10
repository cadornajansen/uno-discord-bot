import logging
from pathlib import Path
from typing import Optional
import zoneinfo
import discord
from discord import app_commands
from discord.ext import commands

from bot.services.academic_schedule import (
    AcademicScheduleService,
    ClassMeeting,
    Subject,
    ScheduleError,
    ScheduleDataNotFoundError,
    ScheduleValidationError,
    format_12h_time,
    VALID_DAYS,
)
from bot.utils.formatting import split_message

logger = logging.getLogger(__name__)


def format_meeting_time_range(meeting: ClassMeeting) -> str:
    """Format meeting start and end times into '7:00 AM–10:00 AM' string."""
    return f"{format_12h_time(meeting.start)}–{format_12h_time(meeting.end)}"


class AcademicsCog(commands.Cog):
    """Cog handling academic schedule, daily classes, next class, and professor lookup commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        settings = getattr(bot, "settings", None)

        data_dir = Path("data/academics")
        school_year = settings.academic_school_year if settings else "2026-2027"
        semester = settings.academic_semester if settings else 1
        tz_name = settings.academic_timezone if settings else "Asia/Manila"

        self.schedule_service = AcademicScheduleService(
            data_dir=data_dir,
            school_year=school_year,
            semester=semester,
            tz_name=tz_name,
        )

    async def subject_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Discord autocomplete for /prof subject:<text> parameter."""
        try:
            term = self.schedule_service.get_term()
        except Exception as e:
            logger.debug(f"Subject autocomplete error: {e}")
            return []

        cleaned = current.strip().lower()
        choices = []

        for subject in term.subjects:
            display_name = f"{subject.code} — {subject.name}"
            # Truncate choice name to 100 chars (Discord max choice name limit)
            choice_name = display_name[:100]

            if not cleaned or cleaned in subject.code.lower() or cleaned in subject.name.lower():
                choices.append(app_commands.Choice(name=choice_name, value=subject.code))

            if len(choices) >= 25:  # Discord max choice limit is 25
                break

        return choices

    @app_commands.command(name="countdown", description="View countdown to upcoming academic milestones.")
    async def countdown(self, interaction: discord.Interaction) -> None:
        """Display remaining time until upcoming milestones."""
        from datetime import datetime, timezone

        # Configurable section milestones (UTC or local datetimes)
        MILESTONES = [
            ("Midterm Examinations", datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)),
            ("Final Project Submission", datetime(2026, 11, 28, 23, 59, tzinfo=timezone.utc)),
            ("Final Examinations", datetime(2026, 12, 10, 8, 0, tzinfo=timezone.utc)),
        ]

        now = datetime.now(timezone.utc)
        embed = discord.Embed(
            title="Academic Countdown & Milestones",
            color=discord.Color.blue(),
        )

        for name, dt in MILESTONES:
            diff = dt - now
            if diff.total_seconds() > 0:
                days = diff.days
                hours, remainder = divmod(diff.seconds, 3600)
                minutes, _ = divmod(remainder, 60)
                time_str = f"**{days}d {hours}h {minutes}m** remaining"
            else:
                time_str = "Passed / Completed"

            embed.add_field(
                name=name,
                value=f"Target: `<t:{int(dt.timestamp())}:F>`\nStatus: {time_str}",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="today", description="Show today's class schedule.")
    async def today(self, interaction: discord.Interaction) -> None:
        """Slash command /today"""
        try:
            get_term = self.schedule_service.get_term()
            term = get_term
            today_classes = self.schedule_service.get_today()
            current_dt = self.schedule_service._get_now_in_tz()
            day_name = VALID_DAYS[current_dt.weekday()]

            if not today_classes:
                await interaction.response.send_message("No classes scheduled for today.")
                return

            header = f"**Classes Today — {day_name}**\n{term.semester_name} · SY {term.school_year}\n"
            blocks = []

            for subject, meeting in today_classes:
                prof_str = f" · Prof. {subject.professor}" if subject.professor else ""
                type_str = f" ({subject.class_type})" if subject.class_type else ""
                block = (
                    f"**{format_meeting_time_range(meeting)}**\n"
                    f"{subject.code} — {subject.name}{type_str}\n"
                    f"{meeting.location}{prof_str}"
                )
                blocks.append(block)

            full_text = header + "\n\n" + "\n\n".join(blocks)
            chunks = split_message(full_text, limit=2000)

            await interaction.response.send_message(chunks[0])
            for chunk in chunks[1:]:
                await interaction.followup.send(chunk)

        except (ScheduleError, ScheduleDataNotFoundError, ScheduleValidationError) as e:
            logger.error(f"Error executing /today: {e}")
            await interaction.response.send_message("Academic schedule data is currently unavailable.")
        except Exception as e:
            logger.error(f"Unexpected error in /today: {e}", exc_info=True)
            await interaction.response.send_message("Something went wrong while fetching today's schedule.")

    @app_commands.command(name="schedule", description="Show the weekly class schedule.")
    async def schedule(self, interaction: discord.Interaction) -> None:
        """Slash command /schedule"""
        try:
            term = self.schedule_service.get_term()
            weekly_map = self.schedule_service.get_week()

            header = f"**Weekly Class Schedule**\n{term.semester_name} · SY {term.school_year}\n"
            day_sections = []

            for day in VALID_DAYS:
                meetings = weekly_map[day]
                if not meetings:
                    continue

                m_lines = []
                for subject, meeting in meetings:
                    type_str = f" ({subject.class_type})" if subject.class_type else ""
                    line = (
                        f"{format_meeting_time_range(meeting)}\n"
                        f"{subject.code} — {subject.name}{type_str}\n"
                        f"Location: {meeting.location}"
                    )
                    m_lines.append(line)

                day_sections.append(f"**{day}**\n\n" + "\n\n".join(m_lines))

            if not day_sections:
                await interaction.response.send_message("No weekly classes scheduled.")
                return

            full_text = header + "\n" + "\n\n".join(day_sections)
            chunks = split_message(full_text, limit=2000)

            await interaction.response.send_message(chunks[0])
            for chunk in chunks[1:]:
                await interaction.followup.send(chunk)

        except (ScheduleError, ScheduleDataNotFoundError, ScheduleValidationError) as e:
            logger.error(f"Error executing /schedule: {e}")
            await interaction.response.send_message("Academic schedule data is currently unavailable.")
        except Exception as e:
            logger.error(f"Unexpected error in /schedule: {e}", exc_info=True)
            await interaction.response.send_message("Something went wrong while fetching the weekly schedule.")

    @app_commands.command(name="nextclass", description="Show the next upcoming class.")
    async def nextclass(self, interaction: discord.Interaction) -> None:
        """Slash command /nextclass"""
        try:
            next_info = self.schedule_service.get_next_class()
            if not next_info:
                await interaction.response.send_message("No upcoming classes found.")
                return

            subject: Subject = next_info["subject"]
            meeting: ClassMeeting = next_info["meeting"]
            is_current: bool = next_info["is_current"]
            status_text: str = next_info["status_text"]

            header_title = "Current Class" if is_current else "Next Class"
            type_str = f" ({subject.class_type})" if subject.class_type else ""

            body = (
                f"**{header_title}**\n\n"
                f"**{subject.code} — {subject.name}{type_str}**\n"
                f"{meeting.day} · {format_meeting_time_range(meeting)}\n"
                f"Room: {meeting.location}\n"
                f"Prof. {subject.professor}\n\n"
                f"{status_text}"
            )

            await interaction.response.send_message(body)

        except (ScheduleError, ScheduleDataNotFoundError, ScheduleValidationError) as e:
            logger.error(f"Error executing /nextclass: {e}")
            await interaction.response.send_message("Academic schedule data is currently unavailable.")
        except Exception as e:
            logger.error(f"Unexpected error in /nextclass: {e}", exc_info=True)
            await interaction.response.send_message("Something went wrong while fetching the next class.")

    @app_commands.command(name="prof", description="Look up a professor by subject.")
    @app_commands.describe(subject="Subject code or name to look up.")
    @app_commands.autocomplete(subject=subject_autocomplete)
    async def prof(self, interaction: discord.Interaction, subject: str) -> None:
        """Slash command /prof subject:<text>"""
        cleaned = subject.strip()
        if not cleaned:
            await interaction.response.send_message("Subject parameter cannot be empty.", ephemeral=True)
            return

        try:
            matches = self.schedule_service.find_subjects(cleaned)

            if not matches:
                await interaction.response.send_message(
                    f"No subject found matching '{cleaned}'. Use `/schedule` to see all available subjects."
                )
                return

            if len(matches) == 1:
                subj = matches[0]
                # Collect locations
                locations = ", ".join(dict.fromkeys(m.location for m in subj.schedules))
                type_str = subj.class_type if subj.class_type else "N/A"

                res = (
                    f"**{subj.name}**\n"
                    f"`{subj.code}`\n\n"
                    f"Professor: {subj.professor}\n"
                    f"Type: {type_str}\n"
                    f"Room: {locations}"
                )
                await interaction.response.send_message(res)
                return

            # Multiple matches -> disambiguation list
            lines = [f"• `{s.code}` — {s.name}" for s in matches]
            res = (
                f"Multiple subjects matched:\n\n"
                + "\n".join(lines)
                + "\n\nUse the exact code with `/prof` for a specific result."
            )
            await interaction.response.send_message(res)

        except (ScheduleError, ScheduleDataNotFoundError, ScheduleValidationError) as e:
            logger.error(f"Error executing /prof: {e}")
            await interaction.response.send_message("Academic schedule data is currently unavailable.")
        except Exception as e:
            logger.error(f"Unexpected error in /prof: {e}", exc_info=True)
            await interaction.response.send_message("Something went wrong while looking up the professor.")



async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AcademicsCog(bot))
