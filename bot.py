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
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL") # Get the questions URL

# Load Questions from URL
try:
    response = requests.get(QUESTIONS_JSON_URL)
    response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
    questions = response.json()
    logger.info(f"Loaded {len(questions)} questions from {QUESTIONS_JSON_URL}")
except requests.exceptions.RequestException as e:
    logger.error(f"Error fetching questions from {QUESTIONS_JSON_URL}: {e}")
    questions = []
except json.JSONDecodeError:
    logger.error(f"Error decoding JSON from {QUESTIONS_JSON_URL}")
    questions = []

answered_users = set()
current_question = None
current_message_id = None

async def send_question(context: ContextTypes.DEFAULT_TYPE, is_test=False) -> bool:
    global current_question, answered_users, current_message_id
    answered_users = set()

    if not questions: # added check for empty questions list.
        logger.error("No questions available.")
        return False

    if is_test:
        current_question = random.choice(questions)
    else:
        current_question = questions[datetime.now().day % len(questions)]

    logger.info(f"send_question called, is_test: {is_test}, question: {current_question['question']}")
    keyboard = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in current_question["options"]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"📝 {'Test' if is_test else 'Daily'} Challenge:\n\n{current_question['question']}",
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
    # ... (handle_answer remains the same)

async def heartbeat(context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (heartbeat remains the same)

async def test_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (test_question remains the same)

async def set_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (set_webhook remains the same)

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

    port = int(os.environ.get("PORT", 5000))
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
    )

if __name__ == "__main__":
    main()
