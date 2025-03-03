import json
import os
import random
import requests
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# In-memory storage
questions = []
leaderboard = {}

# GitHub file paths (repo-specific, update if needed)
REPO_OWNER = "your-username"
REPO_NAME = "bot-data-repo"
LEADERBOARD_FILE_PATH = "leaderboard.json"

# Fetch files from GitHub
def fetch_file(url):
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        logger.error(f"Failed to fetch {url}: {response.status_code} - {response.text}")
        return []

def load_data():
    global questions, leaderboard
    questions = fetch_file(QUESTIONS_JSON_URL) or []
    leaderboard = fetch_file(LEADERBOARD_JSON_URL) or {}

def save_leaderboard():
    if not GITHUB_TOKEN:
        logger.warning("GITHUB_TOKEN not set - leaderboard changes will not persist.")
        return

    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{LEADERBOARD_FILE_PATH}"
    
    # Fetch current file SHA to update (required by GitHub API)
    response = requests.get(url)
    sha = response.json().get("sha")

    # New content
    new_content = json.dumps(leaderboard, indent=2)
    encoded_content = new_content.encode("utf-8").decode("latin1").encode("base64").decode()

    payload = {
        "message": "Update leaderboard.json via bot",
        "content": encoded_content,
        "sha": sha
    }

    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    response = requests.put(url, headers=headers, json=payload)

    if response.status_code == 200:
        logger.info("Leaderboard updated on GitHub successfully.")
    else:
        logger.error(f"Failed to update leaderboard: {response.status_code} - {response.text}")

# Command: /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome to the Quiz Bot! Use /test to try a test question.")

# Command: /test
async def test_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_question(context, is_test=True)

# Function to send a question
async def send_question(context: ContextTypes.DEFAULT_TYPE, is_test=False):
    if not questions:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="No questions available.")
        return

    question = random.choice(questions)
    context.chat_data['current_question'] = question

    keyboard = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in question['options']]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=question['question'],
        reply_markup=reply_markup
    )

# Handle answer selection
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    question = context.chat_data.get('current_question')
    if not question:
        await query.edit_message_text("No active question.")
        return

    user_answer = query.data
    correct_answer = question['correct']

    if user_answer == correct_answer:
        user = update.effective_user
        username = user.username or user.first_name
        leaderboard[username] = leaderboard.get(username, 0) + 1
        await query.edit_message_text(f"Correct! ✅\n\n{username} has {leaderboard[username]} points.")

        save_leaderboard()  # Save leaderboard to GitHub (if token provided)
    else:
        await query.edit_message_text(f"Wrong ❌ The correct answer was: {correct_answer}")

# Main function
def main():
    load_data()

    application = Application.builder().token(os.getenv("BOT_TOKEN")).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("test", test_question))
    application.add_handler(CallbackQueryHandler(button))

    application.run_polling()

if __name__ == "__main__":
    main()
