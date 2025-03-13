import os
import json
import logging
import requests
import asyncio
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackContext
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Load environment variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Must be HTTPS, e.g. https://bot-py-dcpa.onrender.com/webhook
PORT = int(os.getenv("PORT", "8443"))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize the Telegram bot application (webhook mode)
application = Application.builder().token(TOKEN).build()

# Global variable for the dedicated event loop for telegram Application
telegram_loop = None

# Initialize APScheduler for posting questions automatically
scheduler = BackgroundScheduler()

# ----------------------- Question Management -----------------------

def get_latest_question():
    """
    Fetches questions from GitHub, removes the first (oldest) question, updates the GitHub file,
    and returns the removed question.
    """
    try:
        response = requests.get(QUESTIONS_JSON_URL)
        if response.status_code == 200:
            questions = response.json()
            if questions:
                latest_question = questions.pop(0)  # Use the first question
                update_questions_json(questions)
                return latest_question
            else:
                return None
        else:
            logger.error("Failed to fetch questions.")
            return None
    except Exception as e:
        logger.error(f"Error fetching questions: {e}")
        return None

def update_questions_json(updated_questions):
    """
    Updates the questions.json file on GitHub by removing the used question.
    """
    try:
        headers = {"Authorization": f"token {os.getenv('GITHUB_TOKEN')}"}
        update_data = {
            "message": "Remove used question",
            "content": json.dumps(updated_questions, indent=2).encode("utf-8").decode("latin1"),
            "sha": get_file_sha("questions.json"),
        }
        url = f"https://api.github.com/repos/{os.getenv('REPO_OWNER')}/{os.getenv('REPO_NAME')}/contents/questions.json"
        response = requests.put(url, headers=headers, json=update_data)
        if response.status_code not in [200, 201]:
            logger.error(f"Failed to update questions JSON: {response.text}")
    except Exception as e:
        logger.error(f"Error updating questions JSON: {e}")

def get_file_sha(filename):
    """
    Retrieves the SHA of the file from GitHub, needed to update the file.
    """
    headers = {"Authorization": f"token {os.getenv('GITHUB_TOKEN')}"}
    url = f"https://api.github.com/repos/{os.getenv('REPO_OWNER')}/{os.getenv('REPO_NAME')}/contents/{filename}"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()["sha"]
    return None

def post_question():
    """
    Synchronously posts a new question to the Telegram channel.
    """
    question = get_latest_question()
    if question:
        application.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"🔥 *New Question!* 🔥\n\n{question['question']}",
            parse_mode="Markdown",
        )
    else:
        application.bot.send_message(
            chat_id=CHANNEL_ID,
            text="No more questions available!",
            parse_mode="Markdown",
        )

# ----------------------- Command Handlers -----------------------

async def leaderboard_command(update: Update, context: CallbackContext):
    """
    Fetches and displays the leaderboard from GitHub.
    """
    try:
        response = requests.get(LEADERBOARD_JSON_URL)
        if response.status_code == 200:
            leaderboard = response.json()
            if not leaderboard:
                await update.message.reply_text("🏆 Leaderboard is empty!")
                return
            sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
            leaderboard_text = "🏆 *Leaderboard* 🏆\n\n"
            for rank, (user, score) in enumerate(sorted_leaderboard[:10], start=1):
                leaderboard_text += f"{rank}. {user}: {score} points\n"
            await update.message.reply_text(leaderboard_text, parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️ Failed to load leaderboard data.")
    except Exception as e:
        logger.error(f"Error fetching leaderboard: {e}")
        await update.message.reply_text("⚠️ Error fetching leaderboard.")

async def test_command(update: Update, context: CallbackContext):
    """
    Test command to immediately post a test question.
    """
    question = get_latest_question()
    if question:
        await update.message.reply_text(f"Test Question: {question['question']}")
    else:
        await update.message.reply_text("No question available for testing!")

# ----------------------- Scheduler Setup -----------------------

def setup_scheduler():
    """
    Sets up the scheduler to post questions at 8:00 AM, 12:00 PM, and 6:00 PM.
    """
    scheduler.add_job(post_question, CronTrigger(hour=8, minute=0))
    scheduler.add_job(post_question, CronTrigger(hour=12, minute=0))
    scheduler.add_job(post_question, CronTrigger(hour=18, minute=0))
    scheduler.start()

# ----------------------- Flask Webhook Setup -----------------------

flask_app = Flask(__name__)

@flask_app.route('/webhook', methods=['POST'])
def webhook_handler():
    """
    Handles incoming webhook POST requests from Telegram.
    Processes the update on the dedicated telegram_loop.
    """
    if request.method == 'POST':
        update = Update.de_json(request.get_json(force=True), application.bot)
        # Schedule the coroutine on the dedicated event loop
        asyncio.run_coroutine_threadsafe(application.process_update(update), telegram_loop)
        return 'OK', 200

# ----------------------- Main Entry Point -----------------------

def main():
    global telegram_loop
    # Create a dedicated event loop for the telegram Application and initialize it
    telegram_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(telegram_loop)
    telegram_loop.run_until_complete(application.initialize())
    
    setup_scheduler()

    # Register command handlers
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CommandHandler("test", test_command))

    # Set the webhook and wait for it to complete
    telegram_loop.run_until_complete(application.bot.set_webhook(url=WEBHOOK_URL))
    logger.info("Webhook set. Starting Flask server...")

    # Start Flask server to listen for webhook updates
    flask_app.run(host="0.0.0.0", port=PORT)

if __name__ == '__main__':
    main()
