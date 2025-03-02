import os
import json
import logging
import asyncio
from datetime import time, datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, JobQueue
from pytz import timezone

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))
WEBHOOK_URL = os.getenv("RENDER_WEBHOOK_URL")

# Leaderboard file
LEADERBOARD_FILE = "leaderboard.json"

# Questions (Add your own)
questions = [
    {"question": "What is the capital of France?", "options": ["Berlin", "Madrid", "Paris", "Rome"], "answer": "Paris", "explanation": "Paris is the capital city of France."},
    {"question": "2 + 2 equals?", "options": ["3", "4", "5", "6"], "answer": "4", "explanation": "Simple math!"},
]

# Leaderboard and state
leaderboard = {}
answered_users = set()
current_question = None
current_message_id = None

# Load leaderboard from file
def load_leaderboard():
    global leaderboard
    if os.path.exists(LEADERBOARD_FILE):
        with open(LEADERBOARD_FILE, "r") as file:
            leaderboard = json.load(file)
    else:
        logger.warning("⚠️ No leaderboard file found, starting fresh.")
        leaderboard = {}

# Save leaderboard to file
def save_leaderboard():
    with open(LEADERBOARD_FILE, "w") as file:
        json.dump(leaderboard, file, indent=2)

# Send daily question
async def send_daily_question(context: ContextTypes.DEFAULT_TYPE) -> None:
    global current_question, answered_users, current_message_id
    answered_users = set()
    current_question = questions[datetime.now().day % len(questions)]

    keyboard = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in current_question["options"]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"📝 Daily Challenge:\n\n{current_question['question']}",
        reply_markup=reply_markup
    )

    current_message_id = message.message_id

# Handle answer callback
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global answered_users, current_question, current_message_id

    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.first_name

    if user_id in answered_users:
        await query.answer("❌ You already answered this question.")
        return

    answered_users.add(user_id)
    user_answer = query.data
    correct = user_answer == current_question["answer"]

    if correct:
        await query.answer("✅ Correct!")

        leaderboard[username] = leaderboard.get(username, 0) + 1
        save_leaderboard()

        explanation = current_question.get("explanation", "No explanation provided.")
        edited_text = (
            "📝 Daily Challenge (Answered)\n\n"
            f"Question: {current_question['question']}\n"
            f"✅ Correct Answer: {current_question['answer']}\n"
            f"ℹ️ Explanation: {explanation}\n\n"
            f"🏆 Winner: {username} (+1 point)"
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

# Show leaderboard
async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    text = "🏆 Leaderboard:\n\n" + "\n".join([f"{name}: {points} points" for name, points in sorted_leaderboard])
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)

# Heartbeat - Bot health check to OWNER
async def heartbeat(context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(chat_id=OWNER_ID, text=f"💓 Heartbeat check - Bot is alive at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# Send daily leaderboard to channel
async def send_daily_leaderboard(context: ContextTypes.DEFAULT_TYPE) -> None:
    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    text = "🏆 Daily Leaderboard:\n\n" + "\n".join([f"{name}: {points} points" for name, points in sorted_leaderboard])
    await context.bot.send_message(chat_id=CHANNEL_ID, text=text)

# Main function
def main():
    load_leaderboard()

    application = Application.builder().token(BOT_TOKEN).build()

    job_queue = application.job_queue

    # Schedule jobs (adjusted for Asia/Gaza)
    job_queue.run_daily(send_daily_question, time(hour=8, minute=0), timezone="Asia/Gaza")
    job_queue.run_daily(send_daily_question, time(hour=14, minute=40), timezone="Asia/Gaza")
    job_queue.run_daily(send_daily_question, time(hour=18, minute=0), timezone="Asia/Gaza")
    job_queue.run_daily(send_daily_leaderboard, time(hour=23, minute=59), timezone="Asia/Gaza")

    # Heartbeat every 5 minutes
    job_queue.run_repeating(heartbeat, interval=300)

    # Handlers
    application.add_handler(CommandHandler("leaderboard", show_leaderboard))
    application.add_handler(CallbackQueryHandler(handle_answer))

    # Start bot (webhook mode)
    async def start():
        await application.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
        await application.start()
        logger.info("🚀 Bot started with webhook.")
        await application.updater.start_webhook(
            listen="0.0.0.0",
            port=8000,
            url_path="webhook",
            webhook_url=f"{WEBHOOK_URL}/webhook"
        )

    asyncio.run(start())

if __name__ == "__main__":
    main()
