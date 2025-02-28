import os
import logging
import asyncio
from datetime import datetime, date
import pytz
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

# Load environment variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")  # Example: -1001234567890
ADMIN_ID = os.getenv("ADMIN_ID")  # Optional, for heartbeat if needed

# Setup logging
logging.basicConfig(level=logging.INFO)

# Timezone (Gaza/Palestine)
GAZA_TZ = pytz.timezone('Asia/Gaza')

# Bot & Application
bot = Bot(TOKEN)
application = Application.builder().token(TOKEN).build()

# Active question data
current_question = None
current_message_id = None
correct_answer = None
answer_explanation = None
first_correct_user = None

# Track user answers to prevent retry (anti-cheat)
answered_users = set()


# Example question - replace later with dynamic system
QUESTION = "What is the past tense of 'go'?"
OPTIONS = [
    ("A) Goed", "A"),
    ("B) Went", "B"),
    ("C) Goes", "C"),
    ("D) Going", "D")
]
correct_answer = "B"
answer_explanation = "The correct past tense of 'go' is 'went'."

async def send_question():
    global current_question, current_message_id, correct_answer, answer_explanation, first_correct_user, answered_users

    current_question = QUESTION
    first_correct_user = None
    answered_users = set()

    keyboard = [
        [InlineKeyboardButton(text, callback_data=callback) for text, callback in OPTIONS]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = await bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"📚 Daily English Question:\n\n{current_question}",
        reply_markup=reply_markup
    )

    current_message_id = message.message_id
    logging.info(f"Question sent to channel at {datetime.now(GAZA_TZ)}")

# Handle button clicks (answers)
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global first_correct_user

    query = update.callback_query
    user_id = query.from_user.id
    user_name = query.from_user.first_name

    if user_id in answered_users:
        await query.answer("❌ You have already answered this question.")
        return

    user_answer = query.data

    if user_answer == correct_answer:
        if first_correct_user is None:
            first_correct_user = user_name
            await announce_correct_answer()

        await query.answer("✅ Correct! Well done.")
    else:
        await query.answer("❌ Incorrect! You can't try again.")

    answered_users.add(user_id)

# Edit the message to show correct answer & explanation
async def announce_correct_answer():
    global current_message_id, first_correct_user

    explanation_text = (
        f"✅ Correct Answer: {correct_answer}\n\n"
        f"ℹ️ Explanation: {answer_explanation}\n\n"
        f"🏅 First Correct Answer: {first_correct_user}\n\n"
        "🔔 Stay tuned for the next question!"
    )

    try:
        await bot.edit_message_text(
            chat_id=CHANNEL_ID,
            message_id=current_message_id,
            text=f"📚 Daily English Question:\n\n{current_question}\n\n{explanation_text}"
        )
    except Exception as e:
        logging.error(f"Failed to edit message: {e}")

# Daily scheduler (3 times a day)
async def schedule_questions():
    last_sent_dates = {"08:00": None, "12:00": None, "16:28": None}

    while True:
        now = datetime.now(GAZA_TZ)
        current_time = now.strftime("%H:%M")

        if current_time in last_sent_dates and last_sent_dates[current_time] != date.today():
            await send_question()
            last_sent_dates[current_time] = date.today()

        await asyncio.sleep(30)

# Heartbeat system - optional
async def heartbeat():
    if not ADMIN_ID:
        return
    codes = ["Code 1", "Code 2"]
    index = 0

    while True:
        try:
            await bot.send_message(chat_id=ADMIN_ID, text=f"✅ Bot Heartbeat - {codes[index]} - Bot is Running.")
            index = 1 - index  # Alternate between 0 and 1
        except Exception as e:
            logging.error(f"Failed to send heartbeat: {e}")

        await asyncio.sleep(60)

# Start bot
async def main():
    application.add_handler(CallbackQueryHandler(handle_answer))

    asyncio.create_task(schedule_questions())
    asyncio.create_task(heartbeat())

    await application.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
