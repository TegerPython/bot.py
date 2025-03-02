import logging
import os
import json
import random
from datetime import time
import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID'))
OWNER_ID = int(os.getenv('OWNER_TELEGRAM_ID'))
WEBHOOK_URL = os.getenv('RENDER_WEBHOOK_URL')

# Global variables
questions = [
    {
        "question": "What is the capital of France?",
        "options": ["Berlin", "Madrid", "Paris", "Rome"],
        "answer": "Paris"
    },
    {
        "question": "Which planet is known as the Red Planet?",
        "options": ["Earth", "Mars", "Jupiter", "Venus"],
        "answer": "Mars"
    }
]
current_question = {}
current_message_id = None
answered_users = set()
leaderboard = {}

# Load leaderboard from file
def load_leaderboard():
    global leaderboard
    try:
        with open("leaderboard.json", "r") as file:
            leaderboard = json.load(file)
    except FileNotFoundError:
        logging.warning("⚠️ No leaderboard file found, starting fresh.")
        leaderboard = {}

# Save leaderboard to file
def save_leaderboard():
    with open("leaderboard.json", "w") as file:
        json.dump(leaderboard, file)

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Welcome to the English Challenge Bot!")

# Send daily question
async def send_daily_question(context: ContextTypes.DEFAULT_TYPE) -> None:
    global current_question, current_message_id, answered_users

    current_question = random.choice(questions)
    answered_users = set()

    keyboard = [
        [InlineKeyboardButton(opt, callback_data=opt)] for opt in current_question["options"]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"📝 Daily Challenge:\n\n{current_question['question']}",
        reply_markup=reply_markup
    )
    current_message_id = message.message_id
    logging.info("✅ Question posted to channel.")

# Handle answer callback
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global answered_users, current_question

    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.first_name

    if user_id in answered_users:
        await query.answer("❌ You have already answered this question.")
        return

    answered_users.add(user_id)

    user_answer = query.data
    correct = user_answer == current_question["answer"]

    if correct:
        await query.answer("✅ Correct!")
        await update.effective_message.reply_text(f"🎉 {username} got the correct answer: {user_answer}")
        leaderboard[username] = leaderboard.get(username, 0) + 1
        save_leaderboard()
    else:
        await query.answer("❌ Incorrect.")

# Send leaderboard summary at night
async def send_leaderboard_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    summary = "📊 Daily Leaderboard\n\n"
    for rank, (name, score) in enumerate(sorted_leaderboard, start=1):
        summary += f"{rank}. {name}: {score} points\n"

    await context.bot.send_message(chat_id=CHANNEL_ID, text=summary)

# Heartbeat to bot owner
async def heartbeat(context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(chat_id=OWNER_ID, text="✅ Bot is running smoothly.")

# Main function
def main():
    logging.info("🚀 Bot Starting...")

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_answer))

    load_leaderboard()

    job_queue = application.job_queue

    gaza_timezone = pytz.timezone("Asia/Gaza")

    job_queue.run_daily(send_daily_question, time(hour=8, minute=0, tzinfo=gaza_timezone))
    job_queue.run_daily(send_daily_question, time(hour=14, minute=22, tzinfo=gaza_timezone))
    job_queue.run_daily(send_daily_question, time(hour=18, minute=0, tzinfo=gaza_timezone))
    job_queue.run_daily(send_leaderboard_summary, time(hour=23, minute=59, tzinfo=gaza_timezone))
    job_queue.run_repeating(heartbeat, interval=3600)

    application.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
    logging.info(f"🌐 Webhook set at {WEBHOOK_URL}/webhook")

    application.run_webhook(
        listen="0.0.0.0",
        port=10000,
        url_path="/webhook",
        webhook_url=f"{WEBHOOK_URL}/webhook"
    )

if __name__ == "__main__":
    main()
