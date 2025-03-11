import logging
import os
import json
import datetime
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 8443))  # Default to port 8443

# Load questions
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
questions = []

# Load leaderboard
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
leaderboard = {}

# Function to fetch and update questions from GitHub
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

# Function to fetch and update leaderboard
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
async def post_question(application: Application):
    if not questions:
        logger.warning("No questions left!")
        return

    question = questions.pop(0)
    keyboard = [[InlineKeyboardButton(option, callback_data=option)] for option in question["options"]]

    message = await application.bot.send_message(
        chat_id=CHANNEL_ID,
        text=question["question"],
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    application.bot_data["current_question"] = question
    application.bot_data["question_message_id"] = message.message_id

# Handle user responses
async def handle_response(update: Update, context):
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
async def post_leaderboard(application: Application):
    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    leaderboard_text = "🏆 **Leaderboard** 🏆\n"
    leaderboard_text += "\n".join([f"{i+1}. {user}: {score}" for i, (user, score) in enumerate(sorted_leaderboard[:10])])

    await application.bot.send_message(chat_id=CHANNEL_ID, text=leaderboard_text)

# Start command
async def start(update: Update, context):
    await update.message.reply_text("Hello! I'm your quiz bot!")

# Test command
async def test(update: Update, context):
    await update.message.reply_text("Bot is running!")

# Webhook setup
async def start_bot():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("test", test))
    application.add_handler(CallbackQueryHandler(handle_response))

    await fetch_questions()
    await fetch_leaderboard()

    # Scheduler for daily questions and leaderboard
    scheduler = AsyncIOScheduler()
    scheduler.add_job(post_question, "cron", hour=8, minute=0, day_of_week="*", args=[application])
    scheduler.add_job(post_question, "cron", hour=12, minute=0, day_of_week="*", args=[application])
    scheduler.add_job(post_question, "cron", hour=18, minute=0, day_of_week="*", args=[application])
    scheduler.add_job(post_leaderboard, "cron", hour=23, minute=0, day_of_week="*", args=[application])
    scheduler.start()

    # Webhook setup
    await application.bot.set_webhook(url=WEBHOOK_URL)
    await application.run_webhook(port=PORT, webhook_url=WEBHOOK_URL)

# Run bot
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_bot())
