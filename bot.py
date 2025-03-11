import logging
import os
import json
import datetime
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

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
def post_question(context: CallbackContext):
    if not questions:
        logger.warning("No questions left!")
        return

    question = questions.pop(0)
    keyboard = [[InlineKeyboardButton(option, callback_data=option)] for option in question["options"]]

    message = context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=question["question"],
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    context.bot_data["current_question"] = question
    context.bot_data["question_message_id"] = message.message_id

# Handle user responses
def handle_response(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    answer = query.data
    current_question = context.bot_data.get("current_question", {})

    if answer == current_question.get("correct_answer"):
        query.answer("Correct!")
        context.bot.edit_message_text(
            chat_id=CHANNEL_ID,
            message_id=context.bot_data["question_message_id"],
            text=f"✅ {current_question['question']}\n\nCorrect answer: {answer}"
        )
    else:
        query.answer("Incorrect!", show_alert=True)

# Post the leaderboard
def post_leaderboard(context: CallbackContext):
    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    leaderboard_text = "🏆 **Leaderboard** 🏆\n"
    leaderboard_text += "\n".join([f"{i+1}. {user}: {score}" for i, (user, score) in enumerate(sorted_leaderboard[:10])])

    context.bot.send_message(chat_id=CHANNEL_ID, text=leaderboard_text)

# Start command
def start(update: Update, context: CallbackContext):
    update.message.reply_text("Hello! I'm your quiz bot!")

# Test command
def test(update: Update, context: CallbackContext):
    update.message.reply_text("Bot is running!")

# Webhook setup
def main():
    updater = Updater(TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("test", test))
    dispatcher.add_handler(CallbackQueryHandler(handle_response))

    loop = asyncio.get_event_loop()
    loop.run_until_complete(fetch_questions())
    loop.run_until_complete(fetch_leaderboard())

    # Scheduler for daily questions and leaderboard
    scheduler = AsyncIOScheduler()
    scheduler.add_job(post_question, "cron", hour=8, minute=0, day_of_week="*", args=[dispatcher])
    scheduler.add_job(post_question, "cron", hour=12, minute=0, day_of_week="*", args=[dispatcher])
    scheduler.add_job(post_question, "cron", hour=18, minute=0, day_of_week="*", args=[dispatcher])
    scheduler.add_job(post_leaderboard, "cron", hour=23, minute=0, day_of_week="*", args=[dispatcher])
    scheduler.start()

    # Webhook setup
    updater.start_webhook(
        listen="0.0.0.0",
        port=8443,
        url_path=TOKEN,
        webhook_url=WEBHOOK_URL
    )

    updater.idle()

if __name__ == "__main__":
    main()
