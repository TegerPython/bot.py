import os
import logging
import asyncio
from datetime import datetime, time
import pytz
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

# Load bot token and channel ID from environment variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")  # Example: -1001234567890 (for channels)

# Setup bot
bot = Bot(TOKEN)

# Set Gaza timezone
GAZA_TZ = pytz.timezone('Asia/Gaza')

# Sample question (for now, hardcoded - we’ll load real questions later)
QUESTION = "What is the past tense of 'go'?"
OPTIONS = [
    ("A) Goed", "A"),
    ("B) Went", "B"),
    ("C) Goes", "C"),
    ("D) Going", "D")
]
CORRECT_ANSWER = "B"

# Function to send question to channel
async def send_question():
    keyboard = [
        [InlineKeyboardButton(text, callback_data=callback) for text, callback in OPTIONS]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = await bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"📚 Daily English Question:\n\n{QUESTION}",
        reply_markup=reply_markup
    )
    logging.info(f"Question sent to channel {CHANNEL_ID}.")
    return message.message_id

# Scheduler function to check and send questions
async def schedule_questions():
    last_sent_dates = {"08:00": None, "12:00": None, "16:20": None}

    while True:
        now = datetime.now(GAZA_TZ)
        current_time = now.strftime("%H:%M")

        if current_time in last_sent_dates and last_sent_dates[current_time] != now.date():
            await send_question()
            last_sent_dates[current_time] = now.date()
            logging.info(f"Question sent at {current_time} Gaza time.")

        await asyncio.sleep(30)  # Check every 30 seconds

# Main bot loop (placeholder - future message handling will be here)
async def main():
    logging.basicConfig(level=logging.INFO)

    # Start the daily question scheduler
    asyncio.create_task(schedule_questions())

    # Keep bot running (will be replaced with actual handlers later)
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(main())
