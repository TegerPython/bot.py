import os
import json
import httpx
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.daily import DailyTrigger
from telegram import Bot, ParseMode, Update
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters, CallbackContext
from datetime import datetime
import pytz

# Initialize Flask app
app = Flask(__name__)

# Load environment variables
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
QUESTIONS_JSON_URL = os.getenv('QUESTIONS_JSON_URL')
LEADERBOARD_JSON_URL = os.getenv('LEADERBOARD_JSON_URL')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
PORT = int(os.getenv('PORT', 8443))

# Initialize Telegram Bot
bot = Bot(token=TELEGRAM_BOT_TOKEN)

# Initialize Scheduler
scheduler = BackgroundScheduler(timezone=pytz.timezone('Asia/Gaza'))

# Initialize leaderboard
leaderboard = {}

# Function to fetch questions from GitHub
def fetch_questions():
    global questions
    async with httpx.AsyncClient() as client:
        response = await client.get(QUESTIONS_JSON_URL)
        if response.status_code == 200:
            questions = response.json()
        else:
            questions = []

# Function to fetch leaderboard from GitHub
def fetch_leaderboard():
    global leaderboard
    async with httpx.AsyncClient() as client:
        response = await client.get(LEADERBOARD_JSON_URL)
        if response.status_code == 200:
            leaderboard = response.json()
        else:
            leaderboard = {}

# Function to send a question to the channel
async def send_question():
    if questions:
        question = questions.pop(0)
        options = question.get('options', [])
        message = await bot.send_poll(
            chat_id=CHANNEL_ID,
            question=question.get('question', ''),
            options=options,
            is_anonymous=False
        )
        # Update questions in GitHub
        async with httpx.AsyncClient() as client:
            await client.put(
                QUESTIONS_JSON_URL,
                headers={'Authorization': f'token {GITHUB_TOKEN}'},
                json=questions
            )

# Function to handle answers
async def handle_answer(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    answer = update.message.text
    if user_id not in leaderboard:
        leaderboard[user_id] = 0
    if answer == 'correct_answer':  # Replace with actual answer checking logic
        leaderboard[user_id] += 1
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"User {update.message.from_user.username} answered correctly! Total points: {leaderboard[user_id]}"
        )
        # Update leaderboard in GitHub
        async with httpx.AsyncClient() as client:
            await client.put(
                LEADERBOARD_JSON_URL,
                headers={'Authorization': f'token {GITHUB_TOKEN}'},
                json=leaderboard
            )

# Set up daily question posting
scheduler.add_job(
    send_question,
    DailyTrigger(hour=8, minute=0, second=0, timezone='Asia/Gaza')
)
scheduler.add_job(
    send_question,
    DailyTrigger(hour=12, minute=0, second=0, timezone='Asia/Gaza')
)
scheduler.add_job(
    send_question,
    DailyTrigger(hour=18, minute=0, second=0, timezone='Asia/Gaza')
)

# Start the scheduler
scheduler.start()

# Set up webhook route
@app.route('/webhook', methods=['POST'])
async def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return jsonify({'status': 'ok'}), 200

# Set up command handlers
@app.before_first_request
def setup():
    # Set webhook
    bot.set_webhook(url=WEBHOOK_URL)
    # Fetch initial data
    fetch_questions()
    fetch_leaderboard()
    # Set up dispatcher
    global dispatcher
    dispatcher = Dispatcher(bot, update_queue=None)
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_answer))

# Run the Flask app with an ASGI server
if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=PORT)
