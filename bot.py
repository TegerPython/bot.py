import os
import logging
import random
from datetime import datetime, timedelta
import pytz
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, ApplicationBuilder, MessageHandler, filters

# Enable Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment Variables
TOKEN = os.getenv('TOKEN')
OWNER_ID = int(os.getenv('OWNER_ID'))
CHANNEL_ID = os.getenv('CHANNEL_ID')
RENDER_WEBHOOK_URL = os.getenv('RENDER_WEBHOOK_URL')

# Flask App for Webhook
app = Flask(__name__)
application: Application = None

# Timezone
GAZA_TIME = pytz.timezone('Asia/Gaza')

# Heartbeat Tracking
heartbeat_code = 1

# Sample Questions (Replace with your real questions later)
QUESTIONS = [
    {"question": "What is the synonym of 'Happy'?", "options": ["Sad", "Joyful", "Angry", "Tired"], "answer": "Joyful", "explanation": "Happy and Joyful mean the same."},
    {"question": "Which word is a noun?", "options": ["Run", "Beautiful", "Chair", "Quickly"], "answer": "Chair", "explanation": "Chair is a noun (a thing)."},
]

# Question Tracking
current_question = None
first_correct_user = None
answered_users = set()

@app.route('/')
def home():
    return "Bot is running."

@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.json, application.bot)
    application.update_queue.put(update)
    return "ok"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I'm your Telegram bot running on Render using webhooks.")

async def send_heartbeat(context: ContextTypes.DEFAULT_TYPE):
    global heartbeat_code
    code = "Code 1" if heartbeat_code == 1 else "Code 2"
    heartbeat_code = 2 if heartbeat_code == 1 else 1
    await context.bot.send_message(chat_id=OWNER_ID, text=f"✅ Bot Heartbeat - {code} - Bot is Running.")

async def post_question(context: ContextTypes.DEFAULT_TYPE):
    global current_question, first_correct_user, answered_users
    current_question = random.choice(QUESTIONS)
    first_correct_user = None
    answered_users = set()

    keyboard = [
        [InlineKeyboardButton(option, callback_data=option)] for option in current_question['options']
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = f"📚 English Challenge Time!\n\n{current_question['question']}"
    await context.bot.send_message(chat_id=CHANNEL_ID, text=text, reply_markup=reply_markup)

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global first_correct_user, answered_users

    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.first_name

    if user_id in answered_users:
        await query.answer("❌ You've already answered!")
        return

    answered_users.add(user_id)

    selected_option = query.data
    correct_answer = current_question['answer']

    if selected_option == correct_answer:
        if first_correct_user is None:
            first_correct_user = username
        await query.edit_message_text(
            text=f"✅ Correct Answer: {correct_answer}\nExplanation: {current_question['explanation']}\n\n🏅 First Correct Answer: {first_correct_user}"
        )
        await query.answer("✅ Correct!")
    else:
        await query.answer("❌ Wrong! No second chances.")
        await query.edit_message_text(
            text=f"❌ Incorrect Answer: {selected_option}\n\n✅ Correct Answer: {correct_answer}\nExplanation: {current_question['explanation']}\n\n🏅 First Correct Answer: {first_correct_user or 'None yet'}"
        )

def main():
    global application

    # Set up the bot application
    application = ApplicationBuilder().token(TOKEN).updater(None).build()

    # Command Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_answer))

    # Gaza Time Scheduling (3 questions a day)
    gaza_now = datetime.now(GAZA_TIME)
    context_job_queue = application.job_queue

    context_job_queue.run_repeating(send_heartbeat, interval=60, first=0)

    schedule_times = ["08:00", "12:00", "18:00"]
    for time_str in schedule_times:
        hour, minute = map(int, time_str.split(":"))
        next_run = gaza_now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        if next_run < gaza_now:
            next_run += timedelta(days=1)

        context_job_queue.run_daily(post_question, time=next_run.time(), timezone=GAZA_TIME)

    # Set Webhook (very important)
    webhook_url = f"{RENDER_WEBHOOK_URL}/webhook"
    application.bot.set_webhook(webhook_url)

    # Start Flask App
    app.run(host="0.0.0.0", port=10000)

if __name__ == '__main__':
    main()
