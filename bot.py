import os
import logging
import random
import json
import requests
import time
import asyncio
import pytz
import base64
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, JobQueue, PollAnswerHandler

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
logger.info(f"BOT_TOKEN: {BOT_TOKEN}")

CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))
DISCUSSION_GROUP_ID = int(os.getenv("DISCUSSION_GROUP_ID", "0"))
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
answered_users = set()

# Weekly test class
class WeeklyTest:
    def __init__(self):
        self.questions = []
        self.current_question_index = 0
        self.participants = {}  # user_id -> {"name": name, "score": score}
        self.active = False
        self.poll_ids = {}  # question_index -> poll_id
        self.poll_messages = {}  # question_index -> poll_message_id (in discussion group)

    def reset(self):
        self.questions = []
        self.current_question_index = 0
        self.participants = {}
        self.active = False
        self.poll_ids = {}
        self.poll_messages = {}

    def add_point(self, user_id, user_name):
        if user_id not in self.participants:
            self.participants[user_id] = {"name": user_name, "score": 0}
        self.participants[user_id]["score"] += 1

    def get_results(self):
        sorted_participants = sorted(
            self.participants.items(),
            key=lambda x: x[1]["score"],
            reverse=True
        )
        return sorted_participants

# Global test instance
weekly_test = WeeklyTest()

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

def save_weekly_leaderboard():
    try:
        github_token = os.getenv("GITHUB_TOKEN")
        repo_owner = "TegerPython"  # Replace with your GitHub username
        repo_name = "bot_data"  # Replace with your repository name
        file_path = "weekly_leaderboard.json"

        # Get the current file's SHA for updating
        get_file_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{file_path}"
        headers = {"Authorization": f"token {github_token}", "Accept": "application/vnd.github.v3+json"}
        get_response = requests.get(get_file_url, headers=headers)
        get_response.raise_for_status()
        sha = get_response.json()["sha"]

        # Convert weekly_test participants to weekly_leaderboard format
        global weekly_test, weekly_leaderboard
        
        for user_id, data in weekly_test.participants.items():
            if str(user_id) not in weekly_leaderboard:
                weekly_leaderboard[str(user_id)] = {"username": data["name"], "score": 0}
            weekly_leaderboard[str(user_id)]["score"] += data["score"]

        # Update the file
        content = json.dumps(weekly_leaderboard, indent=4).encode("utf-8")
        encoded_content = base64.b64encode(content).decode("utf-8")

        update_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{file_path}"
        data = {
            "message": "Update weekly leaderboard",
            "content": encoded_content,
            "sha": sha,
            "branch": "main",  # Or your branch name
        }
        update_response = requests.put(update_url, headers=headers, json=data)
        update_response.raise_for_status()

        logger.info("Weekly leaderboard saved successfully to GitHub.")
    except Exception as e:
        logger.error(f"Error saving weekly leaderboard to GitHub: {e}")

async def test_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    await send_question(context)
    await update.message.reply_text("✅ Test question sent.")

async def heartbeat(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await context.bot.send_message(chat_id=OWNER_ID, text=f"💓 Heartbeat check - Bot is alive at {now}")

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

# Weekly Test Functions
async def send_weekly_test_question(context, question_index):
    """Send weekly test questions to both channel and discussion group"""
    global weekly_test
    
    if question_index >= len(weekly_test.questions):
        # All questions sent, schedule leaderboard post
        logger.info("All weekly test questions sent, scheduling leaderboard results")
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_weekly_leaderboard_results(ctx)),
            60  # Wait 1 minute after the last question
        )
        return
    
    question = weekly_test.questions[question_index]
    weekly_test.current_question_index = question_index
    
    try:
        # 1. Send question to channel (anonymous poll)
        channel_message = await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question=f"❓ Weekly Test Question {question_index + 1}: {question['question']}",
            options=question["options"],
            is_anonymous=True,  # Must be true for channels
            type=Poll.QUIZ,
            correct_option_id=question["correct_option"],
            explanation=f"The correct answer is: {question['options'][question['correct_option']]}",
            open_period=15  # Close after 15 seconds
        )
        
        # 2. Send the same poll to discussion group (non-anonymous)
        group_message = await context.bot.send_poll(
            chat_id=DISCUSSION_GROUP_ID,
            question=f"❓ Weekly Test Question {question_index + 1}: {question['question']}",
            options=question["options"],
            is_anonymous=False,  # Non-anonymous to track users
            protect_content=True,  # Prevent forwarding
            allows_multiple_answers=False
        )
        
        # Store the poll information
        weekly_test.poll_ids[question_index] = group_message.poll.id
        weekly_test.poll_messages[question_index] = group_message.message_id
        
        # Send announcement to discussion group linking to the question
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text=f"⚠️ Answer Weekly Test Question {question_index + 1} in the poll above. You have 15 seconds! Answers will be tracked for the leaderboard."
        )
        
        logger.info(f"Weekly Test Question {question_index + 1} sent to channel and discussion group")
        logger.info(f"Poll ID for question {question_index + 1}: {group_message.poll.id}")
        
        # Schedule next question after delay
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_weekly_test_question(ctx, question_index + 1)),
            20  # Send next question after 20 seconds
        )
        
        # Schedule poll closure in discussion group
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(stop_poll_and_check_answers(ctx, question_index)),
            15  # Close poll after 15 seconds
        )
    except Exception as e:
        logger.error(f"Error sending weekly test question {question_index + 1}: {e}")

