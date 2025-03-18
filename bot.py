import os
import logging
import random
import json
import requests
import time
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, JobQueue
import pytz

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
WEEKLY_QUESTIONS_JSON_URL = os.getenv("WEEKLY_QUESTIONS_JSON_URL")

# Global variables
questions = []
leaderboard = {}
answered_users = set()
current_question = None
current_message_id = None
question_index = 0
weekly_questions = []
weekly_poll_message_ids = []
weekly_user_answers = {}

# Load Questions from URL
def load_questions():
    global questions
    try:
        response = requests.get(QUESTIONS_JSON_URL)
        response.raise_for_status()
        questions = response.json()
        logger.info(f"Loaded {len(questions)} questions from {QUESTIONS_JSON_URL}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching questions from {QUESTIONS_JSON_URL}: {e}")
        questions = []
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from {QUESTIONS_JSON_URL}")
        questions = []

# Load Leaderboard from URL
def load_leaderboard():
    global leaderboard
    try:
        response = requests.get(LEADERBOARD_JSON_URL)
        response.raise_for_status()
        leaderboard = response.json()
        logger.info(f"Loaded leaderboard from {LEADERBOARD_JSON_URL}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching leaderboard from {LEADERBOARD_JSON_URL}: {e}")
        leaderboard = {}
    except json.JSONDecodeError:
        logger.error(f"Error decoding leaderboard from {LEADERBOARD_JSON_URL}")
        leaderboard = {}

# Load Weekly Questions from URL
def load_weekly_questions():
    global weekly_questions
    try:
        response = requests.get(WEEKLY_QUESTIONS_JSON_URL)
        response.raise_for_status()
        weekly_questions = response.json()
        logger.info(f"Loaded {len(weekly_questions)} weekly questions from {WEEKLY_QUESTIONS_JSON_URL}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching weekly questions from {WEEKLY_QUESTIONS_JSON_URL}: {e}")
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from {WEEKLY_QUESTIONS_JSON_URL}")
    except Exception as e:
        logger.error(f"Error loading weekly questions: {e}")

load_questions()
load_leaderboard()
load_weekly_questions()

async def send_question(context: ContextTypes.DEFAULT_TYPE, is_test=False) -> bool:
    # ... (rest of send_question function)

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (rest of handle_answer function)

async def heartbeat(context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (rest of heartbeat function)

async def test_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (rest of test_question function)

async def set_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (rest of set_webhook function)

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (rest of leaderboard_command function)

async def send_weekly_questionnaire(context: ContextTypes.DEFAULT_TYPE):
    global weekly_poll_message_ids, weekly_user_answers
    weekly_poll_message_ids = []
    weekly_user_answers = {}

    if not weekly_questions:
        logger.error("No weekly questions available.")
        return

    for i, question in enumerate(weekly_questions):
        try:
            message = await context.bot.send_poll(
                chat_id=CHANNEL_ID,
                question=question["question"],
                options=question["options"],
                type=Poll.QUIZ,
                correct_option_id=question["correct_option"],
                open_period=60  # 1 minute
            )
            weekly_poll_message_ids.append(message.message_id)
            time.sleep(60)  # Wait for 1 minute
        except Exception as e:
            logger.error(f"Error sending weekly poll {i + 1}: {e}")

    context.job_queue.run_once(close_weekly_polls, when=600)  # Close polls after 10 minutes
    context.job_queue.run_once(display_weekly_results, when=1200) # Display results after 20 minutes

async def handle_weekly_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll_answer = update.poll_answer
    user_id = poll_answer.user.id
    poll_id = poll_answer.poll_id
    selected_option = poll_answer.option_ids[0] if poll_answer.option_ids else None

    if poll_id not in weekly_user_answers:
        weekly_user_answers[poll_id] = {}

    weekly_user_answers[poll_id][user_id] = selected_option
    logger.info(f"Weekly user answers: {weekly_user_answers}")

async def close_weekly_polls(context: ContextTypes.DEFAULT_TYPE):
    for poll_id in weekly_poll_message_ids:
        try:
            await context.bot.stop_poll(chat_id=CHANNEL_ID, message_id=poll_id)
        except Exception as e:
            logger.error(f"Error closing poll {poll_id}: {e}")

async def display_weekly_results(context: ContextTypes.DEFAULT_TYPE):
    results = {}
    for poll_id, user_answers in weekly_user_answers.items():
        question_index = weekly_poll_message_ids.index(poll_id)
        correct_option = weekly_questions[question_index]["correct_option"]

        for user_id, selected_option in user_answers.items():
            if user_id not in results:
                results[user_id] = {"correct": 0, "total": 0}
            results[user_id]["total"] += 1
            if selected_option == correct_option:
                results[user_id]["correct"] += 1

    result_message = "🏆 Weekly Questionnaire Results 🏆\n\n"
    for user_id, scores in results.items():
        user = await context.bot.get_chat(user_id)
        result_message += f"{user.first_name}: {scores['correct']}/{scores['total']} correct\n"

    await context.bot.send_message(chat_id=CHANNEL_ID, text=result_message)

async def test_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_weekly_questionnaire(context)

def get_utc_time(hour, minute, tz_name):
    tz = pytz.timezone(tz_name)
    local_time = tz.localize(datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0))
    return local_time.astimezone(pytz.utc).time()

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    job_queue = application.job_queue

    job_queue.run_daily(send_question, get_utc_time(8, 0, "Asia/Gaza"))
    job_queue.run_daily(send_question, get_utc_time(12, 30, "Asia/Gaza"), name="second_question")
    job_queue.run_daily(send_question, get_utc_time(18, 0, "Asia/Gaza"))
    # job_queue.run_weekly(send_weekly_questionnaire, datetime.time(18, 0, 0), days=(5,)) # Friday at 6 PM - commented out for testing.

    job_queue.run_repeating(heartbeat, interval=60)

    application.add_handler(CommandHandler("test", test_question))
    application.add_handler(CallbackQueryHandler(handle_answer))
    application.add_handler(CommandHandler("setwebhook", set_webhook))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CallbackQueryHandler(handle_weekly_poll_answer))
    application.add_handler(CommandHandler("testweekly", test_weekly)) #add test command

    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting bot on port {port}")
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
    )

if __name__ == "__main__":
    main()
