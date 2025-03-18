import os
import logging
import random
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

# Questions
questions = [
    {"question": "What is the capital of France?", "options": ["Berlin", "Madrid", "Paris", "Rome"], "answer": "Paris", "explanation": "Paris is the capital city of France."},
    {"question": "2 + 2 equals?", "options": ["3", "4", "5", "6"], "answer": "4", "explanation": "Simple math!"}
]

answered_users = set()
current_question = None
current_message_id = None

async def send_question(context: ContextTypes.DEFAULT_TYPE, is_test=False) -> bool:
    global current_question, answered_users, current_message_id
    answered_users = set()

    if is_test:
        current_question = random.choice(questions)
    else:
        current_question = questions[datetime.now().day % len(questions)]

    logger.info(f"send_question called, is_test: {is_test}, question: {current_question['question']}") # add log

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
            logger.info("send_question: message sent successfully") # add log
            return True
        else:
            logger.info("send_question: message sending failed") # add log
            return False

    except Exception as e:
        logger.error(f"send_question: Failed to send question: {e}") # add log
        return False

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (handle_answer remains the same)

async def heartbeat(context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (heartbeat remains the same)

async def test_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info(f"test_question called by user ID: {update.effective_user.id}") # add log
    logger.info(f"OWNER_ID: {OWNER_ID}") # add log
    if update.effective_user.id != OWNER_ID:
        logger.info("test_question: user not authorized") # add log
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    if await send_question(context, is_test=True):
        await update.message.reply_text("✅ Test question sent.")
    else:
        await update.message.reply_text("❌ Failed to send test question.")

async def set_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (set_webhook remains the same)

def get_utc_time(hour, minute, tz_name):
    # ... (get_utc_time remains the same)

def main():
    # ... (main remains the same)
