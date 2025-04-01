import os
import logging
import random
import json
import requests
import time
import aiohttp
import asyncio
import pytz
import base64
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, JobQueue, PollAnswerHandler, filters

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))
DISCUSSION_GROUP_ID = int(os.getenv("DISCUSSION_GROUP_ID", "0"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
WEEKLY_QUESTIONS_JSON_URL = os.getenv("WEEKLY_QUESTIONS_JSON_URL")
PORT = int(os.getenv("PORT", "5000"))

# Constants
QUESTION_DURATION = 30  # Default duration (seconds)
NEXT_QUESTION_DELAY = 2  # seconds between questions
MAX_QUESTIONS = 10  # Maximum number of questions per test

# Global variables
questions = []
leaderboard = {}
current_question = None
current_message_id = None
user_answers = {}
weekly_questions = []
weekly_question_index = 0
weekly_poll_message_ids = []
weekly_user_answers = {}
answered_users = set()
used_weekly_questions = set()

# Load Questions from URL
def load_questions():
    global questions
    try:
        response = requests.get(QUESTIONS_JSON_URL)
        response.raise_for_status()
        questions = response.json()
        logger.info(f"Loaded {len(questions)} questions from {QUESTIONS_JSON_URL}")
        logger.debug(f"Loaded questions: {questions}") #log the questions.
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching questions from {QUESTIONS_JSON_URL}: {e}")
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from {QUESTIONS_JSON_URL}")
    except Exception as e:
        logger.error(f"Error loading questions: {e}")

# Load Leaderboard from URL
def load_leaderboard():
    global leaderboard
    try:
        response = requests.get(LEADERBOARD_JSON_URL)
        response.raise_for_status()
        leaderboard = response.json()
        logger.info(f"Loaded leaderboard from {LEADERBOARD_JSON_URL}")
        logger.debug(f"Loaded leaderboard: {leaderboard}") #log the leaderboard
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching leaderboard from {LEADERBOARD_JSON_URL}: {e}")
    except json.JSONDecodeError:
        logger.error(f"Error decoding leaderboard from {LEADERBOARD_JSON_URL}")
    except Exception as e:
        logger.error(f"Error loading leaderboard: {e}")

# Load Weekly Questions from URL
def load_weekly_questions():
    global weekly_questions
    try:
        response = requests.get(WEEKLY_QUESTIONS_JSON_URL)
        response.raise_for_status()
        weekly_questions = response.json()
        logger.info(f"Loaded {len(weekly_questions)} weekly questions from {WEEKLY_QUESTIONS_JSON_URL}")
        logger.debug(f"loaded weekly questions: {weekly_questions}") #log the weekly questions
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching weekly questions from {WEEKLY_QUESTIONS_JSON_URL}: {e}")
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from {WEEKLY_QUESTIONS_JSON_URL}")
    except Exception as e:
        logger.error(f"Error loading weekly questions: {e}")

load_questions()
load_leaderboard()
load_weekly_questions()

async def send_question(context: ContextTypes.DEFAULT_TYPE):
    global current_question, answered_users, current_message_id
    answered_users = set()
    current_question = random.choice(questions)
    keyboard = [[InlineKeyboardButton(option, callback_data=option)] for option in current_question.get("options", [])]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=current_question.get("question"),
            reply_markup=reply_markup,
            disable_web_page_preview=True,
            disable_notification=False,
        )
        if message and message.message_id:
            current_message_id = message.message_id
            logger.info("send_question: message sent successfully")
            logger.debug(f"send_question: current_question: {current_question}") #log the current question.
        else:
            logger.info("send_question: message sending failed")

    except Exception as e:
        logger.error(f"send_question: Failed to send question: {e}")

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global answered_users, current_question, current_message_id, leaderboard

    query = update.callback_query
    await query.answer()  # Always answer the callback query

    if not query or not current_question:
        logger.warning("handle_answer: query or current_question is None")
        return

    user_id = query.from_user.id
    username = query.from_user.first_name

    if user_id in answered_users:
        await query.answer("❌ You already answered this question.", show_alert=True)
        return

    answered_users.add(user_id)
    user_answer = query.data.strip()
    correct_answer = current_question.get("correct_option", "").strip()

    logger.info(f"handle_answer: User answer: '{user_answer}'")
    logger.info(f"handle_answer: Correct answer: '{correct_answer}'")
    logger.info(f"handle_answer: user_id: '{user_id}'")

    correct = user_answer == correct_answer

    if correct:
        if str(user_id) not in leaderboard:
            leaderboard[str(user_id)] = {"username": username, "score": 0}
        leaderboard[str(user_id)]["score"] += 1

        explanation = current_question.get("explanation", "No explanation provided.")
        edited_text = (
            "📝 Daily Challenge (Answered)\n\n"
            f"Question: {current_question.get('question')}\n"
            f"✅ Correct Answer: {current_question.get('correct_option')}\n"
            f"ℹ️ Explanation: {explanation}\n\n"
            f"🏆 Winner: {username}"
        )
        try:
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=current_message_id,
                text=edited_text,
                reply_markup=None  # Remove the inline keyboard
            )
            logger.info("handle_answer: message edited successfully")
        except Exception as e:
            logger.error(f"handle_answer: Failed to edit message: {e}")
    
    save_leaderboard()

def save_leaderboard():
    try:
        github_token = os.getenv("GITHUB_TOKEN")
        repo_owner = "TegerPython"  # Replace with your GitHub username
        repo_name = "bot_data"  # Replace with your repository name
        file_path = "leaderboard.json"

        # Get the current file's SHA for updating
        get_file_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{file_path}"
        headers = {"Authorization": f"token {github_token}", "Accept": "application/vnd.github.v3+json"}
        get_response = requests.get(get_file_url, headers=headers)
        get_response.raise_for_status()
        sha = get_response.json()["sha"]

        # Update the file
        content = json.dumps(leaderboard, indent=4).encode("utf-8")
        encoded_content = base64.b64encode(content).decode("utf-8")

        update_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{file_path}"
        data = {
            "message": "Update leaderboard",
            "content": encoded_content,
            "sha": sha,
            "branch": "main",  # Or your branch name
        }
        update_response = requests.put(update_url, headers=headers, json=data)
        update_response.raise_for_status()

        logger.info("Leaderboard saved successfully to GitHub.")
        logger.debug(f"saved leaderboard: {leaderboard}") #log the leaderboard
    except Exception as e:
        logger.error(f"Error saving leaderboard to GitHub: {e}")
# ... (rest of your code, including functions like test_question, heartbeat, set_webhook, leaderboard_command, etc.)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    application.add_handler(CallbackQueryHandler(handle_answer))
    application.add_handler(CommandHandler("start", start_test_command))
    application.add_handler(CommandHandler("weeklytest", start_test_command, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("test", test_question))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    
    # Poll answer handler
    application.add_handler(PollAnswerHandler(handle_poll_answer))
    
    # Initial scheduling
    application.job_queue.run_once(
        lambda ctx: asyncio.create_task(schedule_weekly_test(ctx)),
        5,  # Initial delay to let the bot start
        name="initial_schedule"
    )
    
    # Start bot
    if WEBHOOK_URL:
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
            drop_pending_updates=True
        )
    else:
        application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
