import logging
import os
import json
import datetime
import asyncio
import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))  # Convert to int
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 8443))  # Default to 8443

# Load questions
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
questions = []

# Load leaderboard
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
leaderboard = {}

# Function to fetch questions from GitHub
async def fetch_questions():
    global questions
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(QUESTIONS_JSON_URL) as response:
                if response.status == 200:
                    questions = await response.json()
                    logger.info(f"Loaded {len(questions)} questions")
                else:
                    logger.error(f"Failed to fetch questions: {response.status}")
    except Exception as e:
        logger.error(f"Error fetching questions: {e}")

# Function to fetch leaderboard
async def fetch_leaderboard():
    global leaderboard
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(LEADERBOARD_JSON_URL) as response:
                if response.status == 200:
                    leaderboard = await response.json()
                    logger.info(f"Loaded {len(leaderboard)} leaderboard entries")
                else:
                    logger.error(f"Failed to fetch leaderboard: {response.status}")
    except Exception as e:
        logger.error(f"Error fetching leaderboard: {e}")

# Post a question to the channel
async def post_question(context: ContextTypes.DEFAULT_TYPE):
    if not questions:
        logger.warning("No questions left!")
        return

    question = questions.pop(0)
    keyboard = [[InlineKeyboardButton(option, callback_data=option)] for option in question["options"]]

    message = await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=question["question"],
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    context.bot_data["current_question"] = question
    context.bot_data["question_message_id"] = message.message_id

# Handle user responses
async def handle_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    answer = query.data
    current_question = context.bot_data.get("current_question", {})

    if answer == current_question.get("correct_answer"):
        await query.answer("Correct!")
        await context.bot.edit_message_text(
            chat_id=CHANNEL_ID,
            message_id=context.bot_data["question_message_id"],
            text=f"✅ {current_question['question']}\n\nCorrect answer: {answer}"
        )
    else:
        await query.answer("Incorrect!", show_alert=True)

# Post the leaderboard
async def post_leaderboard(context: ContextTypes.DEFAULT_TYPE):
    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    leaderboard_text = "🏆 **Leaderboard** 🏆\n"
    leaderboard_text += "\n".join([f"{i+1}. {user}: {score}" for i, (user, score) in enumerate(sorted_leaderboard[:10])])

    await context.bot.send_message(chat_id=CHANNEL_ID, text=leaderboard_text)

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I'm your quiz bot!")

# Test command
async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is running!")

# Webhook and scheduler setup
async def main():
    app = Application.builder().token(TOKEN).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test))
    app.add_handler(CallbackQueryHandler(handle_response))

    # Fetch initial data
    await fetch_questions()
    await fetch_leaderboard()

    # Scheduler for daily questions and leaderboard
    scheduler = AsyncIOScheduler()
    scheduler.add_job(post_question, "cron", hour=8, minute=0, day_of_week="*", args=[ContextTypes.DEFAULT_TYPE])
    scheduler.add_job(post_question, "cron", hour=12, minute=0, day_of_week="*", args=[ContextTypes.DEFAULT_TYPE])
    scheduler.add_job(post_question, "cron", hour=18, minute=0, day_of_week="*", args=[ContextTypes.DEFAULT_TYPE])
    scheduler.add_job(post_leaderboard, "cron", hour=23, minute=0, day_of_week="*", args=[ContextTypes.DEFAULT_TYPE])
    scheduler.start()

    # Start webhook on port 8443
    await app.bot.set_webhook(url=WEBHOOK_URL)
    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN
    )

if __name__ == "__main__":
    asyncio.run(main())
