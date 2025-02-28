import os
import logging
from flask import Flask, request, jsonify
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackQueryHandler, Dispatcher
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime

# Environment variables (double-checked with your setup)
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')
OWNER_ID = int(os.getenv('OWNER_TELEGRAM_ID'))
WEBHOOK_URL = os.getenv('RENDER_WEBHOOK_URL')

# Flask app for webhook
app = Flask(__name__)

# Telegram bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dispatcher = Dispatcher(bot, None, use_context=True)

# Setup logging
logging.basicConfig(level=logging.INFO)

# Timezone for Gaza
GAZA_TZ = pytz.timezone('Asia/Gaza')

# Global state for heartbeat alternation
heartbeat_code = 1
first_correct_responder = None
current_question = None
current_correct_answer = None
answered_users = set()
question_counter = 0
daily_scores = {}

# Question pool (can be expanded)
questions = [
    {
        'question': "What is the plural of 'child'?",
        'options': ['Childs', 'Children', 'Childes'],
        'correct': 'Children',
        'explanation': "The correct plural of 'child' is 'children'."
    },
    {
        'question': "Which word is a noun?",
        'options': ['Run', 'Beautiful', 'Car'],
        'correct': 'Car',
        'explanation': "A car is a thing, making it a noun."
    },
    {
        'question': "What is the past tense of 'go'?",
        'options': ['Goed', 'Went', 'Gone'],
        'correct': 'Went',
        'explanation': "The past tense of 'go' is 'went'."
    }
]

@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return 'ok'

def send_heartbeat():
    global heartbeat_code
    message = f"✅ Bot Heartbeat - Code {heartbeat_code} - Bot is Running."
    bot.send_message(chat_id=OWNER_ID, text=message)
    heartbeat_code = 2 if heartbeat_code == 1 else 1

def send_question():
    global current_question, current_correct_answer, first_correct_responder, answered_users, question_counter

    first_correct_responder = None
    answered_users = set()

    if question_counter >= len(questions):
        question_counter = 0

    current_question = questions[question_counter]
    current_correct_answer = current_question['correct']

    keyboard = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in current_question['options']]
    reply_markup = InlineKeyboardMarkup(keyboard)

    bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"📚 Question Time!\n\n{current_question['question']}",
        reply_markup=reply_markup
    )

    question_counter += 1

def answer_callback(update, context):
    global first_correct_responder

    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.first_name

    if user_id in answered_users:
        query.answer("You have already answered this question!")
        return

    answered_users.add(user_id)

    if query.data == current_correct_answer:
        if first_correct_responder is None:
            first_correct_responder = username
            daily_scores[username] = daily_scores.get(username, 0) + 1

        bot.edit_message_text(
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            text=f"✅ Correct Answer: {current_correct_answer}\n\n"
                 f"🏅 First correct responder: {first_correct_responder}\n\n"
                 f"ℹ️ Explanation: {current_question['explanation']}"
        )
    else:
        query.answer("❌ Wrong answer. Better luck next time!")
        query.edit_message_reply_markup(reply_markup=None)

def show_leaderboard():
    if not daily_scores:
        bot.send_message(chat_id=CHANNEL_ID, text="📊 No players have scored today.")
        return

    sorted_scores = sorted(daily_scores.items(), key=lambda x: x[1], reverse=True)
    leaderboard_text = "📊 Daily Leaderboard:\n\n"

    for i, (name, score) in enumerate(sorted_scores[:3]):
        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉"
        leaderboard_text += f"{medal} {name}: {score} points\n"

    for name, score in sorted_scores[3:]:
        leaderboard_text += f"{name}: {score} points\n"

    bot.send_message(chat_id=CHANNEL_ID, text=leaderboard_text)

    # Reset scores for the next day
    daily_scores.clear()

def start(update, context):
    update.message.reply_text("Hello! I'm your Telegram bot running on Render.")

# Add command and callback handlers
dispatcher.add_handler(CommandHandler('start', start))
dispatcher.add_handler(CallbackQueryHandler(answer_callback))

# Scheduler for timed events
scheduler = BackgroundScheduler(timezone=GAZA_TZ)

scheduler.add_job(send_heartbeat, 'interval', minutes=1)

scheduler.add_job(send_question, 'cron', hour=8, minute=0)
scheduler.add_job(send_question, 'cron', hour=12, minute=0)
scheduler.add_job(send_question, 'cron', hour=18, minute=0)

scheduler.add_job(show_leaderboard, 'cron', hour=18, minute=30)

scheduler.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
