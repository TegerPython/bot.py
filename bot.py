import os
import logging
import random
import json
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, JobQueue
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

# Load Questions from URL
try:
    response = requests.get(QUESTIONS_JSON_URL)
    response.raise_for_status()
    questions = response.json()
    logger.info(f"Loaded {len(questions)} questions from {QUESTIONS_JSON_URL}")
except requests.exceptions.RequestException as e:
    logger.error(f"Error fetching questions from {QUESTIONS_JSON_URL}: {e}")
    questions = []
except json.JSONDecodeError:
    logger.error(f"Error decoding JSON from {QUESTIONS_JSON_URL}")
    questions = []

# Load Leaderboard from URL
try:
    response = requests.get(LEADERBOARD_JSON_URL)
    response.raise_for_status()
    leaderboard = response.json()
    logger.info(f"Loaded leaderboard from {LEADERBOARD_JSON_URL}")
except requests.exceptions.RequestException as e:
    logger.error(f"Error fetching leaderboard from {LEADERBOARD_JSON_URL}: {e}")
    leaderboard = {}
except json.JSONDecodeError:
    logger.error(f"Error decoding leaderboard from {LEADERBOARD_JSON_URL}")
    leaderboard = {}

answered_users = set()
current_question = None
current_message_id = None

async def send_question(context: ContextTypes.DEFAULT_TYPE, is_test=False) -> bool:
    # ... (send_question remains the same)

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global answered_users, current_question, current_message_id, leaderboard

    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.first_name

    if user_id in answered_users:
        await query.answer("❌ You already answered this question.")
        return

    answered_users.add(user_id)
    user_answer = query.data.strip()
    correct_answer = current_question.get("correct_option", "").strip()

    logger.info(f"User answer: '{user_answer}'")
    logger.info(f"Correct answer: '{correct_answer}'")

    correct = user_answer == correct_answer

    if correct:
        await query.answer("✅ Correct!")
        if str(user_id) not in leaderboard:
            leaderboard[str(user_id)] = {"username": username, "score": 0}
        leaderboard[str(user_id)]["score"] += 1

        explanation = current_question.get("explanation", "No explanation provided.")
        edited_text = (
            "📝 Daily Challenge (Answered)\n\n"
            f"Question: {current_question.get('question')}\n"
            f"✅ Correct Answer: {current_question.get('correct_option')}\n"
            f"ℹ️ Explanation: {explanation}\n\n"
            f"🏆 Winner: {username}"
        )
        try:
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=current_message_id,
                text=edited_text
            )
        except Exception as e:
            logger.error(f"Failed to edit message: {e}")
    else:
        await query.answer("❌ Incorrect.")

async def heartbeat(context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (heartbeat remains the same)

async def test_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (test_question remains the same)

async def set_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (set_webhook remains the same)

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sorted_leaderboard = sorted(leaderboard.items(), key=lambda item: item[1]["score"], reverse=True)
    leaderboard_text = "🏆 Leaderboard 🏆\n\n"
    for rank, (user_id, player) in enumerate(sorted_leaderboard, start=1):
        leaderboard_text += f"{rank}. {player['username']}: {player['score']} points\n"
    await update.message.reply_text(leaderboard_text)

def get_utc_time(hour, minute, tz_name):
    # ... (get_utc_time remains the same)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    job_queue = application.job_queue

    job_queue.run_daily(send_question, get_utc_time(8, 0, "Asia/Gaza"))
    job_queue.run_daily(send_question, get_utc_time(12, 30, "Asia/Gaza"), name="second_question")
    job_queue.run_daily(send_question, get_utc_time(18, 0, "Asia/Gaza"))

    job_queue.run_repeating(heartbeat, interval=60)

    application.add_handler(CommandHandler("test", test_question))
    application.add_handler(CallbackQueryHandler(handle_answer))
    application.add_handler(CommandHandler("setwebhook", set_webhook))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command)) # add leaderboard command.

    port = int(os.environ.get("PORT", 5000))
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
    )

if __name__ == "__main__":
    main()
