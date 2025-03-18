import os
import logging
import random
import json
import requests
import time
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, JobQueue
import pytz

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
logger.info(f"BOT_TOKEN: {BOT_TOKEN}")

CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
WEEKLY_QUESTIONS_JSON_URL = os.getenv("WEEKLY_QUESTIONS_JSON_URL")

# Global variables
questions = []
leaderboard = {}
current_question = None
user_answers = {}
weekly_questions = []
weekly_question_index = 0
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
    global current_question, user_answers
    current_question = random.choice(questions)
    user_answers = {}
    keyboard = [[InlineKeyboardButton(option, callback_data=str(i)) for i, option in enumerate(current_question["options"])]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id=CHANNEL_ID, text=current_question["question"], reply_markup=reply_markup)

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name
    answer = int(query.data)

    if current_question:
        if user_id not in user_answers:
            user_answers[user_id] = answer
            if answer == current_question["correct_option"]:
                if user_id not in leaderboard:
                    leaderboard[user_id] = {"score": 0, "username": username}
                leaderboard[user_id]["score"] += 1
                await query.answer(text="✅ Correct!")
            else:
                await query.answer(text="❌ Incorrect.")
        else:
            await query.answer(text="You've already answered this question.")
        save_leaderboard()
    else:
        await query.answer(text="No question available.")

def save_leaderboard():
    try:
        response = requests.put(LEADERBOARD_JSON_URL, json=leaderboard)
        response.raise_for_status()
        logger.info("Leaderboard saved successfully.")
    except Exception as e:
        logger.error(f"Error saving leaderboard: {e}")

async def test_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_question(context)

async def heartbeat(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Heartbeat: Bot is alive.")

async def set_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    await context.bot.set_webhook(f"{WEBHOOK_URL}/{BOT_TOKEN}")
    await update.message.reply_text("✅ Webhook refreshed.")

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        logger.info(f"Leaderboard data: {leaderboard}")
        sorted_leaderboard = sorted(leaderboard.items(), key=lambda item: item[1]["score"], reverse=True)
        leaderboard_text = "🏆 Leaderboard 🏆\n\n"
        for rank, (user_id, player) in enumerate(sorted_leaderboard, start=1):
            leaderboard_text += f"{rank}. {player['username']}: {player['score']} points\n"
        await update.message.reply_text(leaderboard_text)
    except KeyError as e:
        logger.error(f"Error in leaderboard_command: KeyError - {e}")
        await update.message.reply_text("❌ Failed to display leaderboard due to data error.")
    except Exception as e:
        logger.error(f"Error in leaderboard_command: {e}")
        await update.message.reply_text("❌ Failed to display leaderboard.")

async def send_weekly_questionnaire(context: ContextTypes.DEFAULT_TYPE):
    global weekly_poll_message_ids, weekly_user_answers, weekly_question_index

    if not weekly_questions:
        logger.error("No weekly questions available.")
        return

    start_index = weekly_question_index * 10
    end_index = min(start_index + 10, len(weekly_questions))

    if start_index >= len(weekly_questions):
        logger.info("All weekly questions have been used. Restarting from the beginning.")
        weekly_question_index = 0
        start_index = 0
        end_index = min(10, len(weekly_questions))

    weekly_poll_message_ids = []
    weekly_user_answers = {}

    for i in range(start_index, end_index):
        try:
            question = weekly_questions[i]
            message = await context.bot.send_poll(
                chat_id=CHANNEL_ID,
                question=question["question"],
                options=question["options"],
                type=Poll.QUIZ,
                correct_option_id=question["correct_option"],
                open_period=30  # 30 seconds
            )
            weekly_poll_message_ids.append(message.message_id)
            time.sleep(30)  # Wait for 30 seconds
        except Exception as e:
            logger.error(f"Error sending weekly poll {i + 1}: {e}")

    weekly_question_index += 1  # Increment the index after sending 10 questions
    context.job_queue.run_once(close_weekly_polls, 30 * 10)  # Close after 10 polls * 30 seconds

async def close_weekly_polls(context: ContextTypes.DEFAULT_TYPE):
    global weekly_poll_message_ids, weekly_user_answers
    for message_id in weekly_poll_message_ids:
        try:
            await context.bot.stop_poll(chat_id=CHANNEL_ID, message_id=message_id)
        except Exception as e:
            logger.error(f"Error closing weekly poll {message_id}: {e}")

async def handle_weekly_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll = update.poll
    user_id = poll.voter_count
    if poll.is_closed:
        return
    if user_id not in weekly_user_answers:
        weekly_user_answers[user_id] = poll.options[poll.correct_option_id].voter_count
    else:
        weekly_user_answers[user_id] += poll.options[poll.correct_option_id].voter_count

async def test_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_weekly_questionnaire(context)

def get_utc_time(hour, minute, timezone_str):
    tz = pytz.timezone(timezone_str)
    local_time = datetime.now(tz).replace(hour=hour, minute=minute, second=0, microsecond=0)
    utc_time = local_time.astimezone(pytz.utc).time()
    return utc_time

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    job_queue = application.job_queue

    job_queue.run_daily(send_question, get_utc_time(8, 0, "Asia/Gaza"))
    job_queue.run_daily(send_question, get_utc_time(12, 30, "Asia/Gaza"), name="second_question")
    job_queue.run_daily(send_question, get_utc_time(18, 0, "Asia/Gaza"))

    friday = 4  # Monday is 0, Tuesday is 1, ..., Friday is 4
    now = datetime.now(pytz.utc)
    target_time = get_utc_time(18, 0, "Asia/Gaza")
    target_datetime = datetime.combine(now.date(), target_time).replace(tzinfo=pytz.utc)

    days_ahead = (friday - now.weekday() + 7) % 7
    next_friday = now + timedelta(days=days_ahead)
    next_friday_at_target_time = datetime.combine(next_friday.date(), target_time).replace(tzinfo=pytz.utc)

    job_queue.run_daily(
        send_weekly_questionnaire,
        time=next_friday_at_target_time.time(),
        days=(friday,),
        name="weekly_questionnaire"
    )

    job_queue.run_repeating(heartbeat, interval=60)

    application.add_handler(CommandHandler("test", test_question))
    application.add_handler(CallbackQueryHandler(handle_answer))
    application.add_handler(CommandHandler("setwebhook", set_webhook))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CallbackQueryHandler(handle_weekly_poll_answer))
    application.add_handler(CommandHandler("testweekly", test_weekly))

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
