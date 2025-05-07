# Imports
import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta, timezone
import json
import pytz
from pytz import all_timezones

import os
import asyncio
from discord import app_commands, Interaction
from pytz import timezone as pytz_timezone, utc, all_timezones

# Load configuration values from a JSON file
with open("config.json") as f:
    config = json.load(f)

# Config variables to access the bot token, guild ID, event channel ID, and horror role ID
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
from pytz import timezone as pytz_timezone, UnknownTimeZoneError

# Function to get a user's timezone from stored data
def get_user_timezone(user_id):
    timezones = load_timezones()  # Load saved timezones from file

    tz_name = timezones.get(str(user_id))
    if not tz_name:
        raise ValueError("No timezone set for user.")
    
    try:
        return pytz_timezone(tz_name)  # Return timezone object for the user's timezone
    except UnknownTimeZoneError:
        return utc  # Return UTC if the timezone is invalid

# Load event data from a file
def load_events():
    if not os.path.exists("log_entries.json"):
        return []  # Return empty list if no events file exists
    with open("log_entries.json", "r") as f:
        return json.load(f)

# Save event data to a file
def save_events(events):
    with open("log_entries.json", "w") as f:
        json.dump(events, f, indent=2)

# Load user timezones from file
def load_timezones():
    if not os.path.exists("timezone.json"):
        return {}  # Return empty dictionary if no timezone file exists
    try:
        with open("timezone.json", "r") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            else:
                print("[ERROR] timezone.json is not a dictionary. Resetting...")
                return {}
    except json.JSONDecodeError as e:
        print(f"[ERROR] Failed to load timezone.json: {e}")
        return {}

# Scheduler Task: Send a reminder message about an event
async def send_reminder(event):
    channel = bot.get_channel(EVENT_CHANNEL_ID)  # Get the event channel
    guild = bot.get_guild(GUILD_ID)  # Get the server (guild)
    horror_role = guild.get_role(HORROR_ROLE_ID)  # Get the horror role

    # Send the reminder message with event details
    await channel.send(
        f"⚠️ **SOL-1 Log Transmission**\n"
        f"{horror_role.mention}, anomaly report detected.\n"
        f"Scheduled Event: **{event['game']}**\n"
        f"Commencement ETA: 30 minutes\n"
        f"Notes: {event.get('notes', 'No further data.')}\n"
        f"End of transmission."
    )

# Function to schedule a reminder for a future event
def schedule_reminder(event):
    event_time = datetime.fromisoformat(event["datetime"]).astimezone(utc) - timedelta(minutes=30)
    if event_time > datetime.now(utc):
        scheduler.add_job(send_reminder, 'date', run_date=event_time, args=[event])

# Save timezones to a file
def save_timezones(timezones):
    with open("timezone.json", "w") as f:
        json.dump(timezones, f, indent=2)

# Slash Commands

# Command to set the user's timezone
@tree.command(name="settimezone", description="Set your timezone for event scheduling.")
@app_commands.describe(zone="Enter a timezone like 'America/New_York'")
async def settimezone(interaction: discord.Interaction, zone: str):
    if zone not in all_timezones:  # Validate the timezone input
        await interaction.response.send_message("❌ Invalid timezone. Use a format like America/New_York.", ephemeral=True)
        return

    timezones = load_timezones()  # Load the current timezones
    timezones[str(interaction.user.id)] = zone  # Save the user's timezone
    save_timezones(timezones)
    await interaction.response.send_message(f"✅ Timezone set to {zone}.", ephemeral=True)

# Command to check the user's current timezone
@tree.command(name="mytimezone", description="Check your currently set timezone.")
async def mytimezone(interaction: discord.Interaction):
    tz = get_user_timezone(interaction.user.id)  # Get the user's timezone
    await interaction.response.send_message(f"🕒 Your current timezone is {tz.zone}.", ephemeral=True)

