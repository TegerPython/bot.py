import json
import logging
import random
from datetime import datetime, time
from pytz import timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# Constants
BOT_TOKEN = "YOUR_BOT_TOKEN"
CHANNEL_ID = "@YourChannelUsername"
LEADERBOARD_FILE = "leaderboard.json"

# Questions
questions = [
    {
        "question": "What is the capital of France?",
        "options": ["Paris", "London", "Rome", "Berlin"],
        "correct": "Paris",
        "explanation": "Paris is the capital and largest city of France."
    },
    {
        "question": "What is 5 + 7?",
        "options": ["10", "11", "12", "13"],
        "correct": "12",
        "explanation": "5 + 7 equals 12."
    }
]

# Global variables
current_question = None
current_message_id = None
answered_users = set()

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load leaderboard
try:
    with open(LEADERBOARD_FILE, "r") as f:
        leaderboard = json.load(f)
except FileNotFoundError:
    logger.warning("⚠️ No leaderboard file found, starting fresh.")
    leaderboard = {}


async def send_daily_question(context: ContextTypes.DEFAULT_TYPE) -> None:
    global current_question, current_message_id, answered_users

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


async def send_question_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global current_question, current_message_id, answered_users

    answered_users = set()
    current_question = questions[datetime.now().day % len(questions)]

    keyboard = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in current_question["options"]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"📝 Manual Challenge:\n\n{current_question['question']}",
        reply_markup=reply_markup
    )
    current_message_id = message.message_id

    await update.message.reply_text("✅ Manual question sent!")


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global current_message_id

    query = update.callback_query
    user = query.from_user

    if user.id in answered_users:
        await query.answer("❌ You already answered this question.")
        return

    answered_users.add(user.id)

    if query.data == current_question["correct"]:
        points = 10
        leaderboard[str(user.id)] = leaderboard.get(str(user.id), 0) + points

        with open(LEADERBOARD_FILE, "w") as f:
            json.dump(leaderboard, f)

        winner_text = (
            f"🏆 {user.first_name} answered correctly!\n"
            f"➕ {points} points awarded.\n\n"
            f"✅ Correct Answer: {current_question['correct']}\n"
            f"ℹ️ {current_question['explanation']}"
        )
        await query.edit_message_text(winner_text)

    else:
        await query.answer("❌ Wrong answer!")


async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    text = "🏅 Leaderboard:\n\n"
    for user_id, score in sorted_leaderboard[:10]:
        user = await context.bot.get_chat(int(user_id))
        text += f"{user.first_name}: {score} points\n"
    await update.message.reply_text(text)


def main():
    application = Application.builder().token(BOT_TOKEN).build()

    job_queue = application.job_queue
    job_queue.timezone = timezone("Asia/Gaza")  # ✅ Set timezone globally, not in run_daily

    # Handlers
    application.add_handler(CommandHandler("start", show_leaderboard))
    application.add_handler(CommandHandler("leaderboard", show_leaderboard))
    application.add_handler(CommandHandler("sendquestion", send_question_manual))  # ✅ Manual trigger
    application.add_handler(CallbackQueryHandler(button))

    # Daily scheduled questions (at 8:00, 12:00, 18:00 Gaza time)
    job_queue.run_daily(send_daily_question, time(hour=8, minute=0))
    job_queue.run_daily(send_daily_question, time(hour=12, minute=0))
    job_queue.run_daily(send_daily_question, time(hour=18, minute=0))

    application.run_polling()


if __name__ == "__main__":
    main()
