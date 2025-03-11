import os
import json
import asyncio
import logging
from datetime import time
from flask import Flask, request
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
import requests
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment Variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
CHANNEL_ID = os.getenv("CHANNEL_ID")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
PORT = int(os.getenv("PORT", 5000))  # ✅ Get Render's PORT

# Flask app for webhook
flask_app = Flask(__name__)

# Telegram bot application
bot_app = Application.builder().token(TOKEN).build()

# Scheduler for posting questions
scheduler = AsyncIOScheduler()

# Existing helper functions remain the same...

async def run():
    """Run the bot with webhook."""
    await bot_app.initialize()
    await bot_app.bot.set_webhook(WEBHOOK_URL)
    
    # Start Flask server with Render's PORT
    flask_app.run(host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    # Schedule jobs properly
    scheduler.add_job(post_question, "cron", hour=8, minute=0, args=[bot_app])
    scheduler.add_job(post_question, "cron", hour=12, minute=0, args=[bot_app])
    scheduler.add_job(post_question, "cron", hour=18, minute=0, args=[bot_app])
    scheduler.add_job(post_leaderboard, "cron", hour=20, minute=0, args=[bot_app])
    
    scheduler.start()
    
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        scheduler.shutdown()