# Command to show the next upcoming horror game event
@tree.command(name="next", description="Show the next upcoming horror game event.")
async def next_event(interaction: Interaction):
    events = load_events()  # Load all saved events
    now = datetime.now(utc)  # Get the current time

    upcoming = []
    for e in events:
        try:
            event_time = datetime.fromisoformat(e["datetime"]).astimezone(utc)  # Convert event datetime to UTC

            if event_time.tzinfo is None:
                event_time = utc.localize(event_time)  # Localize to UTC if no timezone info is present

            if event_time > now:
                upcoming.append((event_time, e))  # Append to upcoming events list if event is in the future
        except Exception as ex:
            print(f"Error parsing event datetime: {e['datetime']} - {ex}")
            continue

    if not upcoming:
        await interaction.response.send_message("📭 No upcoming events found.", ephemeral=True)
        return

    upcoming.sort(key=lambda x: x[0])  # Sort events by their time
    next_dt, event = upcoming[0]  # Get the next event
    author = await bot.fetch_user(event['author'])  # Fetch the user who scheduled the event
    local_time = next_dt.astimezone(get_user_timezone(interaction.user.id))  # Convert to user's local time

    # Send the event details to the user
    await interaction.response.send_message(
        f"📅 **Next Horror Event:**\n"
        f"🎮 Game: **{event['game']}**\n"
        f"🕒 Time: {local_time.strftime('%B %d, %Y at %I:%M %p (%Z)')}\n"
        f"📝 Notes: {event.get('notes', 'None')}\n"
        f"👤 Scheduled by: {author.mention}"
    )

# Command to list all events
@tree.command(name="listevents", description="View all upcoming horror game events.")
async def list_events(interaction: Interaction):
    events = load_events()
    now = datetime.now(utc)
    upcoming = []

    for e in events:
        try:
            event_time = datetime.fromisoformat(e["datetime"]).astimezone(utc)
            if event_time > now:
                upcoming.append((event_time, e))
        except Exception as ex:
            print(f"Error parsing event datetime: {e['datetime']} - {ex}")
            continue

    if not upcoming:
        await interaction.response.send_message("📭 No upcoming events found.", ephemeral=True)
        return

    upcoming.sort(key=lambda x: x[0])
    tz = get_user_timezone(interaction.user.id)
    msg = "🗓 **Upcoming Events:**\n"
    for event_time, e in upcoming:
        local_time = event_time.astimezone(tz)
        user = await bot.fetch_user(e['author'])
        msg += (
            f"\n• **{e['game']}** on {local_time.strftime('%B %d at %I:%M %p %Z')} "
            f"(Scheduled by {user.mention})"
        )
    await interaction.response.send_message(msg)

# Command to clear all events admins/mods only
@tree.command(name="clearevents", description="Remove all past events from storage.")
async def clearevents(interaction: Interaction):
    # Define allowed role names or IDs
    allowed_roles = ["Admin", "Moderator"]  # You can also use role IDs like [1234567890]

    # Check if user has at least one allowed role
    member = interaction.user if isinstance(interaction.user, discord.Member) else await interaction.guild.fetch_member(interaction.user.id)

    if not any(role.name in allowed_roles for role in member.roles):
        await interaction.response.send_message("🚫 You don't have permission to use this command.", ephemeral=True)
        return

    now = datetime.now(utc)
    events = load_events()
    future_events = []

    for e in events:
        try:
            event_time = datetime.fromisoformat(e["datetime"]).astimezone(utc)
            if event_time > now:
                future_events.append(e)
        except Exception as ex:
            print(f"Error checking event datetime: {e['datetime']} - {ex}")

    save_events(future_events)
    await interaction.response.send_message(
        f"🧹 Cleared past events. {len(events) - len(future_events)} removed, {len(future_events)} remain.",
        ephemeral=True
    )


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

# Modal to schedule an event after game selection
class ScheduleModal(discord.ui.Modal, title="Schedule Horror Game"):
    def __init__(self, game: str):
        super().__init__()
        self.game = game
        self.add_item(discord.ui.TextInput(label="Date (e.g. April-16)", custom_id="date"))
        self.add_item(discord.ui.TextInput(label="Time (e.g. 8:30pm)", custom_id="time"))
        self.add_item(discord.ui.TextInput(label="Notes (optional)", custom_id="notes", required=False))

    async def on_submit(self, interaction: discord.Interaction):
        date = self.children[0].value
        time = self.children[1].value
        notes = self.children[2].value
        print(f"🗓 Date: {date}, Time: {time}, Notes: {notes}")

        # Get the user's timezone
        user_tz = get_user_timezone(interaction.user.id)
        if user_tz is None:
            await interaction.response.send_message(
                "⚠️ Please set your timezone first using /settimezone <timezone>.",
                ephemeral=True
            )
            return

        try:
            # Get the current year to avoid issues with incomplete date format
            current_year = datetime.now(user_tz).year
            # Parse the date and time (handle missing year in input by using current year)
            naive_dt = datetime.strptime(f"{date}-{current_year} {time}", "%B-%d-%Y %I:%M%p")

            # Localize the naive datetime to the user's timezone
            local_dt = user_tz.localize(naive_dt)

            # Convert to UTC
            utc_dt = local_dt.astimezone(utc)

            # Check if the event is in the future
            if utc_dt < datetime.now(utc):
                await interaction.response.send_message(
                    "⚠️ Cannot schedule past events. Please provide a future time.",
                    ephemeral=True
                )
                return

            # Create the event object
            event = {
                "game": self.game,
                "datetime": utc_dt.isoformat(),
                "notes": notes,
                "author": interaction.user.id
            }

            # Log the event to the console
            print("📦 Saving event:", event)

            # Save event to file
            events = load_events()
            events.append(event)
            save_events(events)

            # Schedule a reminder 30 minutes before the event
            schedule_reminder(event)

            # Confirm the scheduling to the user
            await interaction.response.send_message(
                f"✅ Scheduled **{self.game}** for {local_dt.strftime('%B %d at %I:%M %p %Z')}\n"
                f"Notes: {notes if notes else 'None'}"
            )

        except ValueError as e:
            await interaction.response.send_message(
                "❌ Could not parse date/time. Use format: Month-Day Time (e.g., August-17 8:30pm).",
                ephemeral=True
            )
            print(f"Error parsing date/time: {e}")
            return

