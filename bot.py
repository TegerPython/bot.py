import os
import json
import random
import threading
import time
import pytz
from datetime import datetime
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import CommandHandler, CallbackQueryHandler, Dispatcher

app = Flask(__name__)

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
OWNER_ID = int(os.getenv('OWNER_TELEGRAM_ID'))
CHANNEL_ID = os.getenv('CHANNEL_ID')  # Example: -1001234567890
WEBHOOK_URL = os.getenv('RENDER_WEBHOOK_URL')

bot = Bot(token=TOKEN)

# Dispatcher (for webhook handling)
dispatcher = Dispatcher(bot, None, workers=4)

# Track current question
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
first_correct_user = None

# Gaza timezone
gaza_tz = pytz.timezone('Asia/Gaza')

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

    current_question = random.choice(questions)
    answered_users = {}
    first_correct_user = None

    keyboard = [
        [InlineKeyboardButton(opt, callback_data=str(idx))] for idx, opt in enumerate(current_question['options'])
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

    if len(answered_users) == 1:
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

# 🔔 Heartbeat System
heartbeat_toggle = True

def send_heartbeat():
    global heartbeat_toggle
    try:
        if heartbeat_toggle:
            bot.send_message(OWNER_ID, "✅ Bot Heartbeat - Code 1 - Bot is Running.")
        else:
            bot.send_message(OWNER_ID, "✅ Bot Heartbeat - Code 2 - Bot is Running.")
        heartbeat_toggle = not heartbeat_toggle
    except Exception as e:
        print(f"Failed to send heartbeat: {e}")

# ✅ New: Time-based Scheduler (independent thread)
def background_scheduler():
    question_times = ["08:00", "12:00", "17:29"]  # Gaza times for questions
    last_posted = None

    while True:
        now = datetime.now(gaza_tz)
        current_time_str = now.strftime("%H:%M")

        # Check and post questions
        if current_time_str in question_times and current_time_str != last_posted:
            post_question()
            last_posted = current_time_str

        # Heartbeat every 60 seconds
        send_heartbeat()

        time.sleep(60)

def main():
    bot.set_webhook(f'{WEBHOOK_URL}/{TOKEN}')

    # Command handlers for webhook
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CallbackQueryHandler(handle_answer))

    bot.send_message(OWNER_ID, "✅ Bot is starting up on Render with new time-based scheduler.")

    # Start the background scheduler thread
    scheduler_thread = threading.Thread(target=background_scheduler, daemon=True)
    scheduler_thread.start()

    print("Bot started with webhook + background scheduler.")

if __name__ == '__main__':
    main()
