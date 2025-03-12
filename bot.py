from telegram import Update
from telegram.ext import Application, CommandHandler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.job import Job
import json
import requests
import asyncio

# Assuming the 'questions.json' file holds the list of questions.
QUESTIONS_JSON_URL = "https://github.com/TegerPython/bot_data/blob/main/questions.json"

# Store the current question index to prevent duplication
current_question_index = 0

# Function to load the latest question from the JSON
def get_latest_question():
    global current_question_index
    # Replace this with your actual method to fetch the latest question
    response = requests.get(QUESTIONS_JSON_URL)
    questions = response.json()
    
    # Get the next question based on the index, if available
    if current_question_index < len(questions):
        question = questions[current_question_index]
        current_question_index += 1
        return question
    else:
        return None  # No more questions available

# Post a question
async def post_question(update: Update, context):
    question = get_latest_question()
    if question:
        await update.message.reply_text(f"Question: {question['question']}")
    else:
        await update.message.reply_text("No more questions available!")

# Command handler for testing
async def test_command(update: Update, context):
    question = get_latest_question()
    if question:
        await update.message.reply_text(f"Test Question: {question['question']}")
    else:
        await update.message.reply_text("No question available for testing!")

# Function to set up the scheduler for regular posting
def setup_scheduler(application: Application):
    scheduler = BackgroundScheduler()
    scheduler.add_job(post_question, 'interval', minutes=60, args=[application])  # Adjust interval as needed
    scheduler.start()

# Main entry point
def main():
    application = Application.builder().token('YOUR_BOT_TOKEN').build()

    # Set up handlers for commands
    application.add_handler(CommandHandler("test", test_command))  # Command for testing questions

    # Start the scheduler
    setup_scheduler(application)

    # Run the bot
    application.run_polling()

if __name__ == '__main__':
    main()
