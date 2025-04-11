import discord
from discord.ext import commands, tasks
from discord import app_commands
import requests
import json
import os
import random
import datetime
from dotenv import load_dotenv
load_dotenv()

# Setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

API_KEY = os.getenv("API_KEY")
BOOKMARKS_FILE = "bookmarks.json"

# Saved data
user_bookmarks = {}
subscriptions = {}

# Load saved bookmarks
if os.path.exists(BOOKMARKS_FILE):
    with open(BOOKMARKS_FILE, "r") as f:
        user_bookmarks = json.load(f)
        user_bookmarks = {int(k): v for k, v in user_bookmarks.items()}

# Flag & weather icons
def flag(country_code): return ''.join(chr(127397 + ord(c.upper())) for c in country_code)
def weather_icon(desc):
    desc = desc.lower()
    if "clear" in desc: return "☀️"
    if "cloud" in desc: return "☁️"
    if "rain" in desc: return "🌧️"
    if "storm" in desc: return "⛈️"
    if "snow" in desc: return "❄️"
    if "mist" in desc or "fog" in desc: return "🌫️"
    return "🌡️"

# Autocomplete suggestions
async def city_autocomplete(interaction, current):
    cities = [
        "Paris", "Delhi", "Seoul", "Tokyo", "New York", "London",
        "Mumbai", "Los Angeles", "Dubai", "Berlin", "Rome", "Bangkok",
        "Istanbul", "Cairo", "Singapore", "Toronto", "San Francisco", "Jakarta"
    ]
    return [app_commands.Choice(name=city, value=city) for city in cities if current.lower() in city.lower()][:5]

# Build weather embed
def get_weather_embed(city):
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={API_KEY}&units=metric"
    res = requests.get(url)
    data = res.json()

    if data["cod"] != 200:
        return None, f"❌ Couldn’t find the city: **{city}**."

    desc = data["weather"][0]["description"].title()
    emoji = weather_icon(desc)
    temp = data["main"]["temp"]
    feels_like = data["main"]["feels_like"]
    humidity = data["main"]["humidity"]
    wind = data["wind"]["speed"]
    country = data["sys"].get("country", "🌍")
    flag_emoji = flag(country) if len(country) == 2 else "🌍"

    embed = discord.Embed(
        title=f"{emoji} Weather in {city.title()} {flag_emoji}",
        color=discord.Color.blurple()
    )
    embed.add_field(name="Condition", value=desc, inline=False)
    embed.add_field(name="Temperature", value=f"{temp}°C (Feels like {feels_like}°C)", inline=False)
    embed.add_field(name="Humidity", value=f"{humidity}%", inline=True)
    embed.add_field(name="Wind Speed", value=f"{wind} m/s", inline=True)

    return embed, None

# On Ready
@bot.event
async def on_ready():
    print(f"✅ Weatherella is online as {bot.user}")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="weather around the world"
    ))
    try:
        synced = await tree.sync()
        for cmd in synced:
            print(f"🔹 Synced: {cmd.name}")
        print(f"🔧 Total synced: {len(synced)}")
    except Exception as e:
        print(f"❌ Sync failed: {e}")

    if not daily_weather_updates.is_running():
        daily_weather_updates.start()

# !weather command
@bot.command()
async def weather(ctx, *, city: str):
    embed, error = get_weather_embed(city)
    await ctx.send(embed=embed) if not error else await ctx.send(error)

# /weather
@tree.command(name="weather", description="Get the current weather")
@app_commands.describe(city="City name")
@app_commands.autocomplete(city=city_autocomplete)
async def slash_weather(interaction: discord.Interaction, city: str):
    await interaction.response.defer()
    embed, error = get_weather_embed(city)
    await interaction.followup.send(embed=embed) if not error else await interaction.followup.send(error)

# /savecity
@tree.command(name="savecity", description="Save a city under a name")
@app_commands.describe(name="Nickname (e.g., 'home')", city="City to save")
async def savecity(interaction, name: str, city: str):
    uid = interaction.user.id
    user_bookmarks.setdefault(uid, {})[name.lower()] = city.lower()
    with open(BOOKMARKS_FILE, "w") as f:
        json.dump(user_bookmarks, f)
    await interaction.response.send_message(f"✅ Saved **{city.title()}** as `{name}`!", ephemeral=True)

