import os
import json
import logging
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)
import random

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot Token & Webhook URL
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RENDER_URL = os.getenv("RENDER_URL")  # Set this in Render environment variables
PORT = int(os.getenv("PORT", 8443))

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is missing in environment variables!")
if not RENDER_URL:
    raise ValueError("RENDER_URL is missing in environment variables!")

WEBHOOK_URL = f"{RENDER_URL}/{TOKEN}"

# Fetch repo details from environment variables
GITHUB_REPO_OWNER = os.getenv("REPO_OWNER", "your-github-username")
GITHUB_REPO_NAME = os.getenv("REPO_NAME", "your-bot-data")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# File URLs
QUESTIONS_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/main/questions.json"
LEADERBOARD_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/main/leaderboard.json"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/contents/leaderboard.json"

# In-memory data
questions = []
leaderboard = {}

def fetch_file_from_github(file_url):
    try:
        response = requests.get(file_url)
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Failed to fetch {file_url}: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"Exception while fetching {file_url}: {e}")
        return None

def load_data():
    global questions, leaderboard
    questions = fetch_file_from_github(QUESTIONS_URL) or []
    leaderboard = fetch_file_from_github(LEADERBOARD_URL) or {}
    logger.info(f"Loaded {len(questions)} questions and {len(leaderboard)} leaderboard entries")

async def send_question(context: ContextTypes.DEFAULT_TYPE, is_test=False):
    if not questions:
        logger.warning("No questions available.")
        return

    current_question = random.choice(questions) if is_test else questions[datetime.now().day % len(questions)]
    context.job.chat_data["current_question"] = current_question
    context.job.chat_data["answered_users"] = set()

    keyboard = [[InlineKeyboardButton(option, callback_data=f"answer_{i}")] for i, option in enumerate(current_question["options"])]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=context.job.chat_id,
        text=f"📚 Question:\n\n{current_question['question']}",
        reply_markup=reply_markup,
    )

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name
    await query.answer()

    if user_id in context.chat_data.get("answered_users", set()):
        await query.message.reply_text("🚫 You have already answered this question.")
        return

    context.chat_data.setdefault("answered_users", set()).add(user_id)
    choice = int(query.data.split("_")[1])
    current_question = context.chat_data.get("current_question")

    if choice == current_question["correct_option"]:
        await query.edit_message_text(
            f"✅ Correct! {username} answered it right.\n\n{current_question['question']}\n\n"
            f"The correct answer: {current_question['options'][choice]}"
        )
        update_leaderboard(user_id, username, 1)
    else:
        await query.edit_message_text(
            f"❌ Wrong answer, {username}.\n\n{current_question['question']}\n\n"
            f"The correct answer: {current_question['options'][current_question['correct_option']]}"
        )
        update_leaderboard(user_id, username, 0)

def update_leaderboard(user_id, username, points):
    if str(user_id) not in leaderboard:
        leaderboard[str(user_id)] = {"username": username, "points": 0}
    leaderboard[str(user_id)]["points"] += points
    save_leaderboard_to_github()

def save_leaderboard_to_github():
    try:
        headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        response = requests.get(GITHUB_API_URL, headers=headers)
        sha = response.json().get("sha") if response.status_code == 200 else None

        content = json.dumps(leaderboard, indent=2)
        payload = {"message": "Update leaderboard", "content": content.encode("utf-8").decode("latin1").encode("base64").decode(), "branch": "main"}
        if sha:
            payload["sha"] = sha
        response = requests.put(GITHUB_API_URL, headers=headers, json=payload)

        if response.status_code in [200, 201]:
            logger.info("Leaderboard updated on GitHub")
        else:
            logger.error(f"Failed to update leaderboard on GitHub: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"Exception while saving leaderboard: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome! Use /test to send a test question.")

def main():
    load_data()
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button))
    application.run_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=WEBHOOK_URL)

if __name__ == "__main__":
    main()
