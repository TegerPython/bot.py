import os
import logging
import json
import requests
import time
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import pytz

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
WEEKLY_QUESTIONS_JSON_URL = os.getenv("WEEKLY_QUESTIONS_JSON_URL")
WEEKLY_LEADERBOARD_JSON_URL = os.getenv("WEEKLY_LEADERBOARD_JSON_URL")

# Global variables
weekly_questions = []
weekly_user_answers = {}
weekly_poll_message_ids = []

# Load Questions from URL
def load_questions(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching questions from {url}: {e}")
        return []

# Load Leaderboard from URL
def load_leaderboard(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching leaderboard from {url}: {e}")
        return {}

async def send_weekly_poll_question(context: ContextTypes.DEFAULT_TYPE, question):
    try:
        message = await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question=question["question"],
            options=question["options"],
            type=Poll.QUIZ,
            correct_option_id=question["correct_option"],
            open_period=3,  # 3 seconds for testing
        )
        return message.poll.id
    except Exception as e:
        logger.error(f"Error sending weekly poll question: {e}")
        return None

async def handle_poll_results(context: ContextTypes.DEFAULT_TYPE, poll_id, question):
    try:
        poll = await context.bot.get_poll(poll_id=poll_id)
        for option in poll.options:
            if poll.options.index(option) == poll.correct_option_id:
                for user in option.voters:
                    if str(user.user.id) not in weekly_user_answers:
                        weekly_user_answers[str(user.user.id)] = {"username": user.user.first_name, "score": 0}
                    weekly_user_answers[str(user.user.id)]["score"] += 1
                break
    except Exception as e:
        logger.error(f"Error handling poll results: {e}")

async def send_weekly_results(context: ContextTypes.DEFAULT_TYPE):
    weekly_results = load_leaderboard(WEEKLY_LEADERBOARD_JSON_URL)
    results = sorted(weekly_results.items(), key=lambda item: item[1]["score"], reverse=True)
    message = "🏆 Weekly Test Results 🏆\n\n"
    if results:
        for i, (user_id, user_data) in enumerate(results):
            user = await context.bot.get_chat(user_id)
            if i == 0:
                message += f"🥇 {user.first_name} 🥇: {user_data['score']} points\n\n"
            elif i == 1:
                message += f"🥈 {user.first_name} 🥈: {user_data['score']} points\n"
            elif i == 2:
                message += f"🥉 {user.first_name} 🥉: {user_data['score']} points\n"
            else:
                message += f"{user.first_name}: {user_data['score']} points\n"
    else:
        message += "No participants."
    await context.bot.send_message(chat_id=CHANNEL_ID, text=message)

async def test_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info(f"test_weekly called by user ID: {update.effective_user.id}")
    logger.info(f"OWNER_ID: {OWNER_ID}")
    if update.effective_user.id != OWNER_ID:
        logger.info("test_weekly: user not authorized")
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    global weekly_questions, weekly_user_answers
    weekly_questions = load_questions(WEEKLY_QUESTIONS_JSON_URL)
    if not weekly_questions:
        await update.message.reply_text("❌ Failed to load weekly questions.")
        return

    weekly_user_answers = {}

    for question in weekly_questions[:3]:
        poll_id = await send_weekly_poll_question(context, question)
        time.sleep(3)  # Wait for poll to close
        await handle_poll_results(context, poll_id, question)

    await send_weekly_results(context)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("testweekly", test_weekly))

    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting bot on port {port}")
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
    )

if __name__ == "__main__":
    main()
