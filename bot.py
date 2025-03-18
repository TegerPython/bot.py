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
    {"question": "What is the capital of France?", "options": ["Berlin", "Madrid", "Paris", "Rome"], "answer": "Paris"},
    {"question": "2 + 2 equals?", "options": ["3", "4", "5", "6"], "answer": "4"}
]

current_question = None
current_message_id = None

async def send_question(context: ContextTypes.DEFAULT_TYPE, is_test=False):
    global current_question, current_message_id

    if is_test:
        current_question = random.choice(questions)
    else:
        current_question = questions[datetime.now().day % len(questions)]

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
        current_message_id = message.message_id
        return True
    except Exception as e:
        logger.error(f"Failed to send question: {e}")
        return False

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user_answer = query.data

    logger.info(f"Callback query from {user_id}: {user_answer}")

    if user_answer == current_question["answer"]:
        await query.answer("✅ Correct!")
    else:
        await query.answer("❌ Incorrect.")

async def test_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    if await send_question(context, is_test=True):
        await update.message.reply_text("✅ Test question sent to channel.")
    else:
        await update.message.reply_text("❌ Failed to send test question.")

async def heartbeat(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await context.bot.send_message(chat_id=OWNER_ID, text=f"💓 Heartbeat check - Bot is alive at {now}")

async def set_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    await context.bot.set_webhook(f"{WEBHOOK_URL}/{BOT_TOKEN}")
    await update.message.reply_text("✅ Webhook refreshed.")

def get_utc_time(hour, minute, tz_name):
    tz = pytz.timezone(tz_name)
    local_time = tz.localize(datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0))
    return local_time.astimezone(pytz.utc).time()

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
