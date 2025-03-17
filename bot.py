import os
import logging
import random
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    JobQueue,
    filters
)
import pytz

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Question storage
QUESTIONS = [
    {
        "question": "What is the capital of France?",
        "options": ["Berlin", "Madrid", "Paris", "Rome"],
        "answer": "Paris",
        "explanation": "Paris has been the capital since 508 AD!"
    },
    {
        "question": "What is 2 + 2?",
        "options": ["3", "4", "5", "6"],
        "answer": "4",
        "explanation": "Basic arithmetic sum"
    }
]

class QuestionManager:
    def __init__(self):
        self.active_questions = {}  # {message_id: {question, answer, timestamp}}

    def add_question(self, message_id, question_data):
        self.active_questions[message_id] = {
            "question": question_data["question"],
            "answer": question_data["answer"],
            "timestamp": datetime.now(),
            "options": question_data["options"]
        }

    def get_answer(self, message_id):
        return self.active_questions.get(message_id)

    def cleanup_old_questions(self):
        cutoff = datetime.now() - timedelta(minutes=30)
        to_remove = [msg_id for msg_id, q in self.active_questions.items() 
                    if q["timestamp"] < cutoff]
        for msg_id in to_remove:
            del self.active_questions[msg_id]
        return len(to_remove)

question_manager = QuestionManager()

async def send_question(context: ContextTypes.DEFAULT_TYPE, is_test=False):
    try:
        # Select question
        question_data = random.choice(QUESTIONS) if is_test else QUESTIONS[datetime.now().day % len(QUESTIONS)]

        # Create buttons with unique identifiers
        buttons = [
            InlineKeyboardButton(text=opt, callback_data=f"ans_{opt}")
            for opt in question_data["options"]
        ]

        # Send message
        message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"📝 {'Test' if is_test else 'Daily'} Question:\n\n{question_data['question']}",
            reply_markup=InlineKeyboardMarkup([buttons])
        )

        # Store question state
        question_manager.add_question(message.message_id, question_data)
        return True

    except Exception as e:
        logger.error(f"Failed to send question: {e}")
        return False

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    message_id = query.message.message_id
    user_answer = query.data.split("_")[1]  # Extract answer from "ans_<answer>"
    question_data = question_manager.get_answer(message_id)

    if not question_data:
        await query.edit_message_text("⚠️ This question has expired")
        return

    if user_answer == question_data["answer"]:
        response = "✅ Correct!"
    else:
        response = (f"❌ Incorrect. Correct answer: {question_data['answer']}\n"
                   f"📖 Explanation: {next(q.get('explanation', '') for q in QUESTIONS 
                                   if q['question'] == question_data['question']}")

    await query.edit_message_text(
        text=f"{query.message.text}\n\n{response}",
        reply_markup=None
    )

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("⛔ Unauthorized access")
        return

    try:
        success = await send_question(context, is_test=True)
        if success:
            await update.message.reply_text("✅ Test question sent to channel!")
        else:
            await update.message.reply_text("❌ Failed to send test question")
    except Exception as e:
        logger.error(f"Test command error: {e}")
        await update.message.reply_text("🔥 Critical error in test command")

async def scheduled_question(context: ContextTypes.DEFAULT_TYPE):
    await send_question(context)

async def maintenance_job(context: ContextTypes.DEFAULT_TYPE):
    cleaned = question_manager.cleanup_old_questions()
    logger.info(f"Cleaned up {cleaned} old questions")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is running! Use /test to send a test question")

def main():
    application = Application.builder().token=BOT_TOKEN).build()

    # Schedule daily questions
    tz = pytz.timezone("Asia/Gaza")
    times = ["08:00", "12:30", "18:00"]
    
    for time_str in times:
        hour, minute = map(int, time_str.split(":"))
        application.job_queue.run_daily(
            scheduled_question,
            time=datetime.time(hour=hour, minute=minute, tzinfo=tz),
            days=tuple(range(7))
        )

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(CallbackQueryHandler(handle_answer, pattern=r"^ans_"))

    # Maintenance jobs
    application.job_queue.run_repeating(maintenance_job, interval=300, first=10)

    # Webhook setup
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        webhook_url=WEBHOOK_URL,
    )

if __name__ == "__main__":
    main()
