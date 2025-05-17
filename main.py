import os
import telebot
import asyncio
from telethon import TelegramClient
from flask import Flask, jsonify
from threading import Thread
import aiohttp
import nest_asyncio
import logging
import time
from datetime import datetime
import itertools

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Apply nest_asyncio
nest_asyncio.apply()

# Initialize Flask app
app = Flask(__name__)

# Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN", "7891671369:AAFtHAzdwUNurVI_5WITnF3EWxRTftJUWrQ")
API_ID = int(os.getenv("API_ID", "29272284"))
API_HASH = os.getenv("API_HASH", "d6a6264a583e795b73812dd0549da98b")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1002515413990"))
TERABOX_API_URL = os.getenv("TERABOX_API_URL", "https://teradl-api.dapuntaratya.com")
ALLOWED_USER_IDS = {5730407948}  # Admin user ID
ADMIN_USER_ID = 5730407948

# Initialize bot and client
bot = telebot.TeleBot(BOT_TOKEN)
telethon_client = TelegramClient("bot_session", API_ID, API_HASH)

# Get the event loop
loop = asyncio.get_event_loop()

# Animation frames
ANIMATION_FRAMES = ["🌀", "⏳", "🔄", "⚙️"]
animation_cycle = itertools.cycle(ANIMATION_FRAMES)

# Flask health check
@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok", "message": "Bot is running"}), 200

# Bot command handlers
@bot.message_handler(commands=["start"])
def start_command(message):
    if message.from_user.id not in ALLOWED_USER_IDS:
        bot.reply_to(message, "🚫 *Unauthorized access.* Contact the bot admin.", parse_mode="Markdown")
        return
    bot.send_message(
        message.chat.id,
        "🌟 *Welcome to TeraBox Downloader!* 🌟\n"
        "Send a valid Terabox link to download videos.\n\n"
        "🔑 *Commands*:\n"
        "📌 /id <user_id> - Grant access to a user (admin only)\n"
        "📌 /g - Grant group access (admin only)",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=["id"])
def id_command(message):
    if message.from_user.id != ADMIN_USER_ID:
        bot.reply_to(message, "🚫 *Only the admin can use this command.*", parse_mode="Markdown")
        return
    try:
        args = message.text.split()
        if len(args) != 2 or not args[1].isdigit():
            bot.reply_to(message, "⚠️ *Usage*: /id <user_id>", parse_mode="Markdown")
            return
        new_user_id = int(args[1])
        if new_user_id in ALLOWED_USER_IDS:
            bot.reply_to(message, f"✅ *User {new_user_id} already has access.*", parse_mode="Markdown")
        else:
            ALLOWED_USER_IDS.add(new_user_id)
            bot.reply_to(message, f"✅ *Access granted to user {new_user_id}.*", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"ID command failed: {str(e)}")
        bot.reply_to(message, "Invalid user ID", parse_mode="Markdown")

