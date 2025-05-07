import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta, timezone
import json
import pytz
from pytz import timezone as pytz_timezone, utc, all_timezones
import os
import asyncio
from discord import app_commands, Interaction
from dateutil import parser
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# Load configuration values from a JSON file
with open("config.json") as f:
    config = json.load(f)

TOKEN = config["TOKEN"]
GUILD_ID = config["GUILD_ID"]
EVENT_CHANNEL_ID = config["EVENT_CHANNEL_ID"]
HORROR_ROLE_ID = config["HORROR_ROLE_ID"]

# Set up bot intents and create a bot instance
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
scheduler = AsyncIOScheduler()  # Scheduler to run tasks at specified times

# Utility Functions

def parse_event_time(event_datetime_str, user_tz):
    """Helper to parse and convert event datetime to a user's timezone."""
    try:
        event_time = datetime.fromisoformat(event_datetime_str).astimezone(utc)
        if event_time.tzinfo is None:
            event_time = utc.localize(event_time)  # Localize to UTC if not timezone-aware
        local_time = event_time.astimezone(user_tz)  # Convert to user’s local timezone
        return local_time
    except Exception as ex:
        logger.error(f"Error parsing event datetime: {event_datetime_str} - {ex}")
        return None


# Function to get a user's timezone from stored data
def get_user_timezone(user_id):
    timezones = load_timezones()
    tz_name = timezones.get(str(user_id))
    if not tz_name:
        raise ValueError("No timezone set for user.")
    
    try:
        return pytz_timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        return utc

# Load event data from a file
def load_events():
    if not os.path.exists("log_entries.json"):
        return []
    with open("log_entries.json", "r") as f:
        return json.load(f)

# Save event data to a file
def save_events(events):
    with open("log_entries.json", "w") as f:
        json.dump(events, f, indent=2)

# Load user timezones from file
def load_timezones():
    if not os.path.exists("timezone.json"):
        return {}
    try:
        with open("timezone.json", "r") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            else:
                logger.error("timezone.json is not a dictionary. Resetting...")
                return {}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to load timezone.json: {e}")
        return {}

# Save timezones to a file
def save_timezones(timezones):
    with open("timezone.json", "w") as f:
        json.dump(timezones, f, indent=2)

# Scheduler Task: Send a reminder message about an event
async def send_reminder(event):
    try:
        channel = bot.get_channel(EVENT_CHANNEL_ID)
        if not channel:
            raise ValueError("Channel not found")
        guild = bot.get_guild(GUILD_ID)
        if not guild:
            raise ValueError("Guild not found")
        horror_role = guild.get_role(HORROR_ROLE_ID)
        if not horror_role:
            raise ValueError("Horror role not found")

        await channel.send(
            f"⚠️ **SOL-1 Log Transmission**\n"
            f"{horror_role.mention}, anomaly report detected.\n"
            f"Scheduled Event: **{event['game']}**\n"
            f"Commencement ETA: 30 minutes\n"
            f"Notes: {event.get('notes', 'No further data.')}\n"
            f"End of transmission."
        )
    except Exception as e:
        logger.error(f"Failed to send reminder: {e}")


# Function to schedule a reminder for a future event
def schedule_reminder(event):
    event_time = datetime.fromisoformat(event["datetime"]).astimezone(utc) - timedelta(minutes=30)
    if event_time > datetime.now(utc):
        scheduler.add_job(send_reminder, 'date', run_date=event_time, args=[event])

