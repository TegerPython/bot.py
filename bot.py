import os
import json
import logging
import httpx
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update, ParseMode, Poll
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackContext

# Initialize Flask app
app = Flask(__name__)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')
GITHUB_REPO = os.getenv('GITHUB_REPO')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

# Initialize the scheduler
scheduler = BackgroundScheduler()
scheduler.start()

# Function to fetch data from GitHub
def fetch_github_file(filename):
    url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{filename}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
    return response.json()

# Function to update data on GitHub
def update_github_file(filename, data):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
    headers = {
        'Authorization': f'token {os.getenv("GITHUB_TOKEN")}',
        'Content-Type': 'application/json'
    }
    payload = {
        'message': f'Update {filename}',
        'content': json.dumps(data)
    }
    async with httpx.AsyncClient() as client:
        response = await client.put(url, headers=headers, json=payload)
    return response.json()

# Function to send a question
async def send_question():
    questions = await fetch_github_file('questions.json')
    if questions:
        question = questions.pop(0)
        await update_github_file('questions.json', questions)
        application = ApplicationBuilder().token(BOT_TOKEN).build()
        await application.bot.send_poll(
            chat_id=CHANNEL_ID,
            question=question['question'],
            options=question['options'],
            is_anonymous=False,
            type=Poll.REGULAR,
            allows_multiple_answers=False
        )

# Function to handle answers
async def handle_answer(update: Update, context: CallbackContext):
    user_answer = update.poll_answer.option_ids[0]
    question = update.poll.question
    correct_answer = get_correct_answer(question)
    if user_answer == correct_answer:
        user_id = update.effective_user.id
        leaderboard = await fetch_github_file('leaderboard.json')
        leaderboard[user_id] = leaderboard.get(user_id, 0) + 1
        await update_github_file('leaderboard.json', leaderboard)
        await update.message.reply_text(f"Correct! {update.effective_user.first_name} earns a point!")

# Function to get the correct answer index
def get_correct_answer(question):
    # Implement logic to retrieve the correct answer index
    pass

# Set up command handlers
async def test(update: Update, context: CallbackContext):
    await update.message.reply_text("Bot is online!")

# Set up the application
application = ApplicationBuilder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler('test', test))
application.add_handler(MessageHandler(filters.POLL_ANSWER, handle_answer))

# Set up the webhook
async def set_webhook():
    url = f"{WEBHOOK_URL}/{BOT_TOKEN}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
    return response.json()

# Function to start the bot
async def start_bot():
    await set_webhook()
    scheduler.add_job(send_question, 'interval', hours=4, start_date='2025-03-13 08:00:00', timezone='Asia/Gaza')

if __name__ == '__main__':
    start_bot()
    app.run(host='0.0.0.0', port=8443)
