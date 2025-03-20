import os
import logging
import random
import json
import requests
import time
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, JobQueue
import pytz

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables (Using your provided variables)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
WEEKLY_QUESTIONS_JSON_URL = os.getenv("WEEKLY_QUESTIONS_JSON_URL")

# Global variables
questions = []
leaderboard = {}
answered_users = set()
current_question = None
current_message_id = None
question_index = 0  # Track the current question index
weekly_questions = []
weekly_answered_users = set()
weekly_current_question = None
weekly_current_message_id = None
weekly_leaderboard = {}

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
def load_leaderboard():
    global leaderboard
    leaderboard = load_questions(LEADERBOARD_JSON_URL)

load_questions(QUESTIONS_JSON_URL)
load_leaderboard()

async def send_weekly_question(context: ContextTypes.DEFAULT_TYPE, question):
    global weekly_current_question, weekly_answered_users, weekly_current_message_id
    weekly_answered_users = set()
    weekly_current_question = question

    keyboard = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in question.get("options", [])]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"🚀 Weekly Test:\n\n{question.get('question')}",
            reply_markup=reply_markup,
            disable_web_page_preview=True,
            disable_notification=False,
        )

        if message and message.message_id:
            weekly_current_message_id = message.message_id
            return True
        else:
            return False

    except Exception as e:
        logger.error(f"Failed to send weekly question: {e}")
        return False

async def handle_weekly_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global weekly_answered_users, weekly_current_question, weekly_current_message_id, weekly_leaderboard

    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.first_name

    if user_id in weekly_answered_users:
        await query.answer("❌ You already answered this question.")
        return

    weekly_answered_users.add(user_id)
    user_answer = query.data.strip()
    correct_answer = weekly_current_question.get("correct_option", "").strip()

    correct = user_answer == correct_answer

    if correct:
        await query.answer("✅ Correct!")
        if str(user_id) not in weekly_leaderboard:
            weekly_leaderboard[str(user_id)] = {"username": username, "score": 0}
        weekly_leaderboard[str(user_id)]["score"] += 1

        explanation = weekly_current_question.get("explanation", "No explanation provided.")
        edited_text = (
            "🚀 Weekly Test (Answered)\n\n"
            f"Question: {weekly_current_question.get('question')}\n"
            f"✅ Correct Answer: {weekly_current_question.get('correct_option')}\n"
            f"ℹ️ Explanation: {explanation}\n\n"
            f"🏆 Winner: {username}"
        )
        try:
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=weekly_current_message_id,
                text=edited_text
            )
        except Exception as e:
            logger.error(f"Failed to edit weekly message: {e}")
    else:
        await query.answer("❌ Incorrect.")

async def test_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info(f"test_weekly called by user ID: {update.effective_user.id}")
    logger.info(f"OWNER_ID: {OWNER_ID}")
    if update.effective_user.id != OWNER_ID:
        logger.info("test_weekly: user not authorized")
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    weekly_questions = load_questions(WEEKLY_QUESTIONS_JSON_URL)
    if not weekly_questions:
        await update.message.reply_text("❌ Failed to load weekly questions.")
        return

    weekly_leaderboard.clear()

    for question in weekly_questions:
        if not await send_weekly_question(context, question):
            await update.message.reply_text("❌ Failed to send a weekly question.")
            return
        time.sleep(3)  # 3 seconds delay between questions

    sorted_leaderboard = sorted(weekly_leaderboard.items(), key=lambda item: item[1]["score"], reverse=True)
    leaderboard_text = "🏆 Weekly Test Results 🏆\n\n"
    for rank, (user_id, player) in enumerate(sorted_leaderboard, start=1):
        leaderboard_text += f"{rank}. {player['username']}: {player['score']} points\n"
    await context.bot.send_message(chat_id=CHANNEL_ID, text=leaderboard_text)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("testweekly", test_weekly))
    application.add_handler(CallbackQueryHandler(handle_weekly_answer))

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
