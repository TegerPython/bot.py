import os
import logging
from flask import Flask, request
from telegram import Update, Bot, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.error import TelegramError
from apscheduler.schedulers.background import BackgroundScheduler
import random

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Retrieve environment variables
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')

# Initialize bot and application
bot = Bot(token=TOKEN)
application = Application.builder().token(TOKEN).build()

# Sample questions
questions = [
    "What is the capital of France?",
    "Who wrote 'To Kill a Mockingbird'?",
    "What is the chemical symbol for gold?",
    "Who painted the Mona Lisa?",
    "What is the largest planet in our solar system?"
]

# Dictionary to store user scores
user_scores = {}

# Function to post a question to the channel
async def post_question():
    question = random.choice(questions)
    message = await bot.send_message(chat_id=CHANNEL_ID, text=question)
    application.job_queue.run_once(
        lambda _: reveal_answer(question, message.message_id),
        60  # Reveal answer after 60 seconds
    )

# Function to reveal the answer
async def reveal_answer(question, message_id):
    answer = "The answer to the question is..."
    await bot.send_message(
        chat_id=CHANNEL_ID,
        text=answer,
        reply_to_message_id=message_id
    )

# Command handler to start the quiz
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Welcome to the quiz bot!')

# Command handler to display the leaderboard
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if user_scores:
        leaderboard_text = "🏆 Leaderboard 🏆\n\n"
        sorted_scores = sorted(user_scores.items(), key=lambda x: x[1], reverse=True)
        for user, score in sorted_scores:
            leaderboard_text += f"{user}: {score} points\n"
        await update.message.reply_text(leaderboard_text)
    else:
        await update.message.reply_text("No scores yet. Be the first to answer a question!")

# Message handler to process answers
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.username
    text = update.message.text
    # Logic to check if the answer is correct
    if text.lower() == "correct answer":  # Replace with actual answer checking
        user_scores[user] = user_scores.get(user, 0) + 1
        await update.message.reply_text(f"Correct, {user}! Your score is now {user_scores[user]}.")

# Set up the scheduler to post questions at regular intervals
scheduler = BackgroundScheduler()
scheduler.add_job(post_question, 'interval', minutes=60)  # Adjust interval as needed
scheduler.start()

# Set up command and message handlers
application.add_handler(CommandHandler('start', start))
application.add_handler(CommandHandler('leaderboard', leaderboard))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# Flask route to handle incoming webhook updates
@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(), bot)
    application.update_queue.put(update)
    return 'OK'

# Function to set the webhook
def set_webhook():
    webhook_url = f"{WEBHOOK_URL}/webhook"
    bot.set_webhook(webhook_url)

if __name__ == '__main__':
    set_webhook()
    app.run(host='0.0.0.0', port=8443)
