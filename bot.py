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
logger.info(f"BOT_TOKEN: {BOT_TOKEN}")

CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))
SECOND_OWNER = int(os.getenv("SECOND_OWNER"))  # Add this line
DISCUSSION_GROUP_ID = int(os.getenv("DISCUSSION_GROUP_ID", "0"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
WEEKLY_QUESTIONS_JSON_URL = os.getenv("WEEKLY_QUESTIONS_JSON_URL")
ENGLISH_NOTES_JSON_URL = os.getenv("ENGLISH_NOTES_JSON_URL")  # URL for English notes
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
answered_users = set()
used_weekly_questions = set()
used_daily_questions = set()  # Track used daily questions
english_notes = []  # List to store English notes

# Load Questions from URL
DEBUG = True  # Set to True for extra debugging

def load_questions():
    global questions
    try:
        if DEBUG:
            logger.info(f"Attempting to load questions from {QUESTIONS_JSON_URL}")
        response = requests.get(QUESTIONS_JSON_URL)
        if DEBUG:
            logger.info(f"Response status: {response.status_code}")
        response.raise_for_status()
        questions = response.json()
        if DEBUG:
            logger.info(f"Questions loaded: {len(questions)}")
            if questions:
                logger.info(f"First question sample: {json.dumps(questions[0])[:200]}...")
        logger.info(f"Loaded {len(questions)} questions from {QUESTIONS_JSON_URL}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching questions from {QUESTIONS_JSON_URL}: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from {QUESTIONS_JSON_URL}: {e}")
        if DEBUG:
            try:
                logger.error(f"Raw response: {response.text[:500]}...")
            except:
                pass
    except Exception as e:
        logger.error(f"Error loading questions: {e}")

def load_leaderboard():
    global leaderboard
    try:
        response = requests.get(LEADERBOARD_JSON_URL)
        response.raise_for_status()
        leaderboard = response.json()
        
        # Ensure all required keys exist in each entry
        for user_id, data in leaderboard.items():
            if "username" not in data:
                data["username"] = f"User {user_id}"
            if "score" not in data:
                data["score"] = 0
            if "total_answers" not in data:
                data["total_answers"] = 0
            if "correct_answers" not in data:
                data["correct_answers"] = 0
                
        logger.info(f"Loaded leaderboard from {LEADERBOARD_JSON_URL}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching leaderboard from {LEADERBOARD_JSON_URL}: {e}")
    except json.JSONDecodeError:
        logger.error(f"Error decoding leaderboard from {LEADERBOARD_JSON_URL}")
    except Exception as e:
        logger.error(f"Error loading leaderboard: {e}")

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

def load_english_notes():
    global english_notes
    try:
        response = requests.get(ENGLISH_NOTES_JSON_URL)
        response.raise_for_status()
        english_notes = response.json().get("notes", [])
        logger.info(f"Loaded {len(english_notes)} English notes from {ENGLISH_NOTES_JSON_URL}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching English notes from {ENGLISH_NOTES_JSON_URL}: {e}")
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from {ENGLISH_NOTES_JSON_URL}")
    except Exception as e:
        logger.error(f"Error loading English notes: {e}")

load_questions()
load_leaderboard()
load_weekly_questions()
load_english_notes()

async def send_question(context: ContextTypes.DEFAULT_TYPE):
    global current_question, answered_users, current_message_id, used_daily_questions
    answered_users = set()
    if not questions:
        logger.error("send_question: No questions available")
        return

    available_questions = [q for q in questions if q["id"] not in used_daily_questions]
    if not available_questions:
        logger.error("send_question: No available questions left to post")
        return

    current_question = available_questions[0]  # Pick the first available question
    used_daily_questions.add(current_question["id"])

    keyboard = [[InlineKeyboardButton(option, callback_data=f"answer_{option}")] for option in current_question.get("options", [])]
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

    if current_question is None:
        await query.answer("❌ No active question at the moment.", show_alert=True)
        return

    if user_id in answered_users:
        await query.answer("❌ You already answered this question.", show_alert=True)
        return

    answered_users.add(user_id)
    user_answer = query.data.replace("answer_", "").strip()
    correct_answer = current_question.get("correct_option", "").strip()

    logger.info(f"User answer: '{user_answer}'")
    logger.info(f"Correct answer: '{correct_answer}'")

    correct = user_answer == correct_answer

    if correct:
        await query.answer("✅ Correct!")
        if str(user_id) not in leaderboard:
            leaderboard[str(user_id)] = {"username": username, "score": 0, "total_answers": 0, "correct_answers": 0}
        leaderboard[str(user_id)]["score"] += 1
        
        # Check if correct_answers key exists before incrementing
        if "correct_answers" not in leaderboard[str(user_id)]:
            leaderboard[str(user_id)]["correct_answers"] = 0
        leaderboard[str(user_id)]["correct_answers"] += 1

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
        except Exception as e:
            logger.error(f"Failed to edit message: {e}")
    else:
        await query.answer("❌ Incorrect.", show_alert=True)

    # Check if total_answers key exists before incrementing
    if "total_answers" not in leaderboard[str(user_id)]:
        leaderboard[str(user_id)]["total_answers"] = 0
    leaderboard[str(user_id)]["total_answers"] += 1
    
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
    except Exception as e:
        logger.error(f"Error saving leaderboard to GitHub: {e}")

async def test_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID and update.effective_user.id != SECOND_OWNER:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    if not questions:
        await update.message.reply_text("❌ No questions loaded!")
        return
    
    # Ensure the current question is set properly
    global current_question, current_message_id, answered_users
    answered_users = set()
    current_question = random.choice(questions)
    
    try:
        keyboard = [[InlineKeyboardButton(option, callback_data=f"answer_{option}")] for option in current_question.get("options", [])]
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
            logger.info("test_question: message sent successfully")
        else:
            logger.info("test_question: message sending failed")

        await update.message.reply_text(f"✅ Test question sent in channel. Question: {current_question.get('question')}")
    except Exception as e:
        logger.error(f"test_question: Failed to send test question: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def heartbeat(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await context.bot.send_message(chat_id=OWNER_ID, text=f"💓 Heartbeat check - Bot is alive at {now}")
    await context.bot.send_message(chat_id=SECOND_OWNER, text=f"💓 Heartbeat check - Bot is alive at {now}")

async def reload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID and update.effective_user.id != SECOND_OWNER:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    await update.message.reply_text("🔄 Reloading the bot...")
    os.system("curl https://render.com/activate-service")

async def set_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID and update.effective_user.id != SECOND_OWNER:
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

# Weekly Test Functions
class WeeklyTest:
    def __init__(self):
        self.reset()
        
    def reset(self):
        self.questions = []
        self.current_question_index = 0
        self.participants = {}
        self.active = False
        self.poll_ids = {}
        self.poll_messages = {}
        self.channel_message_ids = []
        self.group_link = None

    def add_point(self, user_id, user_name):
        if user_id not in self.participants:
            self.participants[user_id] = {"name": user_name, "score": 0}
        self.participants[user_id]["score"] += 1

    def get_results(self):
        return sorted(
            self.participants.items(),
            key=lambda x: x[1]["score"],
            reverse=True
        )

weekly_test = WeeklyTest()

async def delete_channel_messages(context):
    """Delete all channel messages from this test"""
    try:
        for msg_id in weekly_test.channel_message_ids:
            try:
                await context.bot.delete_message(
                    chat_id=CHANNEL_ID,
                    message_id=msg_id
                )
            except Exception as e:
                logger.warning(f"Couldn't delete channel message {msg_id}: {e}")
        weekly_test.channel_message_ids = []
    except Exception as e:
        logger.error(f"Error deleting channel messages: {e}")

async def fetch_questions_from_url():
    """Fetch questions from external JSON URL"""
    try:
        if not WEEKLY_QUESTIONS_JSON_URL:
            logger.error("WEEKLY_QUESTIONS_JSON_URL not set")
            return []
            
        async with aiohttp.ClientSession() as session:
            async with session.get(WEEKLY_QUESTIONS_JSON_URL) as response:
                if response.status == 200:
                    text_content = await response.text()
                    try:
                        data = json.loads(text_content)
                        return data.get("questions", [])
                    except json.JSONDecodeError as e:
                        logger.error(f"JSON decode error: {e}")
                        return []
                else:
                    logger.error(f"Failed to fetch weekly questions: {response.status}")
                    return []
    except Exception as e:
        logger.error(f"Exception in fetch_questions_from_url: {e}")
        return []

async def start_weekly_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID and update.effective_user.id != SECOND_OWNER:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    if weekly_test.active:
        await update.message.reply_text("❌ A weekly test is already in progress.")
        return

    weekly_test.reset()
    weekly_test.questions = await fetch_questions_from_url()

    if not weekly_test.questions:
        await update.message.reply_text("❌ No weekly questions available!")
        return
    
    weekly_test.active = True
    await update.message.reply_text("✅ Weekly test started!")
    await send_next_weekly_question(context)

async def send_next_weekly_question(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not weekly_test.active or weekly_test.current_question_index >= len(weekly_test.questions):
        await end_weekly_test(context)
        return

    question = weekly_test.questions[weekly_test.current_question_index]
    weekly_test.current_question_index += 1

    keyboard = [[InlineKeyboardButton(option, callback_data=f"weekly_answer_{option}")] for option in question.get("options", [])]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=question.get("question"),
            reply_markup=reply_markup,
            disable_web_page_preview=True,
            disable_notification=False,
        )
        weekly_test.channel_message_ids.append(message.message_id)
    except Exception as e:
        logger.error(f"send_next_weekly_question: Failed to send question: {e}")

async def handle_weekly_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.first_name

    if not weekly_test.active:
        await query.answer("❌ No active weekly test.", show_alert=True)
        return

    question_index = weekly_test.current_question_index - 1
    question = weekly_test.questions[question_index]

    user_answer = query.data.replace("weekly_answer_", "").strip()
    correct_answer = question.get("correct_option", "").strip()

    if user_answer == correct_answer:
        await query.answer("✅ Correct!")
        weekly_test.add_point(user_id, username)
    else:
        await query.answer("❌ Incorrect.", show_alert=True)

    await send_next_weekly_question(context)

async def end_weekly_test(context: ContextTypes.DEFAULT_TYPE) -> None:
    weekly_test.active = False

    results = weekly_test.get_results()
    results_text = "🏆 Weekly Test Results 🏆\n\n"
    for rank, (user_id, data) in enumerate(results, start=1):
        results_text += f"{rank}. {data['name']}: {data['score']} points\n"

    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text=results_text)
    except Exception as e:
        logger.error(f"Failed to send results: {e}")

    await delete_channel_messages(context)

async def notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not english_notes:
        await update.message.reply_text("❌ No notes available.")
        return

    notes_text = "📚 English Notes 📚\n\n"
    for note in english_notes:
        notes_text += f"- {note}\n"

    await update.message.reply_text(notes_text)

def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()

    job_queue = application.job_queue

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reload", reload_command))
    application.add_handler(CommandHandler("setwebhook", set_webhook))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CommandHandler("testquestion", test_question))
    application.add_handler(CommandHandler("notes", notes))
    application.add_handler(CommandHandler("startweeklytest", start_weekly_test))

    # Callback query handler
    application.add_handler(CallbackQueryHandler(handle_answer, pattern="^answer_"))
    application.add_handler(CallbackQueryHandler(handle_weekly_answer, pattern="^weekly_answer_"))

    # Poll answer handler
    application.add_handler(PollAnswerHandler(receive_poll_answer))

    # Daily question job
    job_queue.run_daily(send_question, time=datetime.time(hour=8, minute=0, second=0, tzinfo=pytz.timezone('Asia/Gaza')), name="morning_question")
    job_queue.run_daily(send_question, time=datetime.time(hour=12, minute=30, second=0, tzinfo=pytz.timezone('Asia/Gaza')), name="midday_question")
    job_queue.run_daily(send_question, time=datetime.time(hour=16, minute=20, second=0, tzinfo=pytz.timezone('Asia/Gaza')), name="afternoon_question")

    # Weekly test job
    job_queue.run_daily(start_weekly_test, time=datetime.time(hour=18, minute=0, second=0, tzinfo=pytz.timezone('Asia/Gaza')), days=(5,), name="weekly_test")

    # Heartbeat check every hour
    job_queue.run_repeating(
        heartbeat,
        interval=3600,  # 1 hour in seconds
        first=10,  # Initial delay to let the bot start
        name="heartbeat_check"
    )

    application.run_polling()

if __name__ == "__main__":
    main()
