import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import zoneinfo

from bot.cogs.academics import AcademicsCog
from bot.services.academic_schedule import (
    AcademicScheduleService,
    ScheduleDataNotFoundError,
    Subject,
    ClassMeeting,
)


def test_today_command_formatting():
    """Test /today slash command callback formats and sends today's schedule."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = AcademicsCog(bot)

        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.followup.send = AsyncMock()

        await cog.today.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        sent_msg = interaction.response.send_message.call_args[0][0]
        assert "**Classes Today" in sent_msg
        assert "First Semester" in sent_msg
        assert "2026-2027" in sent_msg

    asyncio.run(_test())


def test_today_command_no_classes():
    """Test /today slash command when no classes are scheduled for today."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = AcademicsCog(bot)

        # Mock Sunday datetime
        tz = zoneinfo.ZoneInfo("Asia/Manila")
        sunday_dt = datetime(2026, 8, 16, 10, 0, tzinfo=tz)
        cog.schedule_service._get_now_in_tz = MagicMock(return_value=sunday_dt)

        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()

        await cog.today.callback(cog, interaction)

        interaction.response.send_message.assert_called_once_with("No classes scheduled for today.")

    asyncio.run(_test())


def test_schedule_command_formatting():
    """Test /schedule slash command callback formats weekly schedule."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = AcademicsCog(bot)

        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.followup.send = AsyncMock()

        await cog.schedule.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        sent_msg = interaction.response.send_message.call_args[0][0]
        assert "**Weekly Class Schedule**" in sent_msg
        assert "**Monday**" in sent_msg
        assert "CIST101L — Introduction to Computing (Lab)" in sent_msg

    asyncio.run(_test())


def test_nextclass_command_formatting():
    """Test /nextclass slash command callback formats next class result."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = AcademicsCog(bot)

        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()

        await cog.nextclass.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        sent_msg = interaction.response.send_message.call_args[0][0]
        assert "Class**" in sent_msg
        assert "Room:" in sent_msg
        assert "Prof." in sent_msg

    asyncio.run(_test())


def test_prof_command_exact_match():
    """Test /prof subject:CIST_102 returns professor details."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = AcademicsCog(bot)

        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()

        await cog.prof.callback(cog, interaction, subject="CIST_102")

        interaction.response.send_message.assert_called_once()
        sent_msg = interaction.response.send_message.call_args[0][0]
        assert "**Fundamentals of Programming (Lecture)**" in sent_msg
        assert "`CIST_102`" in sent_msg
        assert "Professor: Richard Regala" in sent_msg

    asyncio.run(_test())


def test_prof_command_broad_search_disambiguation():
    """Test /prof subject:programming returns disambiguation list for multiple matches."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = AcademicsCog(bot)

        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()

        await cog.prof.callback(cog, interaction, subject="programming")

        interaction.response.send_message.assert_called_once()
        sent_msg = interaction.response.send_message.call_args[0][0]
        assert "Multiple subjects matched:" in sent_msg
        assert "• `CIST_102` — Fundamentals of Programming (Lecture)" in sent_msg
        assert "• `CIST102L` — Fundamentals of Programming (Lab)" in sent_msg
        assert "Use the exact code with `/prof` for a specific result." in sent_msg

    asyncio.run(_test())


def test_schedule_data_unavailable_handled():
    """Test commands handle ScheduleDataNotFoundError gracefully."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = AcademicsCog(bot)
        cog.schedule_service.get_term = MagicMock(side_effect=ScheduleDataNotFoundError("Missing file"))

        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()

        await cog.today.callback(cog, interaction)

        interaction.response.send_message.assert_called_once_with(
            "Academic schedule data is currently unavailable."
        )

    asyncio.run(_test())


def test_subject_autocomplete():
    """Test subject_autocomplete returns matching choices up to Discord limits."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = AcademicsCog(bot)

        interaction = MagicMock()
        choices = await cog.subject_autocomplete(interaction, current="102")

        assert len(choices) == 2
        values = {c.value for c in choices}
        assert values == {"CIST_102", "CIST102L"}

    asyncio.run(_test())


def test_countdown_command_timestamps():
    """Test /countdown command generates native unescaped Discord timestamps."""
    async def _test():
        bot = MagicMock(spec=[])
        cog = AcademicsCog(bot)

        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()

        await cog.countdown.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        embed = interaction.response.send_message.call_args.kwargs["embed"]
        assert embed.title == "Academic Countdown & Milestones"
        assert len(embed.fields) >= 3
        # Check first field contains native timestamp syntax <t:...:F> (<t:...:R>)
        field_value = embed.fields[0].value
        assert "<t:" in field_value
        assert ":F>" in field_value
        assert ":R>" in field_value
        assert "`<t:" not in field_value  # Verify no backticks

    asyncio.run(_test())
