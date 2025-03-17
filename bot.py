import os
import logging
import random
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    JobQueue
)
import pytz

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Question configuration
QUESTIONS = [
    {
        "question": "What is the capital of France?",
        "options": ["Berlin", "Madrid", "Paris", "Rome"],
        "answer": "Paris"
    },
    {
        "question": "What is 2 + 2?",
        "options": ["3", "4", "5", "6"],
        "answer": "4"
    }
]

# State management
active_questions = {}  # {message_id: {question, answer, expires_at}}

async def send_question(context: ContextTypes.DEFAULT_TYPE, is_test=False):
    try:
        # Select question
        if is_test:
            question_data = random.choice(QUESTIONS)
        else:
            question_data = QUESTIONS[datetime.now().day % len(QUESTIONS)]

        # Create keyboard
        keyboard = [
            [InlineKeyboardButton(opt, callback_data=opt)]
            for opt in question_data["options"]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send message
        message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"📝 {'Test' if is_test else 'Daily'} Question:\n\n{question_data['question']}",
            reply_markup=reply_markup
        )

        # Store question state
        active_questions[message.message_id] = {
            "question": question_data["question"],
            "answer": question_data["answer"],
            "expires_at": datetime.now() + timedelta(minutes=30),
            "is_test": is_test
        }

        return True, message.message_id

    except Exception as e:
        logger.error(f"Error sending question: {e}")
        return False, None

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    message_id = query.message.message_id
    selected_answer = query.data

    # Get question state
    question_state = active_questions.get(message_id)
    
    if not question_state:
        await query.edit_message_text("⌛ This question has expired")
        return

    if selected_answer == question_state["answer"]:
        response = "✅ Correct!"
    else:
        response = f"❌ Incorrect. The correct answer was {question_state['answer']}"

    # Update message and remove keyboard
    await query.edit_message_text(
        text=f"{query.message.text}\n\n{response}",
        reply_markup=None
    )

    # Remove from active questions
    del active_questions[message_id]

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("🚫 Unauthorized")
        return

    success, message_id = await send_question(context, is_test=True)
    if success:
        await update.message.reply_text("✅ Test question sent to channel!")
    else:
        await update.message.reply_text("❌ Failed to send test question")

async def cleanup_job(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    expired = [msg_id for msg_id, q in active_questions.items() if q["expires_at"] < now]
    
    for msg_id in expired:
        try:
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=msg_id,
                text=f"{active_questions[msg_id]['question']}\n\n⌛ Question expired",
                reply_markup=None
            )
            del active_questions[msg_id]
        except Exception as e:
            logger.error(f"Error cleaning up message {msg_id}: {e}")

async def scheduled_question(context: ContextTypes.DEFAULT_TYPE):
    await send_question(context)

async def heartbeat(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=f"💓 Bot status: {len(active_questions)} active questions"
    )

def get_utc_time(hour: int, minute: int, timezone: str):
    tz = pytz.timezone(timezone)
    local_time = tz.localize(datetime.now().replace(hour=hour, minute=minute))
    return local_time.astimezone(pytz.utc).time()

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Schedule daily questions
    job_queue = application.job_queue
    job_queue.run_daily(
        scheduled_question,
        get_utc_time(8, 0, "Asia/Gaza")
    )
    job_queue.run_daily(
        scheduled_question,
        get_utc_time(12, 30, "Asia/Gaza")
    )
    job_queue.run_daily(
        scheduled_question,
        get_utc_time(18, 0, "Asia/Gaza")
    )

    # Add maintenance jobs
    job_queue.run_repeating(cleanup_job, interval=300, first=10)  # Every 5 minutes
    job_queue.run_repeating(heartbeat, interval=3600)  # Every hour

    # Add handlers
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(CallbackQueryHandler(handle_answer))

    # Webhook configuration
    port = int(os.environ.get("PORT", 5000))
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
    )

if __name__ == "__main__":
    main()
    
