import os
import asyncio

from flask import Flask, request, jsonify
import telegram
from shazamio import Shazam, GenreMusic

"""
This serverless Telegram bot uses the ShazamIO library to surface music charts.
When deployed to Vercel, it listens for Telegram webhook events at `/api`.

Commands:
  /start                                 – show help text with available commands.
  /top <country_code> [limit]            – return the top songs for a country (e.g. /top us 10).
  /world [limit]                         – return the top songs globally.
  /genre <country_code> <genre> [limit]  – return the top songs for a genre in a country.
  /search <query>                        – search for songs, albums or artists by name.

Environment:
  BOT_TOKEN must be set to your Telegram bot token.
"""

# Initialise Flask app and Telegram bot
app = Flask(__name__)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set.")

bot = telegram.Bot(token=BOT_TOKEN)
shazam = Shazam()


def format_tracks(tracks):
    """
    Convert a list of track dictionaries into a numbered list of strings.

    Parameters
    ----------
    tracks : list
        List of tracks returned from ShazamIO API.

    Returns
    -------
    str
        Human‑readable list with index, title and subtitle.
    """
    lines = []
    for idx, track in enumerate(tracks, start=1):
        title = track.get("title") or track.get("heading", {}).get("title", "Unknown")
        subtitle = track.get("subtitle") or track.get("heading", {}).get("subtitle", "")
        lines.append(f"{idx}. {title} – {subtitle}")
    return "\n".join(lines)


async def get_top_world_tracks(limit=10):
    """Fetch global top tracks."""
    return await shazam.top_world_tracks(limit=limit)


async def get_top_country_tracks(country_code, limit=10):
    """Fetch top tracks in a specific country."""
    return await shazam.top_country_tracks(country_code.upper(), limit)


async def get_top_country_genre_tracks(country_code, genre: GenreMusic, limit=10):
    """Fetch top tracks of a genre within a country."""
    return await shazam.top_country_genre_tracks(country_code.upper(), genre, limit=limit)


async def search_tracks(query, limit=5):
    """Search for tracks by query."""
    return await shazam.search_track(query=query, limit=limit)


