import os
import json
import logging
import asyncio
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
WEBHOOK_URL = os.getenv("RENDER_WEBHOOK_URL")

# Leaderboard file
LEADERBOARD_FILE = "leaderboard.json"

# Questions
questions = [
    {"question": "What is the capital of France?", "options": ["Berlin", "Madrid", "Paris", "Rome"], "answer": "Paris", "explanation": "Paris is the capital city of France."},
    {"question": "2 + 2 equals?", "options": ["3", "4", "5", "6"], "answer": "4", "explanation": "Simple math!"}
]

leaderboard = {}
answered_users = set()
current_question = None
current_message_id = None

def load_leaderboard():
    global leaderboard
    if os.path.exists(LEADERBOARD_FILE):
        with open(LEADERBOARD_FILE, "r") as file:
            leaderboard = json.load(file)
    else:
        logger.warning("⚠️ No leaderboard file found, starting fresh.")
        leaderboard = {}

def save_leaderboard():
    with open(LEADERBOARD_FILE, "w") as file:
        json.dump(leaderboard, file, indent=2)

async def send_question(context: ContextTypes.DEFAULT_TYPE, is_test=False) -> None:
    global current_question, answered_users, current_message_id
    answered_users = set()

    if is_test:
        current_question = random.choice(questions)
    else:
        current_question = questions[datetime.now().day % len(questions)]

    keyboard = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in current_question["options"]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"📝 {'Test' if is_test else 'Daily'} Challenge:\n\n{current_question['question']}",
        reply_markup=reply_markup
    )
    current_message_id = message.message_id

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

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    text = "🏆 Leaderboard:\n\n" + "\n".join([f"{name}: {points} points" for name, points in sorted_leaderboard])
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)

async def heartbeat(context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await context.bot.send_message(chat_id=OWNER_ID, text=f"💓 Heartbeat check - Bot is alive at {now}")

async def send_daily_leaderboard(context: ContextTypes.DEFAULT_TYPE) -> None:
    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    text = "🏆 Daily Leaderboard:\n\n" + "\n".join([f"{name}: {points} points" for name, points in sorted_leaderboard])
    await context.bot.send_message(chat_id=CHANNEL_ID, text=text)

async def test_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    await send_question(context, is_test=True)
    await update.message.reply_text("✅ Test question sent.")

def get_utc_time(hour, minute, tz_name):
    tz = pytz.timezone(tz_name)
    local_time = tz.localize(datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0))
    return local_time.astimezone(pytz.utc).time()

def main():
    load_leaderboard()

    application = Application.builder().token(BOT_TOKEN).build()
    job_queue = application.job_queue

    # Use pytz conversion for Gaza timezone times
    job_queue.run_daily(send_question, get_utc_time(8, 0, "Asia/Gaza"))
    job_queue.run_daily(send_question, get_utc_time(12, 0, "Asia/Gaza"))
    job_queue.run_daily(send_question, get_utc_time(18, 0, "Asia/Gaza"))
    job_queue.run_daily(send_daily_leaderboard, get_utc_time(23, 59, "Asia/Gaza"))

    job_queue.run_repeating(heartbeat, interval=60)

    application.add_handler(CommandHandler("leaderboard", show_leaderboard))
    application.add_handler(CommandHandler("test", test_question))
    application.add_handler(CallbackQueryHandler(handle_answer))

    # Webhook configuration
    application.run_webhook(
    listen="0.0.0.0",
    port=int(os.getenv("PORT", 8443)),  # Use the correct port
    url_path=BOT_TOKEN,
    webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
)


if __name__ == "__main__":
    main()
