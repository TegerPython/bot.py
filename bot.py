import os
import logging
import pytz
from flask import Flask, request, jsonify
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, ApplicationBuilder
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime

# Load environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')
OWNER_ID = int(os.getenv('OWNER_ID'))  # Your Telegram ID for heartbeats
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

# Set up logging
logging.basicConfig(level=logging.INFO)

# Set up Flask app
app = Flask(__name__)

# Set up Telegram bot and application
bot = Bot(token=BOT_TOKEN)
app_builder = ApplicationBuilder().token(BOT_TOKEN).updater(None).build()

# Set up scheduler
scheduler = BackgroundScheduler(timezone=pytz.timezone('Asia/Gaza'))

# Heartbeat control
heartbeat_code = 1

# Track who answered which question
answered_users = {}
current_question_id = None
questions = [
    {"question": "What is the synonym of 'happy'?", "options": ["Sad", "Angry", "Joyful", "Tired"], "correct": 2, "explanation": "Joyful means the same as happy."},
    {"question": "What is the antonym of 'fast'?", "options": ["Quick", "Slow", "Bright", "Sharp"], "correct": 1, "explanation": "Slow is the opposite of fast."},
    {"question": "Which word is a noun?", "options": ["Run", "Beautiful", "Apple", "Quickly"], "correct": 2, "explanation": "Apple is a noun."},
]

# Function to send a question
async def send_question(context: ContextTypes.DEFAULT_TYPE):
    global current_question_id, answered_users
    current_question_id = datetime.now().strftime("%Y%m%d%H%M")
    answered_users = {}

    question_data = context.job.data
    keyboard = [
        [InlineKeyboardButton(option, callback_data=f"{i}") for i, option in enumerate(question_data['options'])]
    ]

    message = f"🎯 Daily Question:\n\n{question_data['question']}"
    await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if user_id in answered_users:
        await query.answer("❌ You already answered this question!")
        return

    selected_option = int(query.data)
    question_data = questions[0]  # Current question - simple demo for now

    if selected_option == question_data['correct']:
        await query.answer("✅ Correct!")
        answered_users[user_id] = True
        await context.bot.edit_message_text(
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            text=f"🎯 Question: {question_data['question']}\n\n✅ Correct Answer: {question_data['options'][question_data['correct']]}\n\nExplanation: {question_data['explanation']}\n\n🏅 First Correct: {query.from_user.full_name}"
        )
    else:
        answered_users[user_id] = False
        await query.answer("❌ Wrong answer!")

# Heartbeat sender
async def send_heartbeat():
    global heartbeat_code
    await bot.send_message(chat_id=OWNER_ID, text=f"✅ Bot Heartbeat - Code {heartbeat_code} - Bot is Running.")
    heartbeat_code = 2 if heartbeat_code == 1 else 1

@app.route('/', methods=['GET'])
def index():
    return "Bot is running!", 200

@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(), bot)
    app_builder.process_update(update)
    return "ok", 200

# Start-up initialization
async def start_bot():
    await bot.set_webhook(f'{WEBHOOK_URL}/{BOT_TOKEN}')
    logging.info(f"Webhook set to {WEBHOOK_URL}/{BOT_TOKEN}")

def schedule_questions():
    times = ["08:00", "12:00", "18:00"]
    for idx, time in enumerate(times):
        hour, minute = map(int, time.split(":"))
        scheduler.add_job(
            app_builder.job_queue.run_once,
            CronTrigger(hour=hour, minute=minute, timezone="Asia/Gaza"),
            args=[send_question],
            kwargs={"data": questions[idx]},
        )

def main():
    app_builder.add_handler(CallbackQueryHandler(button_handler))

    schedule_questions()
    scheduler.add_job(send_heartbeat, 'interval', minutes=1)

    scheduler.start()
    app_builder.run_webhook(listen="0.0.0.0", port=10000, webhook_url=f'{WEBHOOK_URL}/{BOT_TOKEN}')

if __name__ == '__main__':
    import asyncio
    asyncio.run(start_bot())
    app.run(host='0.0.0.0', port=10000)
