import os
import json
import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackContext
from apscheduler.schedulers.background import BackgroundScheduler

# Load environment variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Telegram bot application
application = Application.builder().token(TOKEN).build()

# Initialize scheduler
scheduler = BackgroundScheduler()

# Function to fetch the latest question
def get_latest_question():
    try:
        response = requests.get(QUESTIONS_JSON_URL)
        if response.status_code == 200:
            questions = response.json()
            if questions:
                latest_question = questions.pop(0)  # Take the first question
                # Update the questions JSON (remove used question)
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

# Function to update the questions JSON after removing used questions
def update_questions_json(updated_questions):
    try:
        headers = {"Authorization": f"token {os.getenv('GITHUB_TOKEN')}"}
        update_data = {
            "message": "Remove used question",
            "content": json.dumps(updated_questions).encode("utf-8").decode("latin1"),
            "sha": get_file_sha("questions.json"),
        }
        requests.put(
            f"https://api.github.com/repos/{os.getenv('REPO_OWNER')}/{os.getenv('REPO_NAME')}/contents/questions.json",
            headers=headers,
            json=update_data,
        )
    except Exception as e:
        logger.error(f"Error updating questions JSON: {e}")

# Function to get the latest SHA for the questions JSON file (needed for GitHub updates)
def get_file_sha(filename):
    headers = {"Authorization": f"token {os.getenv('GITHUB_TOKEN')}"}
    response = requests.get(
        f"https://api.github.com/repos/{os.getenv('REPO_OWNER')}/{os.getenv('REPO_NAME')}/contents/{filename}",
        headers=headers,
    )
    if response.status_code == 200:
        return response.json()["sha"]
    return None

# Function to post a new question to the channel
def post_question():
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

# Leaderboard command function
async def leaderboard_command(update: Update, context: CallbackContext):
    try:
        response = requests.get(LEADERBOARD_JSON_URL)

        if response.status_code == 200:
            leaderboard = response.json()

            if not leaderboard:
                await update.message.reply_text("🏆 Leaderboard is empty!")
                return

            sorted_leaderboard = sorted(
                leaderboard.items(), key=lambda x: x[1], reverse=True
            )
            leaderboard_text = "🏆 *Leaderboard* 🏆\n\n"

            for rank, (user, score) in enumerate(sorted_leaderboard[:10], start=1):
                leaderboard_text += f"{rank}. {user}: {score} points\n"

            await update.message.reply_text(leaderboard_text, parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️ Failed to load leaderboard data.")

    except Exception as e:
        logger.error(f"Error fetching leaderboard: {e}")
        await update.message.reply_text("⚠️ Error fetching leaderboard.")

# Setup scheduler to post questions at intervals
def setup_scheduler():
    scheduler.add_job(post_question, "interval", minutes=60)
    scheduler.start()

# Main entry point
def main():
    setup_scheduler()

    # Register command handlers
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))

    logger.info("Bot is running...")
    application.run_polling()

# Run bot
if __name__ == "__main__":
    main()