# Dropdown for game selection and scheduling
class GameDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Phasmophobia", value="Phasmophobia"),
            discord.SelectOption(label="Demonologist", value="Demonologist"),
            discord.SelectOption(label="REPO", value="REPO"),
            discord.SelectOption(label="Lethal Company", value="Lethal Company"),
            discord.SelectOption(label="Backrooms: Escape Together", value="Backrooms: Escape Together"),
            discord.SelectOption(label="Content Warning", value="Content Warning"),
            discord.SelectOption(label="Panicore", value="Panicore"),  
            discord.SelectOption(label="The Headliners", value="The Headliners")
        ]
        super().__init__(placeholder="Choose a game...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: Interaction):
        view = self.view
        view.selected_game = self.values[0]
        await interaction.response.send_modal(ScheduleModal(game=self.values[0]))  # Show modal to schedule the event

class GameDropdownView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.selected_game = None
        self.add_item(GameDropdown())

# Modal to handle event scheduling
class ScheduleModal(discord.ui.Modal):
    def __init__(self, game: str):
        super().__init__(title="Schedule Event")
        self.game = game
        self.add_item(discord.ui.InputText(label="Event Date & Time (YYYY-MM-DD HH:MM)", placeholder="2025-05-06 20:00"))
        self.add_item(discord.ui.InputText(label="Event Notes", placeholder="Additional details..."))

    def parse_natural_datetime(text, user_tz):
        """
        Parses a date/time string like 'April 6 8:30pm', 'May 7-2025 19:00', or 'Next Friday at 9pm'
        and returns a timezone-aware datetime in the user's timezone.
        """
        # Normalize input by replacing hyphens with spaces
        text = text.replace('-', ' ')  # This ensures 'May 7-2025' becomes 'May 7 2025'

        # Try different formats for parsing
        formats = [
            "%B %d %Y %I:%M%p",  # 12-hour format with AM/PM (e.g., 'May 7 2025 8:30pm')
            "%B %d %Y %H:%M",    # 24-hour format (e.g., 'May 7 2025 19:00')
            "%B %d %Y %I:%M %p",  # 12-hour format with AM/PM and a space (e.g., 'May 7 2025 8:30 PM')
            "%B %d %Y %H:%M",    # 24-hour format without hyphen (e.g., 'May 7 2025 19:00')
        ]

        # Try each format until one matches
        for fmt in formats:
            try:
                dt = datetime.strptime(text, fmt)  # Try parsing with the current format
                if dt.tzinfo is None:  # If the datetime has no timezone, localize it
                    dt = user_tz.localize(dt)
                else:
                    dt = dt.astimezone(user_tz)
                return dt
            except ValueError:
                continue  # If parsing fails, try the next format

        # If none of the formats worked, raise an exception
        raise ValueError(f"Could not parse date/time: {text}")



# Example usage in your schedule modal (assuming `user_tz` is the user's timezone)
async def on_submit(self, interaction: discord.Interaction):
    date_input = self.children[0].value.strip()
    time_input = self.children[1].value.strip()
    notes_input = self.children[2].value.strip()

    # Combine the date and time inputs into one string
    combined_input = f"{date_input} {time_input}"

    try:
        # Get the user's timezone
        user_tz = get_user_timezone(interaction.user.id)

        # Try to parse the combined input
        event_dt = parse_natural_datetime(combined_input, user_tz)

        # Check if the event time is in the past
        if event_dt < datetime.now(user_tz):
            await interaction.response.send_message("❌ You can't schedule an event in the past.", ephemeral=True)
            return

        event = {
            "author": interaction.user.id,
            "game": self.game,
            "datetime": event_dt.astimezone(pytz.utc).isoformat(),
            "notes": notes_input
        }

        # Load existing events, append the new event, and save it
        events = load_events()
        events.append(event)
        save_events(events)

        # Schedule reminder
        schedule_reminder(event)

        await interaction.response.send_message(
            f"✅ Scheduled **{self.game}** on {event_dt.strftime('%B %d, %Y at %I:%M %p (%Z)')}\n📝 Notes: {notes_input or 'None'}",
            ephemeral=True
        )

    except ValueError as e:
        # Handle parsing errors and send user-friendly feedback
        logger.error(f"Failed to parse input: {e}")
        await interaction.response.send_message(
            "❌ Failed to parse your input. Please ensure it follows a format like `Month Day Year Time` (e.g., `May 7 2025 8:30pm`).", 
            ephemeral=True
        )
    except Exception as e:
        # General error handling
        logger.error(f"Error scheduling event: {e}")
        await interaction.response.send_message("❌ An error occurred while scheduling your event.", ephemeral=True)

# Slash Commands

@tree.command(name="settimezone", description="Set your timezone for event scheduling.")
@app_commands.describe(zone="Enter a timezone like 'America/New_York'")
async def settimezone(interaction: discord.Interaction, zone: str):
    if zone not in all_timezones:
        await interaction.response.send_message("❌ Invalid timezone. Use a format like America/New_York.", ephemeral=True)
        return

    timezones = load_timezones()
    timezones[str(interaction.user.id)] = zone
    save_timezones(timezones)
    await interaction.response.send_message(f"✅ Timezone set to {zone}.", ephemeral=True)

@tree.command(name="mytimezone", description="Check your currently set timezone.")
async def mytimezone(interaction: discord.Interaction):
    tz = get_user_timezone(interaction.user.id)
    await interaction.response.send_message(f"🕒 Your current timezone is {tz.zone}.", ephemeral=True)

@tree.command(name="next", description="Show the next upcoming horror game event.")
async def next_event(interaction: Interaction):
    events = load_events()
    now = datetime.now(utc)
    upcoming = []

    for e in events:
        try:
            local_time = parse_event_time(e["datetime"], get_user_timezone(interaction.user.id))
            if local_time and local_time > now:
                upcoming.append((local_time, e))
        except Exception as ex:
            logger.error(f"Error parsing event datetime: {e['datetime']} - {ex}")
            continue

    if not upcoming:
        await interaction.response.send_message("📭 No upcoming events found.", ephemeral=True)
        return

    upcoming.sort(key=lambda x: x[0])
    next_dt, event = upcoming[0]
    author = await bot.fetch_user(event['author'])
    await interaction.response.send_message(
        f"📅 **Next Horror Event:**\n"
        f"🎮 Game: **{event['game']}**\n"
        f"🕒 Time: {next_dt.strftime('%B %d, %Y at %I:%M %p (%Z)')}\n"
        f"📝 Notes: {event.get('notes', 'None')}\n"
        f"👤 Scheduled by: {author.mention}"
    )

@tree.command(name="listevents", description="View all upcoming horror game events.")
async def list_events(interaction: Interaction):
    events = load_events()
    now = datetime.now(utc)
    upcoming = []

    for e in events:
        try:
            local_time = parse_event_time(e["datetime"], get_user_timezone(interaction.user.id))
            if local_time and local_time > now:
                upcoming.append((local_time, e))
        except Exception as ex:
            logger.error(f"Error parsing event datetime: {e['datetime']} - {ex}")
            continue

    if not upcoming:
        await interaction.response.send_message("📭 No upcoming events found.", ephemeral=True)
        return

    upcoming.sort(key=lambda x: x[0])
    msg = "🗓 **Upcoming Events:**\n"
    for local_time, event in upcoming:
        user = await bot.fetch_user(event['author'])
        msg += (
            f"\n• **{event['game']}** on {local_time.strftime('%B %d at %I:%M %p %Z')} "
            f"(Scheduled by {user.mention})"
        )
    await interaction.response.send_message(msg)

# Admin command to clear past events
@tree.command(name="clearevents", description="Remove all past events from storage.")
async def clearevents(interaction: Interaction):
    allowed_roles = ["Admin", "Moderator"]
    member = interaction.user if isinstance(interaction.user, discord.Member) else await interaction.guild.fetch_member(interaction.user.id)

    if not any(role.name in allowed_roles for role in member.roles):
        await interaction.response.send_message("🚫 You don't have permission to use this command.", ephemeral=True)
        return

    now = datetime.now(utc)
    events = load_events()
    future_events = [e for e in events if parse_event_time(e["datetime"], utc) > now]
    save_events(future_events)
    await interaction.response.send_message(
        f"🧹 Cleared past events. {len(events) - len(future_events)} removed, {len(future_events)} remain.",
        ephemeral=True
    )

# Bot Events

@bot.event
async def on_ready():
    await tree.sync()
    logger.info(f"{bot.user} is online and commands are synced!")
    await asyncio.sleep(1)

    try:
        synced = await tree.sync(guild=discord.Object(id=GUILD_ID))
        logger.info(f"Synced {len(synced)} command(s).")
    except Exception as e:
        logger.error(f"Slash command sync failed: {e}")

    events = load_events()
    now = datetime.now(utc)
    for event in events:
        try:
            event_time = datetime.fromisoformat(event["datetime"]).astimezone(utc) - timedelta(minutes=30)
            if event_time > now:
                schedule_reminder(event)
        except Exception as e:
            logger.error(f"Error processing event {event}: {e}")
    scheduler.start()

# Start the bot
bot.run(TOKEN)
