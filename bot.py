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
    global current_question, answered_users, current_message_id, question_index
    answered_users = set()

    if not questions:
        logger.error("No questions available.")
        return False

    if is_test:
        current_question = random.choice(questions)
    else:
        if question_index >= len(questions):
            logger.info("All questions have been posted.")
            return False
        current_question = questions[question_index]
        question_index += 1

    logger.info(f"send_question called, is_test: {is_test}, question: {current_question.get('question')}")
    keyboard = [[InlineKeyboardButton(opt, callback_data=opt)] for opt in current_question.get("options", [])]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"📝 {'Test' if is_test else 'Daily'} Challenge:\n\n{current_question.get('question')}",
            reply_markup=reply_markup,
            disable_web_page_preview=True,
            disable_notification=False,
        )

        if message and message.message_id:
            current_message_id = message.message_id
            logger.info("send_question: message sent successfully")
            return True
        else:
            logger.info("send_question: message sending failed")
            return False

    except Exception as e:
        logger.error(f"send_question: Failed to send question: {e}")
        return False

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

async def heartbeat(context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    questions_left = len(questions) - question_index
    await context.bot.send_message(chat_id=OWNER_ID, text=f"💓 Heartbeat check - Bot is alive at {now}, Questions Left: {questions_left}")

async def test_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info(f"test_question called by user ID: {update.effective_user.id}")
    logger.info(f"OWNER_ID: {OWNER_ID}")
    if update.effective_user.id != OWNER_ID:
        logger.info("test_question: user not authorized")
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    if await send_question(context, is_test=True):
        await update.message.reply_text("✅ Test question sent.")
    else:
        await update.message.reply_text("❌ Failed to send test question.")

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