@app.route("/api", methods=["POST"])
def telegram_webhook():
    """
    Handle incoming Telegram webhook updates.

    This function parses the incoming update, determines which command was
    requested, fetches the appropriate data from Shazam and replies back to
    the user. All asynchronous Shazam calls are run synchronously via
    asyncio.run() since Flask does not support async routes.
    """
    update_json = request.get_json(force=True)
    update = telegram.Update.de_json(update_json, bot)

    if update.message:
        chat_id = update.message.chat.id
        text = (update.message.text or "").strip()

        # /start command – show help text
        if text.startswith("/start"):
            help_text = (
                "مرحبًا! هذا البوت يسمح لك باستكشاف مخططات شازام للموسيقى.\n"
                "الأوامر المتاحة:\n"
                "/top <رمز_الدولة> [عدد] – أفضل الأغاني في بلد ما (مثل /top us 10).\n"
                "/world [عدد] – أفضل الأغاني عالميًا.\n"
                "/genre <رمز_الدولة> <نوع> [عدد] – أفضل الأغاني حسب النوع في البلد.\n"
                "/search <كلمة البحث> – البحث عن أغنية أو فنان أو ألبوم.\n"
            )
            bot.send_message(chat_id=chat_id, text=help_text)
            return jsonify({"status": "ok"})

        # /top command – top tracks in a country
        if text.startswith("/top"):
            parts = text.split()
            country = parts[1] if len(parts) > 1 else "us"
            # default to 10 results if limit not provided
            limit = 10
            if len(parts) > 2 and parts[2].isdigit():
                limit = int(parts[2])
            # run async call synchronously
            data = asyncio.run(get_top_country_tracks(country, limit))
            tracks = data.get("tracks", [])
            reply = f"أفضل {limit} أغاني في {country.upper()}:\n{format_tracks(tracks)}"
            bot.send_message(chat_id=chat_id, text=reply)
            return jsonify({"status": "ok"})

        # /world command – global top tracks
        if text.startswith("/world"):
            parts = text.split()
            limit = 10
            if len(parts) > 1 and parts[1].isdigit():
                limit = int(parts[1])
            data = asyncio.run(get_top_world_tracks(limit))
            tracks = data.get("tracks", [])
            reply = f"أفضل {limit} أغاني عالمية:\n{format_tracks(tracks)}"
            bot.send_message(chat_id=chat_id, text=reply)
            return jsonify({"status": "ok"})

        # /genre command – top tracks by genre in a country
        if text.startswith("/genre"):
            parts = text.split()
            if len(parts) < 3:
                bot.send_message(
                    chat_id=chat_id,
                    text="صيغة الأمر: /genre <رمز_الدولة> <نوع> [عدد]",
                )
                return jsonify({"status": "ok"})
            country = parts[1]
            genre_name = parts[2]
            limit = 10
            if len(parts) > 3 and parts[3].isdigit():
                limit = int(parts[3])

            # map human-friendly genre names to GenreMusic enums
            # allow using either enum name or value (e.g. hip-hop-rap or HIP_HOP_RAP)
            # spaces or underscores are replaced with hyphens/underscores accordingly
            normalized = genre_name.strip().upper().replace("-", "_").replace(" ", "_")
            try:
                genre_enum = GenreMusic[normalized]
            except KeyError:
                # try mapping directly by value
                try:
                    genre_enum = GenreMusic(normalized.lower().replace("_", "-"))
                except Exception:
                    valid = ", ".join([g.value for g in GenreMusic])
                    bot.send_message(
                        chat_id=chat_id,
                        text=(
                            "نوع غير صالح. الأنواع المتاحة:\n"
                            f"{valid}"
                        ),
                    )
                    return jsonify({"status": "ok"})
            data = asyncio.run(
                get_top_country_genre_tracks(country, genre_enum, limit)
            )
            tracks = data.get("tracks", [])
            reply = (
                f"أفضل {limit} أغاني {genre_enum.value.replace('-', ' ')} "
                f"في {country.upper()}:\n{format_tracks(tracks)}"
            )
            bot.send_message(chat_id=chat_id, text=reply)
            return jsonify({"status": "ok"})

        # /search command – search for tracks by query
        if text.startswith("/search"):
            query = text[len("/search") :].strip()
            if not query:
                bot.send_message(
                    chat_id=chat_id,
                    text="اكتب اسم الأغنية أو الفنان بعد الأمر /search",
                )
                return jsonify({"status": "ok"})
            data = asyncio.run(search_tracks(query, limit=5))
            # search_track returns a dict that may include 'tracks' key or 'song_hits'
            # Attempt to find tracks list in typical keys
            tracks = []
            if isinstance(data, dict):
                if "tracks" in data and isinstance(data["tracks"], list):
                    tracks = data["tracks"]
                elif "song_hits" in data and isinstance(data["song_hits"], list):
                    tracks = [hit.get("track") for hit in data["song_hits"] if isinstance(hit, dict)]
            if not tracks:
                bot.send_message(
                    chat_id=chat_id,
                    text=f"لم يتم العثور على نتائج لـ {query}.",
                )
                return jsonify({"status": "ok"})
            reply = f"نتائج البحث عن \"{query}\":\n{format_tracks(tracks)}"
            bot.send_message(chat_id=chat_id, text=reply)
            return jsonify({"status": "ok"})

        # Unknown command – instruct user
        bot.send_message(
            chat_id=chat_id,
            text="الأمر غير معروف. استخدم /start للحصول على قائمة الأوامر.",
        )
        return jsonify({"status": "ok"})

    # If it's not a message (e.g. callback query), do nothing.
    return jsonify({"status": "ok"})
