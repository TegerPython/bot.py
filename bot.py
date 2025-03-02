import os
import json
import random
import asyncio
import logging
from datetime import datetime, timedelta, time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from pytz import timezone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load BOT_TOKEN from environment
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in environment variables.")

# Config
CHANNEL_ID = "@your_channel_username"
ADMIN_ID = "your_admin_user_id"
QUESTIONS_FILE = "questions.json"
LEADERBOARD_FILE = "leaderboard.json"
heartbeat_code = "1111"
last_question_message_id = None
last_question_data = None

# Heartbeat counter
heartbeat_counter = 0

def load_questions():
    with open(QUESTIONS_FILE, "r", encoding="utf-8") as file:
        return json.load(file)

def load_leaderboard():
    if os.path.exists(LEADERBOARD_FILE):
        with open(LEADERBOARD_FILE, "r") as file:
            return json.load(file)
    else:
        logger.warning("⚠️ No leaderboard file found, starting fresh.")
        return {}

def save_leaderboard(data):
    with open(LEADERBOARD_FILE, "w") as file:
        json.dump(data, file, indent=2)

leaderboard = load_leaderboard()

async def send_heartbeat(context: ContextTypes.DEFAULT_TYPE):
    global heartbeat_counter, heartbeat_code
    heartbeat_counter += 1
    heartbeat_code = "1111" if heartbeat_counter % 2 == 0 else "2222"
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"💓 Heartbeat {heartbeat_code}")
    except Exception as e:
        logger.error(f"Failed to send heartbeat: {e}")

async def send_daily_question(context: ContextTypes.DEFAULT_TYPE):
    global last_question_message_id, last_question_data

    questions = load_questions()
    question_data = random.choice(questions)
    last_question_data = question_data

    keyboard = [
        [InlineKeyboardButton(opt, callback_data=f"answer|{idx}") for idx, opt in enumerate(question_data["options"])]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"🧠 Daily Question:\n\n{question_data['question']}",
        reply_markup=reply_markup
    )

    last_question_message_id = message.message_id

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global last_question_message_id, last_question_data

    query = update.callback_query
    user = update.effective_user
    user_id = str(user.id)

    if not last_question_data:
        await query.answer("❌ No active question.")
        return

    selected_idx = int(query.data.split("|")[1])
    correct_idx = last_question_data["correct"]

    if selected_idx == correct_idx:
        points = 10
        text = (f"🎉 Correct! {user.first_name} was the first to answer.\n\n"
                f"✅ Answer: {last_question_data['options'][correct_idx]}\n\n"
                f"📚 Explanation: {last_question_data['explanation']}\n\n"
                f"🏆 {user.first_name} earned {points} points!")

        leaderboard[user_id] = leaderboard.get(user_id, 0) + points
        save_leaderboard(leaderboard)

        await query.answer("✅ Correct!")
        await update.callback_query.edit_message_text(text=text)
        last_question_message_id = None  # Clear for the next question
    else:
        await query.answer("❌ Wrong answer. Better luck next time!")

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    text = "🏅 Leaderboard:\n\n"
    for idx, (user_id, points) in enumerate(sorted_leaderboard[:10], 1):
        user = await context.bot.get_chat(user_id)
        text += f"{idx}. {user.first_name}: {points} points\n"
    await update.message.reply_text(text)

def convert_gaza_to_utc(gaza_hour, gaza_minute):
    gaza = timezone("Asia/Gaza")
    gaza_time = datetime.now(gaza).replace(hour=gaza_hour, minute=gaza_minute, second=0, microsecond=0)
    utc_time = gaza_time.astimezone(timezone("UTC"))
    return utc_time.time()

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler("leaderboard", show_leaderboard))
    application.add_handler(CallbackQueryHandler(handle_answer))

    # JobQueue for scheduled tasks (converted times)
    job_queue = application.job_queue

    times_gaza = [
        (8, 0),  # 8:00 AM Gaza
        (12, 0), # 12:00 PM Gaza
        (18, 0)  # 6:00 PM Gaza
    ]

    for hour, minute in times_gaza:
        utc_time = convert_gaza_to_utc(hour, minute)
        job_queue.run_daily(send_daily_question, time(hour=utc_time.hour, minute=utc_time.minute))

    job_queue.run_repeating(send_heartbeat, interval=60, first=0)

    application.run_polling()

if __name__ == "__main__":
    main()