@bot.message_handler(commands=["g"])
def group_command(message):
    if message.from_user.id != ADMIN_USER_ID:
        bot.reply_to(message, "🚫 *Only the admin can use this command.*", parse_mode="Markdown")
        return
    if message.chat.type not in ["group", "supergroup"]:
        bot.reply_to(message, "⚠️ *This command can only be used in group chats.*", parse_mode="Markdown")
        return
    try:
        members = bot.get_chat_members(message.chat.id)
        for member in members:
            ALLOWED_USER_IDS.add(member.user.id)
        bot.reply_to(message, "✅ *Access granted to all group members.*", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Group command failed: {str(e)}")
        bot.reply_to(message, "Network error", parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if message.from_user.id not in ALLOWED_USER_IDS:
        bot.reply_to(message, "🚫 *Unauthorized access.* Contact the bot admin.", parse_mode="Markdown")
        return
    url = message.text.strip()
    if not url.startswith("http"):
        bot.reply_to(message, "⚠️ *Please send a valid URL.*", parse_mode="Markdown")
        return
    msg = bot.send_message(message.chat.id, "⏳ *Processing your request...* 🌌", parse_mode="Markdown")
    asyncio.run_coroutine_threadsafe(
        process_file(url, message, msg.message_id), loop
    )

async def process_file(url, message, processing_message_id):
    file_path = None
    try:
        # Step 1: Get file details
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
            for attempt in range(5):
                try:
                    async with session.post(
                        f"{TERABOX_API_URL}/generate_file",
                        headers={"Content-Type": "application/json"},
                        json={"url": url}
                    ) as resp:
                        if resp.status != 200:
                            raise Exception(f"HTTP {resp.status}")
                        data = await resp.json()
                        break
                except Exception as e:
                    logger.warning(f"Generate file attempt {attempt + 1}: {str(e)}")
                    if attempt == 4:
                        bot.reply_to(message, "Invalid link", parse_mode="Markdown")
                        return
                    await asyncio.sleep(2 ** attempt)

        if data.get("status") != "success":
            bot.reply_to(message, "Invalid link", parse_mode="Markdown")
            return

        # Extract file details
        def find_first_file(file_list):
            for item in file_list:
                is_dir = str(item.get("is_dir", "1"))
                if is_dir == "0" and item.get("type") == "video":
                    return item
                if item.get("list"):
                    result = find_first_file(item["list"])
                    if result:
                        return result
            return None

        file_info = find_first_file(data["list"])
        if not file_info:
            bot.reply_to(message, "Video not found", parse_mode="Markdown")
            return

        filename = file_info["name"]
        fs_id = file_info["fs_id"]
        file_size_bytes = int(file_info["size"])
        file_size_mb = file_size_bytes / (1024 * 1024)

        max_size_mb = 2000
        if file_size_mb > max_size_mb:
            bot.reply_to(message, f"File size too large: {file_size_mb:.2f} MB", parse_mode="Markdown")
            return

        # Step 2: Get download link
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
            for attempt in range(5):
                try:
                    async with session.post(
                        f"{TERABOX_API_URL}/generate_link",
                        headers={"Content-Type": "application/json"},
                        json={
                            "uk": data["uk"],
                            "shareid": data["shareid"],
                            "timestamp": data["timestamp"],
                            "sign": data["sign"],
                            "fs_id": fs_id
                        }
                    ) as resp:
                        if resp.status != 200:
                            raise Exception(f"HTTP {resp.status}")
                        link_data = await resp.json()
                        break
                except Exception as e:
                    logger.warning(f"Generate link attempt {attempt + 1}: {str(e)}")
                    if attempt == 4:
                        bot.reply_to(message, "Network error", parse_mode="Markdown")
                        return
                    await asyncio.sleep(2 ** attempt)

        if link_data.get("status") != "success":
            bot.reply_to(message, "Network error", parse_mode="Markdown")
            return

        download_urls = [link_data["download_link"].get("url_1"), link_data["download_link"].get("url_2")]
        download_url = None
        for url_option in download_urls:
            if url_option:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
                    for attempt in range(5):
                        try:
                            async with session.get(url_option) as resp:
                                if resp.status == 200:
                                    download_url = url_option
                                    break
                                raise Exception(f"HTTP {resp.status}")
                        except Exception as e:
                            logger.warning(f"Download URL attempt {attempt + 1}: {str(e)}")
                            if attempt == 4:
                                continue
                            await asyncio.sleep(2 ** attempt)
                    if download_url:
                        break
        if not download_url:
            bot.reply_to(message, "Network error", parse_mode="Markdown")
            return

        bot.delete_message(message.chat.id, processing_message_id)
        username = message.from_user.username or message.from_user.first_name
        user_id = message.from_user.id

        # Download with progress bar
        os.makedirs("./downloads", exist_ok=True)
        file_path = os.path.join("./downloads", f"{message.chat.id}_{filename}")

        start_time = time.time()
        downloaded_bytes = 0
        status_msg = bot.send_message(
            message.chat.id,
            get_progress_message(0, file_size_mb, 0, username, user_id, filename, "Downloading", next(animation_cycle)),
            parse_mode="Markdown"
        )

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
            async with session.get(download_url) as resp:
                if resp.status != 200:
                    bot.reply_to(message, "Network error", parse_mode="Markdown")
                    return
                with open(file_path, "wb") as file:
                    async for chunk in resp.content.iter_chunked(1024 * 1024):
                        file.write(chunk)
                        downloaded_bytes += len(chunk)
                        elapsed_time = time.time() - start_time
                        speed_mbps = (downloaded_bytes / (1024 * 1024) / elapsed_time) if elapsed_time > 0 else 0
                        progress = (downloaded_bytes / file_size_bytes) * 100
                        try:
                            bot.edit_message_text(
                                chat_id=message.chat.id,
                                message_id=status_msg.message_id,
                                text=get_progress_message(
                                    progress, file_size_mb, speed_mbps, username, user_id, filename, "Downloading", next(animation_cycle)
                                ),
                                parse_mode="Markdown"
                            )
                        except telebot.apihelper.ApiTelegramException:
                            pass
                        await asyncio.sleep(1)

        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            text=f"✅ *Download complete*: _{filename}_ 🎉",
            parse_mode="Markdown"
        )

        # Send video/document
        video_caption = (
            f"🌟 *Video Downloaded* 🌟\n"
            f"┌──────────────────────────┐\n"
            f"│ 🎥 *Video*: _{filename}_\n"
            f"│ 👤 *User*: *{username}* (ID: _{user_id}_)\n"
            f"│ 📏 *Size*: {file_size_mb:.2f} MB\n"
            f"└──────────────────────────┘"
        )
        with open(file_path, "rb") as file:
            if filename.lower().endswith(('.mp4', '.mkv', '.avi')):
                bot.send_video(message.chat.id, file, caption=video_caption, parse_mode="Markdown")
            else:
                bot.send_document(message.chat.id, file, caption=video_caption, parse_mode="Markdown")

        # Upload to channel
        await upload_to_channel(file_path, filename, message.chat.id, file_size_mb)

    except Exception as e:
        logger.error(f"Process file failed: {str(e)}")
        bot.reply_to(message, "Network error", parse_mode="Markdown")
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

async def upload_to_channel(file_path, filename, chat_id, file_size_mb):
    try:
        if not telethon_client.is_connected():
            await telethon_client.start(bot_token=BOT_TOKEN)
        
        for attempt in range(5):
            try:
                await telethon_client.send_file(
                    CHANNEL_ID,
                    file_path,
                    caption=f"🌟 *Uploaded*: _{filename}_ (Size: {file_size_mb:.2f} MB)",
                    parse_mode="Markdown"
                )
                bot.send_message(chat_id, f"✅ *Upload complete*: _{filename}_ 🎉", parse_mode="Markdown")
                break
            except Exception as e:
                logger.warning(f"Upload attempt {attempt + 1}: {str(e)}")
                if attempt == 4:
                    bot.send_message(chat_id, "Network error", parse_mode="Markdown")
                    return
                await asyncio.sleep(2 ** attempt)
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        bot.send_message(chat_id, "Network error", parse_mode="Markdown")

def get_progress_message(progress, file_size_mb, speed_mbps, username, user_id, filename, action, animation_frame):
    progress_bar_length = 20
    filled = int(progress_bar_length * progress / 100)
    bar = "█" * filled + "░" * (progress_bar_length - filled)
    return (
        f"🌌 *{action}: _{filename}_* {animation_frame}\n"
        f"┌──────────────────────────┐\n"
        f"│ 👤 *User*: *{username}* (ID: _{user_id}_)\n"
        f"│ 📏 *Size*: {file_size_mb:.2f} MB\n"
        f"│ ⚡ *Speed*: {speed_mbps:.2f} MB/s\n"
        f"│ 📊 *Progress*: [{bar}] {progress:.1f}%\n"
        f"│ ⏰ *Time*: {datetime.now().strftime('%H:%M:%S')}\n"
        f"└──────────────────────────┘"
    )

def run_flask():
    app.run(host="0.0.0.0", port=5000, use_reloader=False)

async def main():
    try:
        flask_thread = Thread(target=run_flask, daemon=True)
        flask_thread.start()
        
        await telethon_client.start(bot_token=BOT_TOKEN)
        logger.info("Bot is running...")
        
        loop.run_in_executor(None, bot.polling, {"none_stop": True, "interval": 1, "timeout": 60})
        
        while True:
            await asyncio.sleep(1)
        
    except Exception as e:
        logger.error(f"Bot startup failed: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(main())