async def stop_poll_and_check_answers(context, question_index):
    """Stop the poll in discussion group and record correct answers"""
    global weekly_test
    
    if question_index not in weekly_test.poll_messages:
        return
    
    question = weekly_test.questions[question_index]
    correct_option = question["correct_option"]
    
    try:
        # Stop the poll
        poll = await context.bot.stop_poll(
            chat_id=DISCUSSION_GROUP_ID,
            message_id=weekly_test.poll_messages[question_index]
        )
        
        # Send correct answer message
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text=f"✅ Correct answer: *{question['options'][correct_option]}*",
            parse_mode="Markdown"
        )
        
        logger.info(f"Poll for weekly test question {question_index + 1} stopped")
    except Exception as e:
        logger.error(f"Error stopping poll for weekly test question {question_index + 1}: {e}")

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle poll answers from discussion group members"""
    global weekly_test
    
    try:
        poll_answer = update.poll_answer
        poll_id = poll_answer.poll_id
        
        # Debug logging
        logger.info(f"Received poll answer for poll ID: {poll_id}")
        logger.info(f"Current active poll IDs: {weekly_test.poll_ids}")
        
        if not weekly_test.active:
            logger.info("Weekly test not active, ignoring poll answer")
            return
        
        # Find which question this poll belongs to
        question_index = None
        for idx, p_id in weekly_test.poll_ids.items():
            if p_id == poll_id:
                question_index = idx
                break
        
        if question_index is None:
            logger.warning(f"Poll ID {poll_id} not found in tracked polls")
            return
        
        # Get user information
        user_id = poll_answer.user.id
        user_name = poll_answer.user.full_name if hasattr(poll_answer.user, 'full_name') else f"User {user_id}"
        
        logger.info(f"Processing answer from user {user_name} (ID: {user_id})")
        
        # Check if the user answered correctly
        if poll_answer.option_ids:
            selected_option = poll_answer.option_ids[0]
            correct_option = weekly_test.questions[question_index]["correct_option"]
            
            logger.info(f"User selected option {selected_option}, correct is {correct_option}")
            
            if selected_option == correct_option:
                weekly_test.add_point(user_id, user_name)
                logger.info(f"User {user_name} answered weekly test question {question_index + 1} correctly")
    except Exception as e:
        logger.error(f"Error handling poll answer: {e}")

async def send_weekly_leaderboard_results(context):
    """Send the weekly test leaderboard results in a visually appealing format"""
    global weekly_test, weekly_leaderboard
    
    if not weekly_test.active:
        return
    
    results = weekly_test.get_results()
    logger.info(f"Preparing weekly test leaderboard with {len(results)} participants")
    
    # Create the leaderboard message
    message = "🏆 *WEEKLY TEST RESULTS* 🏆\n\n"
    
    # Display the podium (top 3) 
    if len(results) >= 3:
        # Second place (silver)
        silver_id, silver_data = results[1]
        silver_name = silver_data["name"]
        silver_score = silver_data["score"]
        
        # First place (gold)
        gold_id, gold_data = results[0]
        gold_name = gold_data["name"]
        gold_score = gold_data["score"]
        
        # Third place (bronze)
        bronze_id, bronze_data = results[2]
        bronze_name = bronze_data["name"]
        bronze_score = bronze_data["score"]
        
        # Create the podium display
        message += "      🥇\n"
        message += f"      {gold_name}\n"
        message += f"      {gold_score} pts\n"
        message += "  🥈         🥉\n"
        message += f"  {silver_name}    {bronze_name}\n"
        message += f"  {silver_score} pts    {bronze_score} pts\n\n"
        
        # Other participants
        if len(results) > 3:
            message += "*Other participants:*\n"
            for i, (user_id, data) in enumerate(results[3:], start=4):
                message += f"{i}. {data['name']} - {data['score']} pts\n"
    
    # If we have fewer than 3 participants
    elif len(results) > 0:
        for i, (user_id, data) in enumerate(results, start=1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else ""
            message += f"{medal} {i}. {data['name']} - {data['score']} pts\n"
    else:
        message += "No participants this week."
    
    try:
        # Send results to both channel and discussion group
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=message,
            parse_mode="Markdown"
        )
        
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text=message,
            parse_mode="Markdown"
        )
        
        logger.info("Weekly test leaderboard results sent successfully")
        
        # Update weekly leaderboard and main leaderboard
        for user_id, data in weekly_test.participants.items():
            # Update weekly leaderboard
            if str(user_id) not in weekly_leaderboard:
                weekly_leaderboard[str(user_id)] = {"username": data["name"], "score": 0}
            weekly_leaderboard[str(user_id)]["score"] += data["score"]
            
            # Update main leaderboard
            if str(user_id) not in leaderboard:
                leaderboard[str(user_id)] = {"username": data["name"], "score": 0}
            leaderboard[str(user_id)]["score"] += data["score"]
        
        # Save both leaderboards
        save_leaderboard()
        save_weekly_leaderboard()
        
        # Reset the test after sending results
        weekly_test.active = False
    except Exception as e:
        logger.error(f"Error sending weekly test leaderboard results: {e}")

async def weekly_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command handler for /weeklytest"""
    global weekly_test, weekly_questions
    
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Not authorized")
        return
    
    try:
        # Verify CHANNEL_ID and DISCUSSION_GROUP_ID are set
        if CHANNEL_ID == 0 or DISCUSSION_GROUP_ID == 0:
            await update.message.reply_text("❌ CHANNEL_ID or DISCUSSION_GROUP_ID not set in environment variables.")
            logger.error("Required environment variables not set")
            return
        
        # Reload weekly questions to ensure we have the latest
        load_weekly_questions()
        
        # Reset and prepare the test
        weekly_test.reset()
        weekly_test.questions = weekly_questions
        weekly_test.active = True
        
        # Start the sequence with the first question
        await update.message.reply_text("Starting weekly test...")
        
        # Send announcement to discussion group
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text="🎮 *WEEKLY TEST STARTING* 🎮\n\nAnswer the questions that will appear here to participate in the leaderboard!",
            parse_mode="Markdown"
        )
        
        # Send first question
        await send_weekly_test_question(context, 0)
    
    except Exception as e:
        logger.error(f"Error in weekly test command: {e}")
        await update.message.reply_text(f"Failed to start weekly test: {str(e)}")

