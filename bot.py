import os
import json
import httpx
import schedule
import logging
from datetime import datetime
from telegram import Update, Poll, ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, PollAnswerHandler, CallbackContext
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
GITHUB_REPO = os.getenv('GITHUB_REPO')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
PORT = int(os.getenv('PORT', 8080))

# GitHub API URLs
QUESTIONS_URL = f'https://api.github.com/repos/{GITHUB_REPO}/contents/questions.json'
LEADERBOARD_URL = f'https://api.github.com/repos/{GITHUB_REPO}/contents/leaderboard.json'

# Initialize the scheduler
scheduler = BackgroundScheduler()
scheduler.start()

# Initialize data storage
questions = []
leaderboard = {}

# Function to fetch data from GitHub
async def fetch_github_data():
    async with httpx.AsyncClient() as client:
        questions_response = await client.get(QUESTIONS_URL, headers={'Authorization': f'token {GITHUB_TOKEN}'})
        leaderboard_response = await client.get(LEADERBOARD_URL, headers={'Authorization': f'token {GITHUB_TOKEN}'})
        if questions_response.status_code == 200:
            questions_data = questions_response.json()
            questions_content = base64.b64decode(questions_data[0]['content']).decode('utf-8')
            global questions
            questions = json.loads(questions_content)
        if leaderboard_response.status_code == 200:
            leaderboard_data = leaderboard_response.json()
            leaderboard_content = base64.b64decode(leaderboard_data[0]['content']).decode('utf-8')
            global leaderboard
            leaderboard = json.loads(leaderboard_content)

# Function to update data on GitHub
async def update_github_data():
    async with httpx.AsyncClient() as client:
        # Update questions.json
        questions_content = json.dumps(questions, indent=4)
        questions_encoded = base64.b64encode(questions_content.encode('utf-8')).decode('utf-8')
        questions_payload = {
            'message': 'Update questions.json',
            'content': questions_encoded
        }
        await client.put(QUESTIONS_URL, json=questions_payload, headers={'Authorization': f'token {GITHUB_TOKEN}'})
        # Update leaderboard.json
        leaderboard_content = json.dumps(leaderboard, indent=4)
        leaderboard_encoded = base64.b64encode(leaderboard_content.encode('utf-8')).decode('utf-8')
        leaderboard_payload = {
            'message': 'Update leaderboard.json',
            'content': leaderboard_encoded
        }
        await client.put(LEADERBOARD_URL, json=leaderboard_payload, headers={'Authorization': f'token {GITHUB_TOKEN}'})

# Function to send a question
async def send_question(context: CallbackContext):
    if questions:
        question = questions.pop(0)
        options = question['options']
        correct_option_id = options.index(question['answer'])
        poll = await context.bot.send_poll(
            CHANNEL_ID,
            question['question'],
            options,
            is_anonymous=False,
            correct_option_id=correct_option_id,
            explanation="Please select the correct answer.",
            explanation_parse_mode=ParseMode.MARKDOWN
        )
        logger.info(f"Sent poll: {poll.poll_id}")
        await update_github_data()

# Function to handle poll answers
async def poll_answer_handler(update: Update, context: CallbackContext):
    user_id = update.poll_answer.user.id
    option_ids = update.poll_answer.option_ids
    if user_id not in leaderboard:
        leaderboard[user_id] = 0
    if option_ids:
        correct_option_id = 0  # Assuming the first option is correct
        if option_ids[0] == correct_option_id:
            leaderboard[user_id] += 1
            await context.bot.send_message(
                CHANNEL_ID,
                f"User {update.poll_answer.user.full_name} answered correctly! Current score: {leaderboard[user_id]}"
            )
            await update_github_data()

# Function to handle /test command
async def test(update: Update, context: CallbackContext):
    await update.message.reply_text("Bot is online!")

# Main function to set up the bot
async def main():
    # Create the Application and pass it your bot's token
    application = Application.builder().token(BOT_TOKEN).build()

    # Fetch initial data from GitHub
    await fetch_github_data()

    # Set up command handlers
    application.add_handler(CommandHandler('test', test))

    # Set up poll answer handler
    application.add_handler(PollAnswerHandler(poll_answer_handler))

    # Set up daily job to send questions
    scheduler.add_job(
        send_question,
        'cron',
        hour=8,
        minute=0,
        second=0,
        timezone='Asia/Gaza',
        context=application
    )
    scheduler.add_job(
        send_question,
        'cron',
        hour=12,
        minute=0,
        second=0,
        timezone='Asia/Gaza',
        context=application
    )
    scheduler.add_job(
        send_question,
        'cron',
        hour=18,
        minute=0,
        second=0,
        timezone='Asia/Gaza',
        context=application
    )

    # Run the bot until you send a signal to stop
    await application.run_webhook(
        listen='0.0.0.0',
        port=PORT,
        url_path=WEBHOOK_URL.strip('/'),
        webhook_url=WEBHOOK_URL
    )

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
