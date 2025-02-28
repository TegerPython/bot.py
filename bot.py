import os
import json
import random
import pytz
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import CommandHandler, CallbackQueryHandler, Dispatcher

app = Flask(__name__)

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
OWNER_ID = int(os.getenv('OWNER_TELEGRAM_ID'))
CHANNEL_ID = os.getenv('CHANNEL_ID')  # Use -100xxxxxxxx format
WEBHOOK_URL = os.getenv('RENDER_WEBHOOK_URL')

bot = Bot(token=TOKEN)

# Tracking states
questions = [
    {
        "question": "What is the past tense of 'go'?",
        "options": ["goes", "went", "gone", "going"],
        "correct": 1,
        "explanation": "The past tense of 'go' is 'went'."
    },
    {
        "question": "Which is a synonym for 'happy'?",
        "options": ["sad", "angry", "joyful", "tired"],
        "correct": 2,
        "explanation": "'Joyful' is a synonym for 'happy'."
    }
]
current_question = None
answered_users = {}

# Gaza timezone
gaza_tz = pytz.timezone('Asia/Gaza')

# Dispatcher setup (used for handling commands via webhook)
dispatcher = Dispatcher(bot, None, workers=4)

# Anti-cheating: Track user answers
user_answers = {}
first_correct_user = None

@app.route('/')
def home():
    return "Bot is running!"

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "ok", 200

def start(update, context):
    update.message.reply_text("Hello! I'm your English Quiz Bot running on Render.")

def post_question():
    global current_question, answered_users, first_correct_user

    if not questions:
        return

    current_question = random.choice(questions)
    answered_users = {}
    first_correct_user = None

    keyboard = [
        [InlineKeyboardButton(opt, callback_data=str(idx))] for idx, opt in enumerate(current_question["options"])
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"📚 English Question Time!\n\n{current_question['question']}",
        reply_markup=reply_markup
    )

def handle_answer(update, context):
    global first_correct_user

    query = update.callback_query
    user_id = query.from_user.id

    if user_id in answered_users:
        query.answer("You've already answered this question!")
        return

    user_choice = int(query.data)
    answered_users[user_id] = user_choice

    if user_choice == current_question['correct']:
        if first_correct_user is None:
            first_correct_user = query.from_user.first_name
        query.answer("✅ Correct!")
    else:
        query.answer("❌ Wrong! No second chances.")

    if len(answered_users) == 1:  # First answer triggers explanation update
        edit_question_message()

def edit_question_message():
    correct_option = current_question['options'][current_question['correct']]
    explanation = current_question['explanation']

    text = f"📚 English Question Time!\n\n{current_question['question']}\n\n"
    text += f"✅ Correct Answer: {correct_option}\n\n"
    text += f"📖 Explanation: {explanation}\n\n"

    if first_correct_user:
        text += f"🏅 First Correct Answer: {first_correct_user}"

    bot.send_message(chat_id=CHANNEL_ID, text=text)

# Scheduler Setup
def schedule_questions(context):
    now = datetime.now(gaza_tz)
    times = [
        now.replace(hour=8, minute=0, second=0, microsecond=0),
        now.replace(hour=12, minute=0, second=0, microsecond=0),
        now.replace(hour=17, minute=20, second=0, microsecond=0),
    ]

    for t in times:
        if t < now:
            t += timedelta(days=1)
        context.job_queue.run_once(lambda ctx: post_question(), t)

# Heartbeat System
heartbeat_toggle = True

def send_heartbeat(context):
    global heartbeat_toggle

    if heartbeat_toggle:
        bot.send_message(OWNER_ID, "✅ Bot Heartbeat - Code 1 - Bot is Running.")
    else:
        bot.send_message(OWNER_ID, "✅ Bot Heartbeat - Code 2 - Bot is Running.")

    heartbeat_toggle = not heartbeat_toggle

def main():
    bot.set_webhook(f'{WEBHOOK_URL}/{TOKEN}')

    # Add command handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CallbackQueryHandler(handle_answer))

    # Send initial heartbeat
    bot.send_message(OWNER_ID, "✅ Bot is starting up on Render.")

    # Set up repeating jobs (question schedule + heartbeat)
    job_queue = dispatcher.job_queue
    job_queue.run_repeating(send_heartbeat, interval=60, first=0)
    job_queue.run_once(schedule_questions, when=10)

    print("Bot started with webhook.")

if __name__ == '__main__':
    main()