# Command to start scheduling an event using dropdown
@tree.command(name="schedule", description="Schedule a horror game event using dropdown")
async def schedule_event(interaction: Interaction):
    await interaction.response.send_message("Select a game to schedule:", view=GameDropdownView(), ephemeral=True)


# Message Commands for scheduling events and listing events
@bot.command()
async def schedule(ctx, game: str, date: str, time: str, *, notes=None):
    user_tz = get_user_timezone(ctx.author.id)  # Get the user's timezone

    try:
        current_year = datetime.now(user_tz).year
        naive_dt = datetime.strptime(f"{date}-{current_year} {time}", "%B-%d-%Y %I:%M%p")
        local_dt = user_tz.localize(naive_dt)
        utc_dt = local_dt.astimezone(utc)
    except Exception:
        await ctx.send("❌ [SOL-1] Temporal input invalid. Use !schedule <game> <Month-Day> <HH:MMam/pm> [notes]")
        return

    if utc_dt < datetime.now(utc):
        await ctx.send("⚠️ [SOL-1] Cannot schedule past anomalies. Use a future time.")
        return

    event = {
        "game": game,
        "datetime": utc_dt.isoformat(),
        "notes": notes,
        "author": ctx.author.id
    }

    events = load_events()
    events.append(event)
    save_events(events)
    schedule_reminder(event)

    await ctx.send(
        f"📡 [SOL-1] Log entry accepted.\n"
        f"Event: **{game}** scheduled for {utc_dt.strftime('%B %d at %I:%M %p')} UTC.\n"
        f"Notification beacon primed (T-minus 30 min)."
    )

@bot.command()
async def list(ctx):
    events = load_events()  # Load all events
    now = datetime.now(utc)  # Get current time
    upcoming_events = []

    # Filter upcoming events
    for event in events:
        try:
            event_time = datetime.fromisoformat(event["datetime"]).astimezone(utc)
            if event_time > now:
                upcoming_events.append(event)
        except Exception as e:
            print(f"Error parsing datetime for event: {event} - {e}")
            continue

    if not upcoming_events:
        await ctx.send("❌ No upcoming events found.")
        return

    msg = "📅 **Upcoming Events:**\n"
    for event in upcoming_events:
        event_time = datetime.fromisoformat(event["datetime"]).astimezone(utc)
        msg += (
            f"**{event['game']}** - {event_time.strftime('%B %d at %I:%M %p UTC')}\n"
            f"Notes: {event.get('notes', 'No further data.')}\n"
            f"Scheduled by: <@{event['author']}>\n\n"
        )
    await ctx.send(msg)

# Bot Events

# Event when the bot is ready (on startup)
@bot.event
async def on_ready():
    await tree.sync()  # Sync commands
    print(f"{bot.user} is online and commands are synced!")
    print(f"[SOL-1] Core AI online. Surveillance initialized.")
    await asyncio.sleep(1)

    try:
        synced = await tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"[SOL-1] Synced {len(synced)} command(s).")
    except Exception as e:
        print(f"[SOL-1] Slash command sync failed: {e}")

    # Reschedule any events that require reminders
    events = load_events()
    now = datetime.now(utc)
    for event in events:
        try:
            event_time = datetime.fromisoformat(event["datetime"]).astimezone(utc) - timedelta(minutes=30)
            if event_time > now:
                schedule_reminder(event)
        except Exception as e:
            print(f"Error processing event {event}: {e}")
    scheduler.start()  # Start the scheduler to handle tasks

# Start the bot
bot.run(TOKEN)