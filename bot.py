import os
import logging
import random
from datetime import datetime, timedelta
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

# Questions and state management
questions = [
    {"question": "What is the capital of France?", "options": ["Berlin", "Madrid", "Paris", "Rome"], "answer": "Paris"},
    {"question": "2 + 2 equals?", "options": ["3", "4", "5", "6"], "answer": "4"}
]

active_questions = {}  # {message_id: {question, answer, expires_at}}

async def send_question(context: ContextTypes.DEFAULT_TYPE, is_test=False):
    try:
        if is_test:
            question_data = random.choice(questions)
        else:
            question_data = questions[datetime.now().day % len(questions)]

        keyboard = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in question_data["options"]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"📝 {'Test' if is_test else 'Daily'} Challenge:\n\n{question_data['question']}",
            reply_markup=reply_markup
        )

        # Store question with expiration (30 minutes)
        active_questions[message.message_id] = {
            "question": question_data["question"],
            "answer": question_data["answer"],
            "expires_at": datetime.now() + timedelta(minutes=30)
        }

        return True, message.message_id
    except Exception as e:
        logger.error(f"Failed to send question: {e}")
        return False, None

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    message_id = query.message.message_id
    user_answer = query.data

    # Check if question is still active
    question_data = active_questions.get(message_id)
    if not question_data:
        await query.answer("⌛ This question has expired")
        return

    if user_answer == question_data["answer"]:
        await query.answer("✅ Correct!")
    else:
        await query.answer(f"❌ Incorrect. Correct answer was {question_data['answer']}")

async def test_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Unauthorized")
        return

    success, message_id = await send_question(context, is_test=True)
    if success:
        await update.message.reply_text("✅ Test question sent to channel!")
    else:
        await update.message.reply_text("❌ Failed to send test question")

async def cleanup_questions(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    expired = [msg_id for msg_id, q in active_questions.items() if q["expires_at"] < now]
    
    for msg_id in expired:
        try:
            await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=msg_id)
            del active_questions[msg_id]
        except Exception as e:
            logger.error(f"Error cleaning up message {msg_id}: {e}")

async def heartbeat(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=f"💓 Status at {now}\nActive questions: {len(active_questions)}"
    )

def get_utc_time(hour, minute, tz_name):
    tz = pytz.timezone(tz_name)
    local_time = tz.localize(datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0))
    return local_time.astimezone(pytz.utc).time()

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    job_queue = application.job_queue

    # Schedule daily questions
    job_queue.run_daily(lambda ctx: send_question(ctx), get_utc_time(8, 0, "Asia/Gaza"))
    job_queue.run_daily(lambda ctx: send_question(ctx), get_utc_time(12, 30, "Asia/Gaza"))
    job_queue.run_daily(lambda ctx: send_question(ctx), get_utc_time(18, 0, "Asia/Gaza"))

    # Maintenance jobs
    job_queue.run_repeating(cleanup_questions, interval=300)  # 5 minutes
    job_queue.run_repeating(heartbeat, interval=3600)  # 1 hour

    # Handlers
    application.add_handler(CommandHandler("test", test_question))
    application.add_handler(CallbackQueryHandler(handle_answer))

    # Webhook setup
    port = int(os.environ.get("PORT", 5000))
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
    )

if __name__ == "__main__":
    main()
