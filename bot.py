import logging
import os
import random
import pytz
from datetime import datetime, time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, ContextTypes, CallbackQueryHandler

# Logging
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

# Environment Variables (set in Render)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")  # Should be like: -100xxxxxxxxx
ADMIN_ID = os.getenv("ADMIN_ID")  # Your personal Telegram ID for heartbeat updates

# Timezone
GAZA_TZ = pytz.timezone("Asia/Gaza")

# Game Data
questions = [
    {"question": "What is the synonym of 'Happy'?", "options": ["Sad", "Joyful", "Tired", "Angry"], "answer": "Joyful", "explanation": "Joyful means happy."},
    {"question": "What is the past tense of 'Go'?", "options": ["Gone", "Went", "Goed", "Go"], "answer": "Went", "explanation": "Went is the correct past tense."},
    {"question": "Which word is a noun?", "options": ["Run", "Beautiful", "Apple", "Quickly"], "answer": "Apple", "explanation": "Apple is a noun."}
]
asked_questions = {}
answered_users = {}

# Initialize App
app = Application.builder().token(BOT_TOKEN).updater(None).build()

# Heartbeat alternating counter
heartbeat_counter = 0

# Helper - Send to Channel
async def send_question():
    global asked_questions, answered_users

    question = random.choice(questions)
    asked_questions[question['question']] = question
    answered_users[question['question']] = {}

    keyboard = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in question['options']]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await app.bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"📚 Question Time!\n\n{question['question']}",
        reply_markup=reply_markup
    )

# Callback for Button Answers
async def button_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    user_name = query.from_user.first_name
    data = query.data

    message = query.message.text

    for question, details in asked_questions.items():
        if question in message:
            if user_id in answered_users[question]:
                await query.answer("You already answered!")
                return

            correct_answer = details['answer']
            explanation = details['explanation']

            if data == correct_answer:
                if "first_correct" not in details:
                    details["first_correct"] = user_name
                    text = f"✅ Correct Answer: {correct_answer}\n🏅 First Correct: {user_name}\n\nℹ️ {explanation}"
                else:
                    text = f"✅ Correct Answer: {correct_answer}\n🏅 First Correct: {details['first_correct']}\n\nℹ️ {explanation}"
            else:
                text = f"❌ Wrong Answer.\n✅ Correct Answer: {correct_answer}\n\nℹ️ {explanation}"

            answered_users[question][user_id] = data

            await query.edit_message_text(text=text)
            return

# Daily Scheduler
async def daily_scheduler(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(GAZA_TZ).time()
    times = [time(8, 0), time(12, 0), time(18, 0)]

    if now in times:
        await send_question()

# Heartbeat Function
async def heartbeat(context: ContextTypes.DEFAULT_TYPE):
    global heartbeat_counter

    code_number = 1 if heartbeat_counter % 2 == 0 else 2
    heartbeat_counter += 1

    if ADMIN_ID:
        await app.bot.send_message(chat_id=ADMIN_ID, text=f"✅ Bot Heartbeat - Code {code_number} - Bot is Running.")

# Start Command (just for DM testing, not needed for channel work)
async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("Hello! I'm your Telegram bot running on Render.")

# Webhook Endpoint (for Render to trigger)
async def webhook(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await app.update_queue.put(update)

# Webhook Setup Function
async def set_webhook():
    webhook_url = os.getenv("RENDER_WEBHOOK_URL")
    await app.bot.set_webhook(f"{webhook_url}/webhook")

# Main Function
async def main():
    await set_webhook()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))

    # Daily question scheduler
    app.job_queue.run_repeating(daily_scheduler, interval=60, first=1)

    # Heartbeat every minute
    app.job_queue.run_repeating(heartbeat, interval=60, first=5)

    await app.start()
    await app.updater.start_polling()  # Only for local debugging, not used on Render
    await app.idle()

# Start the app
if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
