import os
import json
import logging
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, PollAnswerHandler, MessageHandler, filters
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
    await update.message.reply_text("Welcome to the English Quiz Bot! Use /test to check functionality.")

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Send a test message to the user's DM
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="✅ Bot is working! Use /leaderboard to see scores."
    )

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
    port = int(os.getenv("PORT", 8443))
    
    # Initialize scheduler
    scheduler.add_job(send_question, 'interval', minutes=5, args=[None])  # Send questions every 5 minutes
    scheduler.start()

    # Build the application
    application = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    
    # Add handlers
    handlers = [
        CommandHandler("start", start),
        CommandHandler("test", test_command),
        CommandHandler("leaderboard", leaderboard_command),
        CallbackQueryHandler(button_response_handler),
        PollAnswerHandler(poll_answer_handler)
    ]
    application.add_handlers(handlers)

    # Run webhook
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path="/webhook",
        webhook_url=os.getenv("WEBHOOK_URL")
    )

if __name__ == "__main__":
    fetch_data()
    main()
