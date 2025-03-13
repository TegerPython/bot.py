import os
import json
import requests
from telegram import Bot
from telegram.ext import Application, CommandHandler
from apscheduler.schedulers.background import BackgroundScheduler

# Load environment variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
CHANNEL_ID = os.getenv("CHANNEL_ID")  # The channel where the bot will post

# Create a bot instance
bot = Bot(token=BOT_TOKEN)

# Store the current question index
current_question_index = 0

def get_latest_question():
    global current_question_index
    response = requests.get(QUESTIONS_JSON_URL)
    
    if response.status_code == 200:
        questions = response.json()
        
        if current_question_index < len(questions):
            question = questions[current_question_index]
            current_question_index += 1
            return question
        else:
            return None  # No more questions available
    else:
        return None  # Failed to fetch questions

# Function to post a question (synchronous wrapper)
def post_question():
    question = get_latest_question()
    
    if question:
        bot.send_message(chat_id=CHANNEL_ID, text=f"Question: {question['question']}")
    else:
        bot.send_message(chat_id=CHANNEL_ID, text="No more questions available!")

# Command handler for testing (async function for commands)
async def test_command(update, context):
    question = get_latest_question()
    
    if question:
        await update.message.reply_text(f"Test Question: {question['question']}")
    else:
        await update.message.reply_text("No question available for testing!")

# Scheduler setup
def setup_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(post_question, 'interval', minutes=60)  # Adjust as needed
    scheduler.start()
    return scheduler

# Main entry point
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Command handler
    application.add_handler(CommandHandler("test", test_command))

    # Start the scheduler
    scheduler = setup_scheduler()

    # Run the bot
    application.run_polling()

if __name__ == '__main__':
    main()
