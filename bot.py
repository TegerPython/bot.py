import os
import logging
import random
import json
import requests
import time
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll, ChatPermissions
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, JobQueue, PollAnswerHandler
import pytz
import base64

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
logger.info(f"BOT_TOKEN: {BOT_TOKEN}")

CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
DISCUSSION_GROUP_ID = int(os.getenv("DISCUSSION_GROUP_ID"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
WEEKLY_QUESTIONS_JSON_URL = os.getenv("WEEKLY_QUESTIONS_JSON_URL")
WEEKLY_LEADERBOARD_JSON_URL = os.getenv("WEEKLY_LEADERBOARD_JSON_URL")

# Global variables
questions = []
leaderboard = {}
current_question = None
current_message_id = None
user_answers = {}
weekly_questions = []
weekly_leaderboard = {}
weekly_question_index = 0
weekly_poll_message_ids = []
weekly_user_answers = {}
answered_users = set()

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

# Load Weekly Leaderboard from URL
def load_weekly_leaderboard():
    global weekly_leaderboard
    try:
        response = requests.get(WEEKLY_LEADERBOARD_JSON_URL)
        response.raise_for_status()
        weekly_leaderboard = response.json()
        logger.info(f"Loaded weekly leaderboard from {WEEKLY_LEADERBOARD_JSON_URL}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching weekly leaderboard from {WEEKLY_LEADERBOARD_JSON_URL}: {e}")
    except json.JSONDecodeError:
        logger.error(f"Error decoding weekly leaderboard from {WEEKLY_LEADERBOARD_JSON_URL}")
    except Exception as e:
        logger.error(f"Error loading weekly leaderboard: {e}")

load_questions()
load_leaderboard()
load_weekly_questions()
load_weekly_leaderboard()

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
        else:
            logger.info("send_question: message sending failed")

    except Exception as e:
        logger.error(f"send_question: Failed to send question: {e}")

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global answered_users, current_question, current_message_id, leaderboard

    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.first_name

    if user_id in answered_users:
        await query.answer("❌ You already answered this question.")
        return

    answered_users.add(user_id)
    user_answer = query.data.strip()
    correct_answer = current_question.get("correct_option", "").strip()

    logger.info(f"User answer: '{user_answer}'")
    logger.info(f"Correct answer: '{correct_answer}'")

    correct = user_answer == correct_answer

    if correct:
        await query.answer("✅ Correct!")
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
                text=edited_text
            )
        except Exception as e:
            logger.error(f"Failed to edit message: {e}")
    else:
        await query.answer("❌ Incorrect.")
    save_leaderboard()

def save_leaderboard():
    try:
        github_token = os.getenv("GITHUB_TOKEN")
        repo_owner = "TegerPython"
        repo_name = "bot_data"
        file_path = "leaderboard.json"

        get_file_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{file_path}"
        headers = {"Authorization": f"token {github_token}", "Accept": "application/vnd.github.v3+json"}
        get_response = requests.get(get_file_url, headers=headers)
        get_response.raise_for_status()
        sha = get_response.json()["sha"]

        content = json.dumps(leaderboard, indent=4).encode("utf-8")
        encoded_content = base64.b64encode(content).decode("utf-8")

        update_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{file_path}"
        data = {
            "message": "Update leaderboard",
            "content": encoded_content,
            "sha": sha,
            "branch": "main",
        }
        update_response = requests.put(update_url, headers=headers, json=data)
        update_response.raise_for_status()

        logger.info("Leaderboard saved successfully to GitHub.")
    except Exception as e:
        logger.error(f"Error saving leaderboard to GitHub: {e}")

def save_weekly_leaderboard():
    try:
        github_token = os.getenv("GITHUB_TOKEN")
        repo_owner = "TegerPython"
        repo_name = "bot_data"
        file_path = "weekly_leaderboard.json"

        get_file_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{file_path}"
        headers = {"Authorization": f"token {github_token}", "Accept": "application/vnd.github.v3+json"}
        get_response = requests.get(get_file_url, headers=headers)
        get_response.raise_for_status()
        sha = get_response.json()["sha"]

        content = json.dumps(weekly_leaderboard, indent=4).encode("utf-8")
        encoded_content = base64.b64encode(content).decode("utf-8")

        update_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{file_path}"
        data = {
            "message": "Update weekly leaderboard",
            "content": encoded_content,
            "sha": sha,
            "branch": "main",
        }
        update_response = requests.put(update_url, headers=headers, json=data)
        update_response.raise_for_status()

        logger.info("Weekly leaderboard saved successfully to GitHub.")
    except Exception as e:
        logger.error(f"Error saving weekly leaderboard to GitHub: {e}")

async def test_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        if update.message:
            await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    await send_question(context)
    if update.message:
        await update.message.reply_text("✅ Test question sent.")

async def heartbeat(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await context.bot.send_message(chat_id=OWNER_ID, text=f"💓 Heartbeat check - Bot is alive at {now}")

async def set_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        if update.message:
            await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    await context.bot.set_webhook(f"{WEBHOOK_URL}/{BOT_TOKEN}")
    if update.message:
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

async def weekly_leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        logger.info(f"Weekly Leaderboard data: {weekly_leaderboard}")
        sorted_leaderboard = sorted(weekly_leaderboard.items(), key=lambda item: item[1]["score"], reverse=True)
        leaderboard_text = "🏆 Weekly Leaderboard 🏆\n\n"
        for rank, (user_id, player) in enumerate(sorted_leaderboard, start=1):
            leaderboard_text += f"{rank}. {player['username']}: {player['score']} points\n"
        await update.message.reply_text(leaderboard_text)
    except KeyError as e:
        logger.error(f"Error in weekly_leaderboard_command: KeyError - {e}")
        await update.message.reply_text("❌ Failed to display weekly leaderboard due to data error.")
    except Exception as e:
        logger.error(f"Error in weekly_leaderboard_command: {e}")
        await update.message.reply_text("❌ Failed to display weekly leaderboard.")

async def send_weekly_questionnaire(context: ContextTypes.DEFAULT_TYPE):
    global weekly_poll_message_ids, weekly_user_answers, weekly_question_index, weekly_leaderboard

    if not weekly_questions:
        logger.error("No weekly questions available.")
        return

    start_index = weekly_question_index * 3  # for test purposes 3 questions
    end_index = min(start_index + 3, len(weekly_questions))  # for test purposes 3 questions

    if start_index >= len(weekly_questions):
        logger.info("All weekly questions have been used. Restarting from the beginning.")
        weekly_question_index = 0
        start_index = 0
        end_index = min(3, len(weekly_questions))  # for test purposes 3 questions

    weekly_poll_message_ids = []
    weekly_user_answers = {}

    for i in range(start_index, end_index):
        try:
            question = weekly_questions[i]
            poll_message = await context.bot.send_poll(
                chat_id=DISCUSSION_GROUP_ID,
                question=question["question"],
                options=question["options"],
                type=Poll.QUIZ,
                correct_option_id=question["correct_option"],
                open_period=5,  # 5 seconds test purposes
                is_anonymous=False  # non anonymous poll to get user info
            )
            weekly_poll_message_ids.append(poll_message.message_id)

            # Send a channel message with a deep link to the poll in the group
            group_link = f"tg://resolve?domain={context.bot.get_chat(DISCUSSION_GROUP_ID).username}&poll={poll_message.message_id}"
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=f"New weekly question! Participate here: {group_link}"
            )

            time.sleep(5)  # 5 seconds test purposes
        except Exception as e:
            logger.error(f"Error sending weekly poll {i + 1}: {e}")

    weekly_question_index += 1
    context.job_queue.run_once(close_weekly_polls, 5 * 3)  # for test purposes 3 questions * 5 seconds

async def close_weekly_polls(context: ContextTypes.DEFAULT_TYPE):
    global weekly_poll_message_ids, weekly_leaderboard
    for message_id in weekly_poll_message_ids:
        try:
            poll = await context.bot.stop_poll(chat_id=DISCUSSION_GROUP_ID, message_id=message_id)
            for option in poll.options:
                if option.is_chosen:
                    for user in option.voters:
                        if poll.options.index(option) == poll.correct_option_id:
                            if str(user.id) not in weekly_leaderboard:
                                weekly_leaderboard[str(user.id)] = {"username": user.first_name, "score": 0}
                            weekly_leaderboard[str(user.id)]["score"] += 1
        except Exception as e:
            logger.error(f"Error closing weekly poll {message_id}: {e}")
    save_weekly_leaderboard()
    await context.bot.send_message(chat_id=CHANNEL_ID, text="Weekly questions finished, here is the weekly leaderboard:")
    await weekly_leaderboard_command(Update(update_id=1, message=context.bot.send_message(chat_id=CHANNEL_ID, text="")), context)

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
    application.add_handler(CommandHandler("weeklyleaderboard", weekly_leaderboard_command))
    application.add_handler(PollAnswerHandler(handle_weekly_poll_answer))
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
