import discord
from discord.ext import commands, tasks
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

import os
from dotenv import load_dotenv, find_dotenv

print("CWD:", os.getcwd())
print("find_dotenv() returns:", find_dotenv())
print("File exists at that path:", os.path.exists(find_dotenv()) if find_dotenv() else False)

loaded = load_dotenv()
print("load_dotenv() returned:", loaded)

token = os.getenv("DISCORD_TOKEN")
print("Token is None?", token is None)
print("Token length:", len(token) if token else 0)
print("First 10 chars:", token[:10] if token else "N/A")

load_dotenv()

# ============ CONFIGURATION ============
# Replace this with the specific user's Discord ID (right-click user > Copy ID)
TARGET_USER_ID = 1186183156651536487

# Replace with the ID of the role that allows @everyone pings.
EVERYONE_ROLE_ID = 1554355429109272596

# How many pings before punishment?
PING_LIMIT = 5

# Where to store the ping data
DATA_FILE = "ping_data.json"
# =======================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Required to manage roles

bot = commands.Bot(command_prefix="!", intents=intents)


# ---------- Data handling ----------
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


def get_user_data(data, user_id):
    """Ensure the user has an entry and return it."""
    key = str(user_id)
    if key not in data:
        data[key] = {
            "count": 0,
            "punished_until": None  # ISO date string (next day at midnight)
        }
    return data[key]


def next_midnight():
    """Return a datetime for the start of the next day (local time)."""
    tomorrow = datetime.now() + timedelta(days=1)
    return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)


# ---------- Events ----------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    check_punishments.start()


@bot.event
async def on_message(message):
    # Ignore bot's own messages
    if message.author.bot:
        return

    # Only track the target user
    if message.author.id != TARGET_USER_ID:
        await bot.process_commands(message)
        return

    # Check if they pinged @everyone (or @here)
    if message.mention_everyone:
        data = load_data()
        user_data = get_user_data(data, message.author.id)

        # If they're currently punished, just let them know
        if user_data["punished_until"]:
            punish_end = datetime.fromisoformat(user_data["punished_until"])
            if datetime.now() < punish_end:
                await message.channel.send(
                    f"Looks like this was not something fate has stored for you {message.author.mention}, you've hit the limit. "
                    f"You'll get your role back on **{punish_end.strftime('%B %d at %I:%M %p')}**."
                )
                return
            else:
                # Punishment expired — reset (the background task normally handles this,
                # but this is a safety net)
                user_data["punished_until"] = None
                user_data["count"] = 0

        # Increment ping count
        user_data["count"] += 1
        count = user_data["count"]
        save_data(data)

        if count < PING_LIMIT:
            await message.channel.send(
                f"{message.author.mention}, you have pinged everyone **{count}** time(s) now. "
                f"You have {PING_LIMIT - count} more before your fate will be sealed."
            )
        else:
            # They hit the limit — remove the role
            guild = message.guild
            role = guild.get_role(EVERYONE_ROLE_ID)
            member = message.author

            if role and role in member.roles:
                try:
                    await member.remove_roles(role, reason=f"Pinged everyone {PING_LIMIT} times")
                except discord.Forbidden:
                    await message.channel.send(
                        "I don't have permission to remove that role. "
                        "Make sure my bot role is higher than the role I'm removing."
                    )
                    return

            # Set punishment to end at next midnight
            punish_end = next_midnight()
            user_data["punished_until"] = punish_end.isoformat()
            save_data(data)

            await message.channel.send(
                f"{message.author.mention}, you just hit your everyone ping limit! "
                f"Your fate shall be sealed! No more everyone pings! Don't worry, you can always do it again in the future. "
                f"**{punish_end.strftime('%B %d at %I:%M %p')}**."
            )

    await bot.process_commands(message)


# ---------- Background task: restore roles ----------
@tasks.loop(minutes=1)
async def check_punishments():
    """Every minute, check if any punished users have reached the next day."""
    data = load_data()
    now = datetime.now()
    changed = False

    for user_id, user_data in data.items():
        if user_data.get("punished_until"):
            punish_end = datetime.fromisoformat(user_data["punished_until"])

            if now >= punish_end:
                # Time's up — give the role back on every server the bot is in
                for guild in bot.guilds:
                    member = guild.get_member(int(user_id))
                    role = guild.get_role(EVERYONE_ROLE_ID)

                    if member and role and role not in member.roles:
                        try:
                            await member.add_roles(role, reason="Punishment served")
                            print(f"Restored role to {member} in {guild.name}")
                        except discord.Forbidden:
                            print(f"Couldn't restore role in {guild.name} — check permissions.")

                # Reset their data
                user_data["count"] = 0
                user_data["punished_until"] = None
                changed = True

    if changed:
        save_data(data)


bot.run(os.getenv("DISCORD_TOKEN"))
