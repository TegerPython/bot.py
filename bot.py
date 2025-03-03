import os
import json
import logging
import requests
from datetime import datetime, time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)
import random
import base64

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot Token & Webhook URL
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # << Fixed here
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Fetch repo details from environment variables
GITHUB_REPO_OWNER = os.getenv("REPO_OWNER", "your-github-username")
GITHUB_REPO_NAME = os.getenv("REPO_NAME", "your-bot-data")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# File URLs
QUESTIONS_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/main/questions.json"
LEADERBOARD_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/main/leaderboard.json"

# GitHub API URL for updating leaderboard
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

async def send_question(context: ContextTypes.DEFAULT_TYPE):
    if not questions:
        logger.warning("No questions available.")
        return

    is_test = context.job.data.get("is_test", False) if context.job.data else False
    current_question = random.choice(questions) if is_test else questions[datetime.now().day % len(questions)]

    context.job.chat_data["current_question"] = current_question
    context.job.chat_data["answered_users"] = set()

    keyboard = [
        [InlineKeyboardButton(option, callback_data=f"answer_{i}")]
        for i, option in enumerate(current_question["options"])
    ]
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
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
        }
        response = requests.get(GITHUB_API_URL, headers=headers)
        if response.status_code == 200:
            file_data = response.json()
            sha = file_data.get("sha")
        else:
            sha = None

        content = json.dumps(leaderboard, indent=2)
        encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")

        payload = {
            "message": "Update leaderboard",
            "content": encoded_content,
            "branch": "main",
        }

        if sha:
            payload["sha"] = sha

        response = requests.put(GITHUB_API_URL, headers=headers, json=payload)

        if response.status_code in [200, 201]:
            logger.info("Leaderboard updated on GitHub")
        else:
            logger.error(f"Failed to update leaderboard on GitHub: {response.status_code} - {response.text}")

    except Exception as e:
        logger.error(f"Exception while saving leaderboard: {e}")

async def test_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    job = context.job_queue.run_once(
        send_question,
        0,
        chat_id=update.effective_chat.id,
        name="test_question",
        data={"is_test": True}
    )
    await update.message.reply_text("Test question sent!")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome! Use /test to send a test question.")

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not leaderboard:
        await update.message.reply_text("🏅 No scores yet!")
        return

    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1]["points"], reverse=True)
    message = "🏆 Leaderboard:\n\n"
    for user_id, data in sorted_leaderboard[:10]:
        message += f"{data['username']}: {data['points']} points\n"
    await update.message.reply_text(message)

def main():
    load_data()

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("test", test_question))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CallbackQueryHandler(button))

    # Schedule daily questions (optional if using daily intervals)
    job_queue = application.job_queue
    job_queue.run_daily(send_question, time(hour=8), data={})
    job_queue.run_daily(send_question, time(hour=12), data={})
    job_queue.run_daily(send_question, time(hour=18), data={})

    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 8443)),
        webhook_url=WEBHOOK_URL
    )

if __name__ == "__main__":
    main()
