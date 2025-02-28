import os
import json
import logging
import asyncio
import random
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler
)

# Load environment variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))
WEBHOOK_URL = os.getenv("RENDER_WEBHOOK_URL")

# Setup logging
logging.basicConfig(level=logging.INFO)

# Scheduler
scheduler = AsyncIOScheduler()

# Load or create leaderboard file
LEADERBOARD_FILE = "leaderboard.json"

def load_leaderboard():
    if os.path.exists(LEADERBOARD_FILE):
        with open(LEADERBOARD_FILE, "r") as file:
            return json.load(file)
    return {}

def save_leaderboard(data):
    with open(LEADERBOARD_FILE, "w") as file:
        json.dump(data, file, indent=2)

leaderboard = load_leaderboard()

# Sample questions (you can change these)
QUESTIONS = [
    {"question": "What’s the synonym of 'Happy'?", "options": ["Sad", "Joyful", "Angry", "Tired"], "answer": "Joyful"},
    {"question": "What’s the past tense of 'go'?", "options": ["Goed", "Went", "Gone", "Goes"], "answer": "Went"},
]

# Current question tracking
current_question = None
answered_users = {}

async def send_daily_question(context: ContextTypes.DEFAULT_TYPE):
    global current_question, answered_users

    question = random.choice(QUESTIONS)
    current_question = question
    answered_users = {}

    buttons = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in question['options']]
    reply_markup = InlineKeyboardMarkup(buttons)

    await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"📚 Daily Question:\n\n{question['question']}",
        reply_markup=reply_markup
    )

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global leaderboard, answered_users

    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.first_name

    if user_id in answered_users:
        await query.answer("❌ You've already answered this question.")
        return

    answered_users[user_id] = True
    selected_option = query.data
    correct_answer = current_question['answer']

    if selected_option == correct_answer:
        if len(answered_users) == 1:
            points = 3  # First correct gets 3 points
        else:
            points = 1

        if str(user_id) not in leaderboard:
            leaderboard[str(user_id)] = {"name": username, "points": 0}
        
        leaderboard[str(user_id)]["points"] += points
        save_leaderboard(leaderboard)

        await query.answer("✅ Correct!")
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"🎉 {username} answered correctly and earned {points} points!"
        )
    else:
        await query.answer("❌ Wrong answer.")

async def send_leaderboard_summary(context: ContextTypes.DEFAULT_TYPE):
    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1]["points"], reverse=True)

    message = "🏆 Daily Leaderboard:\n\n"
    for rank, (user_id, data) in enumerate(sorted_leaderboard, start=1):
        message += f"{rank}. {data['name']} - {data['points']} points\n"

    if not sorted_leaderboard:
        message += "No players scored points today."

    await context.bot.send_message(chat_id=CHANNEL_ID, text=message)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I'm your competitive English quiz bot 🎉")

async def heartbeat(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=OWNER_ID, text="✅ Bot Heartbeat - Bot is Running.")

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_answer))

    # Scheduling - Gaza Time (UTC+2)
    scheduler.add_job(send_daily_question, "cron", hour=8, minute=0, timezone="Asia/Gaza", args=[application])
    scheduler.add_job(send_daily_question, "cron", hour=12, minute=0, timezone="Asia/Gaza", args=[application])
    scheduler.add_job(send_daily_question, "cron", hour=17, minute=55, timezone="Asia/Gaza", args=[application])
    scheduler.add_job(send_leaderboard_summary, "cron", hour=23, minute=59, timezone="Asia/Gaza", args=[application])

    # Heartbeat every 60 minutes
    scheduler.add_job(heartbeat, "interval", minutes=60, args=[application])

    scheduler.start()

    # Webhook Setup
    application.bot.set_webhook(url=WEBHOOK_URL + "/webhook")

    application.run_webhook(
        listen="0.0.0.0",
        port=10000,
        url_path="/webhook",
        webhook_url=WEBHOOK_URL + "/webhook"
    )

if __name__ == "__main__":
    main()
