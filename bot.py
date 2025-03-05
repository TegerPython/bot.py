import os
import json
import logging
import random
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import Application, CommandHandler, Calimport os
import json
import logging
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, PollAnswerHandler
from apscheduler.schedulers.background import BackgroundScheduler

# Logging setup
logging.basicConfig(
    format="%(levelname)s:%(name)s:%(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

questions = []
leaderboard = {}
scheduler = BackgroundScheduler()

def fetch_data():
    global questions, leaderboard
    questions_url = os.getenv("QUESTIONS_JSON_URL")
    leaderboard_url = os.getenv("LEADERBOARD_JSON_URL")

    try:
        questions_response = requests.get(questions_url)
        questions_response.raise_for_status()
        questions = questions_response.json()
        logger.info(f"Loaded {len(questions)} questions")
    except Exception as e:
        logger.error(f"Could not load questions: {e}")
        questions = []

    try:
        leaderboard_response = requests.get(leaderboard_url)
        leaderboard_response.raise_for_status()
        leaderboard = leaderboard_response.json()
        logger.info(f"Loaded {len(leaderboard)} leaderboard entries")
    except Exception as e:
        logger.error(f"Could not load leaderboard: {e}")
        leaderboard = {}

def update_leaderboard():
    token = os.getenv("GITHUB_TOKEN")
    repo_owner = os.getenv("REPO_OWNER")
    repo_name = os.getenv("REPO_NAME")
    path = "leaderboard.json"

    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{path}"
    headers = {"Authorization": f"Bearer {token}"}

    current_data = json.dumps(leaderboard, indent=2)
    current_sha = requests.get(url, headers=headers).json().get("sha")

    data = {
        "message": "Update leaderboard",
        "content": current_data.encode("utf-8").decode("utf-8"),
        "sha": current_sha,
    }

    response = requests.put(url, headers=headers, json=data)

    if response.status_code in [200, 201]:
        logger.info("Leaderboard updated successfully.")
    else:
        logger.error(f"Failed to update leaderboard: {response.text}")

async def send_question(context: ContextTypes.DEFAULT_TYPE):
    global questions

    if not questions:
        fetch_data()
        if not questions:
            logger.warning("No questions available.")
            return

    question = questions.pop(0)

    if question['type'] == 'poll':
        message = await context.bot.send_poll(
            chat_id=os.getenv("CHANNEL_ID"),
            question=question['question'],
            options=question['options'],
            is_anonymous=False,
            allows_multiple_answers=False
        )
        context.chat_data[message.poll.id] = {
            "correct_option": question['correct_option'],
            "answered_users": set(),
            "question": question
        }

    elif question['type'] == 'buttons':
        keyboard = [[InlineKeyboardButton(option, callback_data=f"answer|{idx}")]
                    for idx, option in enumerate(question['options'])]
        reply_markup = InlineKeyboardMarkup(keyboard)

        message = await context.bot.send_message(
            chat_id=os.getenv("CHANNEL_ID"),
            text=question['question'],
            reply_markup=reply_markup
        )

        context.chat_data[message.message_id] = {
            "correct_option": question['correct_option'],
            "answered_users": set(),
            "question": question
        }

    delete_used_question_from_github()

def delete_used_question_from_github():
    token = os.getenv("GITHUB_TOKEN")
    repo_owner = os.getenv("REPO_OWNER")
    repo_name = os.getenv("REPO_NAME")
    path = "questions.json"

    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{path}"
    headers = {"Authorization": f"Bearer {token}"}

    remaining_data = json.dumps(questions, indent=2)
    current_sha = requests.get(url, headers=headers).json().get("sha")

    data = {
        "message": "Remove used question",
        "content": remaining_data.encode("utf-8").decode("utf-8"),
        "sha": current_sha,
    }

    requests.put(url, headers=headers, json=data)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome to the English Quiz Bot!")

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sorted_board = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    text = "\n".join([f"{i+1}. {user}: {score}" for i, (user, score) in enumerate(sorted_board)])
    await update.message.reply_text(f"Leaderboard:\n{text}")

async def button_response_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data.split("|")

    chat_data = context.chat_data.get(query.message.message_id, {})
    if user_id in chat_data.get("answered_users", set()):
        await query.answer("You already answered!")
        return

    correct_option = chat_data["correct_option"]
    chat_data["answered_users"].add(user_id)

    if int(data[1]) == correct_option:
        leaderboard[str(user_id)] = leaderboard.get(str(user_id), 0) + 1
        update_leaderboard()
        await query.answer("Correct!")
    else:
        await query.answer("Wrong!")

async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    poll_data = context.chat_data.get(answer.poll_id)

    if not poll_data or answer.user.id in poll_data["answered_users"]:
        return

    poll_data["answered_users"].add(answer.user.id)

    if answer.option_ids[0] == poll_data["correct_option"]:
        leaderboard[str(answer.user.id)] = leaderboard.get(str(answer.user.id), 0) + 1
        update_leaderboard()

def main():
    application = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    application.add_handlers([CommandHandler("start", start), PollAnswerHandler(poll_answer_handler)])
    application.run_webhook(url_path="/webhook", webhook_url=os.getenv("WEBHOOK_URL"))

if __name__ == "__main__":
    fetch_data()
    main()
lbackQueryHandler, MessageHandler, ContextTypes, filters
from apscheduler.schedulers.background import BackgroundScheduler

# Logging setup
logging.basicConfig(
    format="%(levelname)s:%(name)s:%(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global variables
questions = []
leaderboard = {}
scheduler = BackgroundScheduler()

# Fetch questions and leaderboard from GitHub
def fetch_data():
    global questions, leaderboard
    questions_url = os.getenv("QUESTIONS_JSON_URL")
    leaderboard_url = os.getenv("LEADERBOARD_JSON_URL")

    try:
        questions_response = requests.get(questions_url)
        questions_response.raise_for_status()
        questions = questions_response.json()
        logger.info(f"Loaded {len(questions)} questions")
    except Exception as e:
        logger.error(f"Could not load questions: {e}")
        questions = []

    try:
        leaderboard_response = requests.get(leaderboard_url)
        leaderboard_response.raise_for_status()
        leaderboard = leaderboard_response.json()
        logger.info(f"Loaded {len(leaderboard)} leaderboard entries")
    except Exception as e:
        logger.error(f"Could not load leaderboard: {e}")
        leaderboard = {}

# Update leaderboard on GitHub
def update_leaderboard():
    token = os.getenv("GITHUB_TOKEN")
    repo_owner = os.getenv("REPO_OWNER")
    repo_name = os.getenv("REPO_NAME")
    path = "leaderboard.json"

    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{path}"
    headers = {"Authorization": f"Bearer {token}"}

    current_data = json.dumps(leaderboard, indent=2)
    current_sha = requests.get(url, headers=headers).json().get("sha")

    data = {
        "message": "Update leaderboard",
        "content": current_data.encode("utf-8").decode("utf-8"),
        "sha": current_sha,
    }

    response = requests.put(url, headers=headers, json=data)

    if response.status_code == 200 or response.status_code == 201:
        logger.info("Leaderboard updated successfully.")
    else:
        logger.error(f"Failed to update leaderboard: {response.text}")

# Send question to the channel
async def send_question(context: ContextTypes.DEFAULT_TYPE):
    global questions

    if not questions:
        fetch_data()
        if not questions:
            logger.warning("No questions available.")
            return

    question = questions.pop(0)

    if question['type'] == 'poll':
        message = await context.bot.send_poll(
            chat_id=os.getenv("CHANNEL_ID"),
            question=question['question'],
            options=question['options'],
            is_anonymous=False,
            allows_multiple_answers=False
        )
        context.chat_data[message.poll.id] = {
            "correct_option": question['correct_option'],
            "answered_users": set(),
            "question": question
        }

    elif question['type'] == 'buttons':
        keyboard = [
            [InlineKeyboardButton(option, callback_data=f"answer|{idx}")]
            for idx, option in enumerate(question['options'])
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        message = await context.bot.send_message(
            chat_id=os.getenv("CHANNEL_ID"),
            text=question['question'],
            reply_markup=reply_markup
        )

        context.chat_data[message.message_id] = {
            "correct_option": question['correct_option'],
            "answered_users": set(),
            "question": question
        }

    delete_used_question_from_github()

# Delete the used question from GitHub
def delete_used_question_from_github():
    token = os.getenv("GITHUB_TOKEN")
    repo_owner = os.getenv("REPO_OWNER")
    repo_name = os.getenv("REPO_NAME")
    path = "questions.json"

    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{path}"
    headers = {"Authorization": f"Bearer {token}"}

    remaining_data = json.dumps(questions, indent=2)
    current_sha = requests.get(url, headers=headers).json().get("sha")

    data = {
        "message": "Remove used question",
        "content": remaining_data.encode("utf-8").decode("utf-8"),
        "sha": current_sha,
    }

    response = requests.put(url, headers=headers, json=data)

    if response.status_code in [200, 201]:
        logger.info("Used question removed from GitHub.")
    else:
        logger.error(f"Failed to update questions: {response.text}")

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome to the English Quiz Bot!")

# Leaderboard command
async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sorted_leaderboard = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
    leaderboard_text = "\n".join([f"{idx+1}. {user_id}: {score}" for idx, (user_id, score) in enumerate(sorted_leaderboard)])
    await update.message.reply_text(f"Leaderboard:\n{leaderboard_text}")

# Handle button responses
async def button_response_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if user_id in context.chat_data.get(query.message.message_id, {}).get("answered_users", set()):
        await query.answer("You have already answered.")
        return

    correct_option = context.chat_data[query.message.message_id]["correct_option"]
    question = context.chat_data[query.message.message_id]["question"]
    context.chat_data[query.message.message_id]["answered_users"].add(user_id)

    if int(query.data.split("|")[1]) == correct_option:
        leaderboard[str(user_id)] = leaderboard.get(str(user_id), 0) + 1
        update_leaderboard()
        await query.answer("Correct!")
    else:
        await query.answer("Wrong answer.")

    await query.edit_message_text(
        text=f"{question['question']}\n\nCorrect answer: {question['options'][correct_option]}"
    )

# Handle poll responses
async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll_id = update.poll_answer.poll_id
    user_id = update.poll_answer.user.id

    if poll_id not in context.chat_data:
        return

    poll_data = context.chat_data[poll_id]
    if user_id in poll_data["answered_users"]:
        return

    poll_data["answered_users"].add(user_id)

    if update.poll_answer.option_ids[0] == poll_data["correct_option"]:
        leaderboard[str(user_id)] = leaderboard.get(str(user_id), 0) + 1
        update_leaderboard()

# Test command
async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is running fine.")

# Main
def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    webhook_url = os.getenv("WEBHOOK_URL")

    print(f"🔗 Attempting to set webhook to: {webhook_url}")

    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(CallbackQueryHandler(button_response_handler))
    application.add_handler(MessageHandler(filters.POLL_ANSWER, poll_answer_handler))

    scheduler.add_job(send_question, trigger='cron', hour=8, minute=0)
    scheduler.add_job(send_question, trigger='cron', hour=12, minute=0)
    scheduler.add_job(send_question, trigger='cron', hour=18, minute=0)

    scheduler.start()

    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get('PORT', 8080)),
        url_path="/webhook",
        webhook_url=webhook_url
    )

if __name__ == "__main__":
    fetch_data()
    main()