async def custom_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command handler for /customtest with specific questions"""
    global weekly_test
    
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Not authorized")
        return
    
    try:
        # Custom quiz questions (example)
        custom_questions = [
            {
                "question": "What is the largest planet in our solar system?",
                "options": ["Saturn", "Jupiter", "Neptune", "Uranus"],
                "correct_option": 1
            },
            {
                "question": "Which element has the chemical symbol 'Au'?",
                "options": ["Silver", "Aluminum", "Gold", "Copper"],
                "correct_option": 2
            },
            {
                "question": "Who wrote 'Romeo and Juliet'?",
                "options": ["Charles Dickens", "William Shakespeare", "Jane Austen", "Mark Twain"],
                "correct_option": 1
            }
        ]
        
        # Reset and prepare the test
        weekly_test.reset()
        weekly_test.questions = custom_questions
        weekly_test.active = True
        
        # Start the sequence with the first question
        await update.message.reply_text("Starting custom test...")
        
        # Send announcement to discussion group
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text="🎮 *CUSTOM TEST STARTING* 🎮\n\nAnswer the questions that will appear here to participate in the leaderboard!",
            parse_mode="Markdown"
        )
        
        # Send first question
        await send_weekly_test_question(context, 0)
    
    except Exception as e:
        logger.error(f"Error in custom test command: {e}")
        await update.message.reply_text(f"Failed to start custom test: {str(e)}")

def get_utc_time(hour, minute, timezone_str):
    tz = pytz.timezone(timezone_str)
    local_time = datetime.now(tz).replace(hour=hour, minute=minute, second=0, microsecond=0)
    utc_time = local_time.astimezone(pytz.utc).time()
    return utc_time

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    job_queue = application.job_queue

    # Schedule daily questions
    job_queue.run_daily(send_question, get_utc_time(8, 0, "Asia/Gaza"))
    job_queue.run_daily(send_question, get_utc_time(12, 30, "Asia/Gaza"), name="second_question")
    job_queue.run_daily(send_question, get_utc_time(18, 0, "Asia/Gaza"))

    # Schedule weekly test
    friday = 4  # Monday is 0, Tuesday is 1, ..., Friday is 4
    now = datetime.now(pytz.utc)
    target_time = get_utc_time(18, 0, "Asia/Gaza")
    
    job_queue.run_daily(
        weekly_test_command,
        time=target_time,
        days=(friday,),
        name="weekly_test"
    )

    # Heartbeat check
    job_queue.run_repeating(heartbeat, interval=60)

    # Command handlers
    application.add_handler(CommandHandler("test", test_question))
    application.add_handler(CallbackQueryHandler(handle_answer))
    application.add_handler(CommandHandler("setwebhook", set_webhook))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CommandHandler("weeklyleaderboard", weekly_leaderboard_command))
    application.add_handler(CommandHandler("weeklytest", weekly_test_command))
    application.add_handler(CommandHandler("customtest", custom_test_command))
    application.add_handler(PollAnswerHandler(handle_poll_answer))

    # Error handler
    application.add_error_handler(lambda update, context: 
                               logger.error(f"Error: {context.error}", exc_info=context.error))

    # Start the bot
    port = int(os.environ.get)"
