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

# Enhanced logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)
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
QUESTION_EXPIRY_TIME = 3600  # 1 hour in seconds
QUESTION_ROTATION_INTERVAL = 1800  # 30 minutes in seconds

# Global variables with improved state management
questions = []
leaderboard = {}
current_question = None
current_message_id = None
question_expiry = None
user_answers = {}
weekly_questions = []
weekly_question_index = 0
weekly_poll_message_ids = []
weekly_user_answers = {}
answered_users = set()
used_weekly_questions = set()

# Load Questions from URL with retry mechanism
def load_questions():
    global questions
    max_retries = 3
    retry_delay = 5
    
    for attempt in range(max_retries):
        try:
            response = requests.get(QUESTIONS_JSON_URL, timeout=10)
            response.raise_for_status()
            questions = response.json()
            logger.info(f"Loaded {len(questions)} questions from {QUESTIONS_JSON_URL}")
            return
        except requests.exceptions.RequestException as e:
            logger.error(f"Attempt {attempt + 1}: Error fetching questions - {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
        except json.JSONDecodeError:
            logger.error("Error decoding questions JSON")
    logger.error("Failed to load questions after multiple attempts")

# Similar improvements for other load functions
def load_leaderboard():
    global leaderboard
    try:
        response = requests.get(LEADERBOARD_JSON_URL, timeout=10)
        response.raise_for_status()
        leaderboard = response.json()
        logger.info(f"Loaded leaderboard from {LEADERBOARD_JSON_URL}")
    except Exception as e:
        logger.error(f"Error loading leaderboard: {e}")
        leaderboard = {}

def load_weekly_questions():
    global weekly_questions
    try:
        response = requests.get(WEEKLY_QUESTIONS_JSON_URL, timeout=10)
        response.raise_for_status()
        weekly_questions = response.json()
        logger.info(f"Loaded {len(weekly_questions)} weekly questions")
    except Exception as e:
        logger.error(f"Error loading weekly questions: {e}")
        weekly_questions = []

# Initialize data
load_questions()
load_leaderboard()
load_weekly_questions()

async def cleanup_question(context: ContextTypes.DEFAULT_TYPE):
    global current_question, current_message_id, answered_users, question_expiry
    
    if current_question and current_message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=current_message_id,
                text="⌛ This question has expired",
                reply_markup=None
            )
            logger.info(f"Cleaned up question (ID: {current_message_id})")
        except Exception as e:
            logger.error(f"Failed to edit message during cleanup: {e}")
    
    current_question = None
    current_message_id = None
    answered_users = set()
    question_expiry = None

async def send_question(context: ContextTypes.DEFAULT_TYPE):
    global current_question, answered_users, current_message_id, question_expiry
    
    # Clean up any existing question
    await cleanup_question(context)
    
    if not questions:
        logger.error("No questions available to send")
        return

    try:
        current_question = random.choice(questions)
        keyboard = [
            [InlineKeyboardButton(option, callback_data=option)] 
            for option in current_question.get("options", [])
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=current_question.get("question"),
            reply_markup=reply_markup,
            disable_web_page_preview=True,
            disable_notification=False,
        )
        
        if message and message.message_id:
            current_message_id = message.message_id
            question_expiry = time.time() + QUESTION_EXPIRY_TIME
            logger.info(f"Sent question (ID: {current_message_id}), expires at {datetime.fromtimestamp(question_expiry)}")
        else:
            logger.error("Failed to get message ID after sending")
            current_question = None

    except Exception as e:
        logger.error(f"Failed to send question: {e}")
        current_question = None
        current_message_id = None

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.debug("Answer handler triggered")
    global answered_users, current_question, current_message_id, leaderboard, question_expiry

    # Early validation
    if not update.callback_query:
        logger.warning("No callback query in update")
        return

    query = update.callback_query
    await query.answer()

    # Get message ID from the original question message
    try:
        callback_message_id = query.message.message_id
    except AttributeError:
        logger.warning("Missing message in callback query")
        try:
            await query.answer("⚠️ Invalid message", show_alert=True)
        except Exception as e:
            logger.error(f"Failed to send error feedback: {e}")
        return

    # Check if this is the currently active question
    if callback_message_id != current_message_id:
        logger.warning(f"Received answer for old message {callback_message_id} (current: {current_message_id})")
        try:
            await query.answer("⏳ This question has expired", show_alert=True)
        except Exception as e:
            logger.error(f"Failed to send expiry feedback: {e}")
        return

    # Check if question is still valid
    if not current_question or not current_message_id:
        logger.warning("No active question")
        try:
            await query.answer("⚠️ No active question", show_alert=True)
        except Exception as e:
            logger.error(f"Failed to send answer feedback: {e}")
        return

    # Check if question has expired
    if question_expiry and time.time() > question_expiry:
        logger.warning(f"Question {current_message_id} has expired")
        await cleanup_question(context)
        try:
            await query.answer("⌛ This question has expired", show_alert=True)
        except Exception as e:
            logger.error(f"Failed to send expiry feedback: {e}")
        return

    user_id = query.from_user.id
    username = query.from_user.first_name or query.from_user.username or f"User {user_id}"

    # Check if user already answered
    if user_id in answered_users:
        try:
            await query.answer("❌ You already answered this question.", show_alert=True)
        except Exception as e:
            logger.error(f"Failed to send duplicate answer feedback: {e}")
        return

    # Mark user as answered
    answered_users.add(user_id)
    
    try:
        user_answer = query.data.strip()
        correct_answer = current_question.get("correct_option", "").strip()

        logger.info(f"User {username} (ID: {user_id}) answered: '{user_answer}'")
        logger.info(f"Correct answer: '{correct_answer}'")

        correct = user_answer == correct_answer

        if correct:
            # Update leaderboard
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
                    reply_markup=None
                )
                logger.info("Successfully updated question message")
            except Exception as e:
                logger.error(f"Failed to edit message: {e}")
            
            # Save the updated leaderboard
            save_leaderboard()
            
        else:
            try:
                await query.answer("❌ Incorrect answer!", show_alert=False)
            except Exception as e:
                logger.error(f"Failed to send incorrect answer feedback: {e}")

    except Exception as e:
        logger.error(f"Error processing answer: {e}")
        try:
            await query.answer("⚠️ Error processing your answer", show_alert=False)
        except Exception as e:
            logger.error(f"Failed to send error feedback: {e}")

# [Rest of the code remains the same...]

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Handlers
    application.add_handler(CallbackQueryHandler(handle_answer))
    application.add_handler(CommandHandler("start", start_test_command))
    application.add_handler(CommandHandler("weeklytest", start_test_command, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("test", test_question))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(PollAnswerHandler(handle_poll_answer))

    # Scheduled jobs
    application.job_queue.run_repeating(
        cleanup_question,
        interval=3600,  # Every hour
        first=10
    )
    
    application.job_queue.run_repeating(
        rotate_questions,
        interval=QUESTION_ROTATION_INTERVAL,
        first=QUESTION_ROTATION_INTERVAL
    )

    application.job_queue.run_once(
        lambda ctx: asyncio.create_task(schedule_weekly_test(ctx)),
        5,
        name="initial_schedule"
    )

    # Start the bot
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
