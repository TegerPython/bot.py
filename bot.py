import os
import json
import logging
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot, Update, ParseMode
from telegram.ext import CommandHandler, MessageHandler, Filters, Dispatcher
import httpx

# Initialize Flask app
app = Flask(__name__)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Retrieve environment variables
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')
QUESTIONS_JSON_URL = os.getenv('QUESTIONS_JSON_URL')
LEADERBOARD_JSON_URL = os.getenv('LEADERBOARD_JSON_URL')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
PORT = int(os.getenv('PORT', 8443))

# Initialize Telegram Bot
bot = Bot(token=TELEGRAM_BOT_TOKEN)

# Global variables to store questions and leaderboard
questions = []
leaderboard = {}

# Function to fetch questions and leaderboard from GitHub
def fetch_data():
    global questions, leaderboard
    async with httpx.AsyncClient() as client:
        questions_response = await client.get(QUESTIONS_JSON_URL)
        leaderboard_response = await client.get(LEADERBOARD_JSON_URL)
        if questions_response.status_code == 200:
            questions = questions_response.json()
        if leaderboard_response.status_code == 200:
            leaderboard = leaderboard_response.json().get('players', {})

# Function to send a question as a poll to the channel
async def send_question():
    if questions:
        question = questions.pop(0)
        options = question.get('options', [])
        correct_option = question.get('correct_option', '')
        explanation = question.get('explanation', '')
        message = await bot.send_poll(
            chat_id=CHANNEL_ID,
            question=question.get('question', ''),
            options=options,
            is_anonymous=False,
            type='quiz',
            correct_option_id=options.index(correct_option),
            explanation=explanation
        )
        # Update questions on GitHub
        async with httpx.AsyncClient() as client:
            await client.put(QUESTIONS_JSON_URL, json=questions)

# Function to handle incoming answers
async def handle_answer(update: Update):
    user_id = update.message.from_user.id
    answer = update.message.text
    if answer:
        # Check if the answer is correct
        for question in questions:
            if answer == question.get('correct_option'):
                if user_id not in leaderboard:
                    leaderboard[user_id] = {'score': 0}
                leaderboard[user_id]['score'] += 1
                # Update leaderboard on GitHub
                async with httpx.AsyncClient() as client:
                    await client.put(LEADERBOARD_JSON_URL, json={'players': leaderboard})
                # Announce the correct answer
                await bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=f"Correct answer by {update.message.from_user.full_name}!"
                )
                break

# Set up the scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(
    send_question,
    CronTrigger(hour='8,12,18', minute='0'),
    id='send_question_job',
    replace_existing=True
)
scheduler.start()

# Set up webhook route
@app.route('/webhook', methods=['POST'])
async def webhook():
    json_str = await request.get_data(as_text=True)
    update = Update.de_json(json.loads(json_str), bot)
    dispatcher.process_update(update)
    return jsonify({'status': 'ok'}), 200

# Set up command handlers
def start(update: Update, context):
    update.message.reply_text("Welcome to the English Quiz Bot!")

# Initialize dispatcher
dispatcher = Dispatcher(bot, None, workers=0)
dispatcher.add_handler(CommandHandler('start', start))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_answer))

# Set webhook on Telegram
async def set_webhook():
    await bot.set_webhook(WEBHOOK_URL)

if __name__ == '__main__':
    import asyncio
    loop = asyncio.get_event_loop()
    loop.run_until_complete(fetch_data())
    loop.run_until_complete(set_webhook())
    app.run(host='0.0.0.0', port=PORT)
