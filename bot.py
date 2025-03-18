import os
import logging
import random
import signal
import sys
from datetime import datetime, time, timedelta
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
        self.active_questions = {}

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
        logger.info("Attempting to send question...")
        question_data = random.choice(QUESTIONS) if is_test else QUESTIONS[datetime.now().day % len(QUESTIONS)]
        
        buttons = [
            InlineKeyboardButton(text=opt, callback_data=f"ans_{opt}")
            for opt in question_data["options"]
        ]

        message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"📝 {'Test' if is_test else 'Daily'} Question:\n\n{question_data['question']}",
            reply_markup=InlineKeyboardMarkup([buttons])
        )

        question_manager.add_question(message.message_id, question_data)
        logger.info(f"Question sent successfully! Message ID: {message.message_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to send question: {str(e)}")
        return False

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        logger.info(f"Received answer from {query.from_user.id}")

        message_id = query.message.message_id
        user_answer = query.data.split("_")[1]
        question_data = question_manager.get_answer(message_id)

        if not question_data:
            await query.edit_message_text("⚠️ This question has expired")
            return

        response = ("✅ Correct!" if user_answer == question_data["answer"] else 
                   f"❌ Incorrect. Correct answer: {question_data['answer']}\n📖 Explanation: {next((q.get('explanation', '') for q in QUESTIONS if q['question'] == question_data['question'], 'No explanation')}")
        
        await query.edit_message_text(text=f"{query.message.text}\n\n{response}", reply_markup=None)
    except Exception as e:
        logger.error(f"Error handling answer: {str(e)}")

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info(f"Received test command from {update.effective_user.id}")
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text("⛔ Unauthorized access")
            return

        success = await send_question(context, is_test=True)
        response = "✅ Test question sent!" if success else "❌ Failed to send test question"
        await update.message.reply_text(response)
    except Exception as e:
        logger.error(f"Test command error: {str(e)}")
        await update.message.reply_text("🔧 Error processing test command")

async def scheduled_question(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Executing scheduled question job")
    await send_question(context)

async def heartbeat(context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info("Sending heartbeat...")
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=f"💓 Bot Status:\nActive Questions: {len(question_manager.active_questions)}\nLast Check: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    except Exception as e:
        logger.error(f"Heartbeat failed: {str(e)}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot is operational!\nUse /test to send a test question")

async def debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    status_report = (
        f"🛠️ Debug Info:\n"
        f"Active Questions: {len(question_manager.active_questions)}\n"
        f"Scheduled Jobs: {len(context.application.job_queue.jobs())}\n"
        f"Last Maintenance: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await update.message.reply_text(status_report)

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Clear existing jobs
    if application.job_queue:
        application.job_queue.scheduler.remove_all_jobs()

    # Schedule daily questions with precise timezone handling
    tz = pytz.timezone("Asia/Gaza")
    schedule_times = [
        tz.localize(datetime.strptime("08:00", "%H:%M")).time(),
        tz.localize(datetime.strptime("12:30", "%H:%M")).time(),
        tz.localize(datetime.strptime("18:00", "%H:%M")).time()
    ]

    for target_time in schedule_times:
        application.job_queue.run_daily(
            scheduled_question,
            time=target_time,
            days=tuple(range(7)),
            name=f"ScheduledQuestion_{target_time}"
        )

    # Add handlers with explicit filters
    application.add_handler(CommandHandler("start", start, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("test", test_command, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("debug", debug, filters=filters.User(OWNER_ID)))
    application.add_handler(CallbackQueryHandler(handle_answer, pattern=r"^ans_"))

    # Configure jobs with unique IDs
    application.job_queue.run_repeating(
        maintenance_job,
        interval=300,
        first=10,
        name="Maintenance"
    )
    application.job_queue.run_repeating(
        heartbeat,
        interval=60,  # 1 minute heartbeat
        first=5,
        name="Heartbeat"
    )

    # Webhook verification
    async def post_init(application: Application):
        await application.bot.set_webhook(WEBHOOK_URL)
        logger.info("Webhook configured successfully")
        logger.info(f"Current jobs: {application.job_queue.jobs()}")

    application.post_init(post_init)

    # Error handling
    application.add_error_handler(lambda update, context: logger.error(f"Update {update} caused error: {context.error}"))

    # Start the bot
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        webhook_url=WEBHOOK_URL,
    )

if __name__ == "__main__":
    main()
