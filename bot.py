import os
import logging
import random
import json
import requests
import time  # Import time for delay
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
    global current_question, answered_users, current_message_id
    answered_users = set()

    if not questions:
        logger.error("No questions available.")
        return False

    if is_test:
        current_question = random.choice(questions)
    else:
        current_question = questions[datetime.now().day % len(questions)]

    logger.info(f"send_question called, is_test: {is_test}, question: {current_question.get('question')}")
    keyboard = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in current_question.get("options", [])]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"📝 {'Test' if is_test else 'Daily'} Challenge:\n\n{current_question.get('question')}",
            reply_markup=reply_markup,
            disable_web_page_preview=True,
            disable_notification=False,
        )

        if message and message.message_id:
            current_message_id = message.message_id
            logger.info("send_question: message sent successfully")
            return True
        else:
            logger.info("send_question: message sending failed")
            return False

    except Exception as e:
        logger.error(f"send_question: Failed to send question: {e}")
        return False

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
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await context.bot.send_message(chat_id=OWNER_ID, text=f"💓 Heartbeat check - Bot is alive at {now}")

async def test_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info(f"test_question called by user ID: {update.effective_user.id}")
    logger.info(f"OWNER_ID: {OWNER_ID}")
    if update.effective_user.id != OWNER_ID:
        logger.info("test_question: user not authorized")
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    if await send_question(context, is_test=True):
        await update.message.reply_text("✅ Test question sent.")
    else:
        await update.message.reply_text("❌ Failed to send test question.")

async def set_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    await context.bot.set_webhook(f"{WEBHOOK_URL}/{BOT_TOKEN}")
    await update.message.reply_text("✅ Webhook refreshed.")

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        sorted_leaderboard = sorted(leaderboard.items(), key=lambda item: item[1]["score"], reverse=True)
        leaderboard_text = "🏆 Leaderboard 🏆\n\n"
        for rank, (user_id, player) in enumerate(sorted_leaderboard, start=1):
            leaderboard_text += f"{rank}. {player['username']}: {player['score']} points\n"
        await update.message.reply_text(leaderboard_text)
    except Exception as e:
        logger.error(f"Error in leaderboard_command: {e}")
        await update.message.reply_text("❌ Failed to display leaderboard.")

def get_utc_time(hour, minute, tz_name):
    tz = pytz.timezone(tz_name)
    local_time = tz.localize(datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0))
    return local_time.astimezone