# /weather_saved
@tree.command(name="weather_saved", description="Check weather for a saved city")
@app_commands.describe(name="Your saved city name")
async def weather_saved(interaction, name: str):
    uid = interaction.user.id
    saved = user_bookmarks.get(uid, {}).get(name.lower())
    if not saved:
        await interaction.response.send_message(f"❌ You haven’t saved `{name}`.", ephemeral=True)
        return
    await interaction.response.defer()
    embed, error = get_weather_embed(saved)
    await interaction.followup.send(embed=embed) if not error else await interaction.followup.send(error)

# /mycities
@tree.command(name="mycities", description="List all your saved cities")
async def mycities(interaction):
    uid = interaction.user.id
    saved = user_bookmarks.get(uid)
    if not saved:
        await interaction.response.send_message("📭 No cities saved.", ephemeral=True)
        return
    msg = "\n".join([f"`{k}` → **{v.title()}**" for k, v in saved.items()])
    await interaction.response.send_message(f"📌 **Your Saved Cities:**\n{msg}", ephemeral=True)

# /deletecity
@tree.command(name="deletecity", description="Delete a saved city 📂")
@app_commands.describe(name="The name you saved the city under (like 'home')")
async def deletecity(interaction, name: str):
    uid = interaction.user.id
    bookmarks = user_bookmarks.get(uid, {})
    if name.lower() not in bookmarks:
        await interaction.response.send_message(f"❌ No city saved as `{name}`.", ephemeral=True)
        return
    deleted = bookmarks.pop(name.lower())
    with open(BOOKMARKS_FILE, "w") as f:
        json.dump(user_bookmarks, f)
    await interaction.response.send_message(f"🗑️ Deleted `{name}` → **{deleted.title()}**.", ephemeral=True)

# /forecast
@tree.command(name="forecast", description="Get a 3-day forecast for a city 📅")
@app_commands.describe(city="City to get the forecast for")
async def forecast(interaction, city: str):
    await interaction.response.defer()
    url = f"http://api.openweathermap.org/data/2.5/forecast?q={city}&appid={API_KEY}&units=metric"
    res = requests.get(url)
    data = res.json()

    if data["cod"] != "200":
        await interaction.followup.send(f"❌ Couldn’t get a forecast for **{city}**.")
        return

    forecasts = data["list"]
    daily_forecasts = {}

    for entry in forecasts:
        if "12:00:00" in entry["dt_txt"]:
            date = entry["dt_txt"].split()[0]
            daily_forecasts[date] = entry
        if len(daily_forecasts) >= 3:
            break

    embed = discord.Embed(
        title=f"📅 3-Day Forecast for {city.title()}",
        color=discord.Color.gold()
    )
    for date, info in daily_forecasts.items():
        desc = info["weather"][0]["description"].title()
        emoji = weather_icon(desc)
        temp = info["main"]["temp"]
        wind = info["wind"]["speed"]
        humidity = info["main"]["humidity"]
        embed.add_field(
            name=f"{emoji} {date}",
            value=f"**{desc}**\n🌡️ {temp}°C | 💨 {wind} m/s | 💧 {humidity}%",
            inline=False
        )
    await interaction.followup.send(embed=embed)

# /subscribe
@tree.command(name="subscribe", description="Get daily weather DMs 💌")
@app_commands.describe(name="Name of your saved city to subscribe to")
async def subscribe(interaction, name: str):
    uid = interaction.user.id
    saved = user_bookmarks.get(uid, {}).get(name.lower())
    if not saved:
        await interaction.response.send_message(f"❌ No saved city named `{name}`.", ephemeral=True)
        return
    subscriptions[uid] = name.lower()
    await interaction.response.send_message(f"📬 Subscribed to daily updates for `{name}`!", ephemeral=True)

# /unsubscribe
@tree.command(name="unsubscribe", description="Stop getting daily weather DMs 📴")
async def unsubscribe(interaction):
    uid = interaction.user.id
    if uid in subscriptions:
        subscriptions.pop(uid)
        await interaction.response.send_message("❌ Unsubscribed from daily updates.", ephemeral=True)
    else:
        await interaction.response.send_message("You weren’t subscribed anyway 😅", ephemeral=True)

# Background weather loop
@tasks.loop(minutes=60)
async def daily_weather_updates():
    now = datetime.datetime.now()
    if now.hour != 7:
        return
    for uid, name in subscriptions.items():
        user = bot.get_user(uid)
        city = user_bookmarks.get(uid, {}).get(name)
        if user and city:
            embed, error = get_weather_embed(city)
            if embed:
                try:
                    await user.send(embed=embed)
                except:
                    pass  # ignore if DMs are blocked

# Run the bot
bot.run(os.getenv("TOKEN"))

