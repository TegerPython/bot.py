import logging
import os
import json
import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
LEADERBOARD_JSON_URL = os.getenv('LEADERBOARD_JSON_URL')
QUESTIONS_JSON_URL = os.getenv('QUESTIONS_JSON_URL')
CHANNEL_ID = os.getenv('CHANNEL_ID')

# Global variables
questions_data = []
leaderboard_data = {}

# Load questions from JSON URL
def load_questions():
    global questions_data
    response = httpx.get(QUESTIONS_JSON_URL)
    if response.status_code == 200:
        questions_data = response.json()

# Load leaderboard from JSON URL
def load_leaderboard():
    global leaderboard_data
    response = httpx.get(LEADERBOARD_JSON_URL)
    if response.status_code == 200:
        leaderboard_data = response.json()

# Start command - Welcome message
async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("Hello! I am your competitive English bot. Ready to start?")

# Help command - Instructions for the bot
async def help_command(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("This bot will send you daily English questions! Answer correctly and compete on the leaderboard.")

# Load a new question
async def post_question(update: Update, context: CallbackContext) -> None:
    if questions_data:
        question = questions_data.pop(0)
        await update.message.reply_text(f"Question: {question['question']}")

# Set up a scheduler to post questions
def setup_scheduler(application: Application):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: post_question(update=None, context=None), 'interval', minutes=60)
    scheduler.start()

# Main function to start the bot
def main():
    load_questions()
    load_leaderboard()

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Command Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))

    # Message Handlers
    application.add_handler(MessageHandler(filters.TEXT, post_question))

    # Set up scheduler for automatic question posting
    setup_scheduler(application)

    application.run_polling()

if __name__ == '__main__':
    main()
