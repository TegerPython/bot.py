import logging
import json
import asyncio
import aiohttp
import datetime
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CallbackContext,
    CommandHandler,
    MessageHandler,
    filters,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import os

# Load environment variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
CHANNEL_ID = os.getenv("CHANNEL_ID")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Async function to fetch JSON safely
async def fetch_json(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                text = await response.text()
                try:
                    return json.loads(text)  # Manually parse JSON
                except json.JSONDecodeError as e:
                    logger.error(f"JSON decoding error: {e}")
            else:
                logger.error(f"Failed to fetch {url}: {response.status}")
    return None

# Command: Start
async def start(update: Update, context: CallbackContext):
    await update.message.reply_text("Welcome to the English quiz bot!")

# Post a new question
async def post_question():
    logger.info("Posting a new question...")
    questions = await fetch_json(QUESTIONS_JSON_URL)
    if not questions:
        logger.error("No questions found.")
        return
    question = questions.pop(0)

    # Send question
    bot = Bot(TOKEN)
    await bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"Question: {question['question']}\nOptions:\nA) {question['options'][0]}\nB) {question['options'][1]}\nC) {question['options'][2]}\nD) {question['options'][3]}",
    )

# Post leaderboard
async def post_leaderboard():
    logger.info("Posting leaderboard...")
    leaderboard = await fetch_json(LEADERBOARD_JSON_URL)
    if not leaderboard:
        logger.error("No leaderboard data found.")
        return

    # Format leaderboard text
    leaderboard_text = "🏆 Leaderboard 🏆\n"
    for idx, (user, score) in enumerate(leaderboard.items(), start=1):
        leaderboard_text += f"{idx}. {user}: {score} points\n"

    bot = Bot(TOKEN)
    await bot.send_message(chat_id=CHANNEL_ID, text=leaderboard_text)

# Main function
async def main():
    app = Application.builder().token(TOKEN).build()

    # Add command handlers
    app.add_handler(CommandHandler("start", start))

    # Setup scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(post_question, CronTrigger(hour=8, minute=0))
    scheduler.add_job(post_question, CronTrigger(hour=12, minute=0))
    scheduler.add_job(post_question, CronTrigger(hour=18, minute=0))
    scheduler.add_job(post_leaderboard, CronTrigger(hour=23, minute=59))
    scheduler.start()

    # Start webhook
    logger.info("Starting webhook...")
    await app.run_webhook(
        listen="0.0.0.0",
        port=8443,  # ✅ Runs on port 8443
        webhook_url=WEBHOOK_URL,
    )

# Run the bot
if __name__ == "__main__":
    asyncio.run(main())
