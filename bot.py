import os
import logging
import random
import json
import requests
import time
import asyncio
import base64
import pytz
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, PollAnswerHandler, JobQueue, filters

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0"))
DISCUSSION_GROUP_ID = int(os.getenv("DISCUSSION_GROUP_ID", "0"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8443"))
WEEKLY_QUESTIONS_JSON_URL = os.getenv("WEEKLY_QUESTIONS_JSON_URL")
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "")

# Global variables for daily quiz
questions = []
leaderboard = {}
current_question = None
current_message_id = None
user_answers = {}
answered_users = set()

# Global variables for weekly quiz
weekly_questions = []
weekly_question_index = 0
weekly_poll_message_ids = []
weekly_user_answers = {}

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

# Load Questions and Leaderboard
def load_questions():
    global questions, weekly_questions, leaderboard
    try:
        # Load daily questions
        response = requests.get(QUESTIONS_JSON_URL)
        response.raise_for_status()
        questions = response.json()
        logger.info(f"Loaded {len(questions)} questions from {QUESTIONS_JSON_URL}")

        # Load weekly questions
        weekly_response = requests.get(WEEKLY_QUESTIONS_JSON_URL)
        weekly_response.raise_for_status()
        weekly_questions = weekly_response.json()
        logger.info(f"Loaded {len(weekly_questions)} weekly questions from {WEEKLY_QUESTIONS_JSON_URL}")

        # Load leaderboard
        leaderboard_response = requests.get(LEADERBOARD_JSON_URL)
        leaderboard_response.raise_for_status()
        leaderboard = leaderboard_response.json()
        logger.info("Loaded leaderboard successfully")
    except Exception as e:
        logger.error(f"Error loading data: {e}")

# Daily Quiz Functions
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

# Weekly Quiz Functions
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

async def send_weekly_question(context, question_index):
    """Send weekly question to group and announcement to channel"""
    global weekly_test
    
    if not weekly_test.active or question_index >= len(weekly_test.questions):
        if weekly_test.active:
            await send_leaderboard_results(context)
        return

    question = weekly_test.questions[question_index]
    weekly_test.current_question_index = question_index
    
    try:
        # Send poll to group
        group_message = await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question=f"❓ Weekly Question {question_index + 1}: {question['question']}",
            options=question["options"],
            type=Poll.QUIZ,
            correct_option_id=question["correct_option"],
            open_period=30  # 30 seconds per question
        )
        
        # Store poll info
        weekly_test.poll_ids[question_index] = group_message.poll.id
        weekly_test.poll_messages[question_index] = group_message.message_id
        weekly_test.channel_message_ids.append(group_message.message_id)
        
        # Schedule next question or results
        if question_index + 1 < min(len(weekly_test.questions), 10):
            context.job_queue.run_once(
                lambda ctx: asyncio.create_task(send_weekly_question(ctx, question_index + 1)),
                30, 
                name="next_weekly_question"
            )
        else:
            context.job_queue.run_once(
                lambda ctx: asyncio.create_task(send_leaderboard_results(ctx)),
                32, 
                name="weekly_leaderboard"
            )
        
    except Exception as e:
        logger.error(f"Error sending weekly question {question_index + 1}: {e}")

async def send_leaderboard_results(context):
    """Send final leaderboard results"""
    global weekly_test
    
    if not weekly_test.active:
        return
        
    results = weekly_test.get_results()
    
    # Format leaderboard message
    message = "🏆 *Weekly Quiz Results* 🏆\n\n"
    if results:
        for i, (user_id, data) in enumerate(results, start=1):
            if i == 1:
                message += f"🥇 *{data['name']}* - {data['score']} pts\n"
            elif i == 2:
                message += f"🥈 *{data['name']}* - {data['score']} pts\n"
            elif i == 3:
                message += f"🥉 *{data['name']}* - {data['score']} pts\n"
            else:
                message += f"{i}. {data['name']} - {data['score']} pts\n"
    else:
        message += "No participants this week."
    
    try:
        # Delete previous channel messages
        await delete_channel_messages(context)
        
        # Send final results
        channel_message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=message,
            parse_mode="Markdown"
        )
        weekly_test.channel_message_ids.append(channel_message.message_id)
        
        weekly_test.active = False
    except Exception as e:
        logger.error(f"Error sending leaderboard: {e}")

async def start_weekly_test(context):
    """Start the weekly quiz"""
    try:
        questions = weekly_questions[:10]  # Take first 10 questions
        if not questions:
            logger.error("No weekly questions available")
            return
            
        weekly_test.reset()
        weekly_test.questions = questions
        weekly_test.active = True
        
        # Send quiz start message
        channel_message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="🚀 *Weekly Quiz Starts Now!*\n"
                 "Get ready for the challenge!",
            parse_mode="Markdown"
        )
        weekly_test.channel_message_ids.append(channel_message.message_id)
        
        # Start first question
        await send_weekly_question(context, 0)
        
    except Exception as e:
        logger.error(f"Weekly quiz start error: {e}")

async def handle_weekly_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle weekly poll answers"""
    global weekly_test
    
    try:
        if not weekly_test.active:
            return
            
        poll_answer = update.poll_answer
        poll_id = poll_answer.poll_id
        
        question_index = next(
            (idx for idx, p_id in weekly_test.poll_ids.items() if p_id == poll_id),
            None
        )
        if question_index is None:
            return
            
        if poll_answer.option_ids and poll_answer.option_ids[0] == weekly_test.questions[question_index]["correct_option"]:
            user = poll_answer.user
            user_name = user.full_name or user.username or f"User {user.id}"
            weekly_test.add_point(user.id, user_name)
            
    except Exception as e:
        logger.error(f"Error handling weekly poll answer: {e}")

async def schedule_weekly_test(context):
    """Schedule weekly test for Friday 6 PM Gaza time"""
    try:
        gaza_tz = pytz.timezone('Asia/Gaza')
        now = datetime.now(gaza_tz)
        
        # Calculate next Friday at 6 PM
        days_until_friday = (4 - now.weekday()) % 7
        if days_until_friday == 0 and now.hour >= 18:
            days_until_friday = 7
            
        next_friday = now + timedelta(days=days_until_friday)
        next_friday = next_friday.replace(hour=18, minute=0, second=0, microsecond=0)
        
        next_friday_utc = next_friday.astimezone(pytz.utc)
        
        context.job_queue.run_once(
            start_weekly_test,
            (next_friday_utc - datetime.now(pytz.utc)).total_seconds(),
            name="start_weekly_test"
        )
        
        logger.info(f"Scheduled next weekly test for {next_friday}")
        
    except Exception as e:
        logger.error(f"Error scheduling weekly test: {e}")

# Helper Functions
def save_leaderboard():
    try:
        github_token = os.getenv("GITHUB_TOKEN")
        repo_owner = "TegerPython"
        repo_name = "bot_data"
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
            "branch": "main",
        }
        update_response = requests.put(update_url, headers=headers, json=data)
        update_response.raise_for_status()

        logger.info("Leaderboard saved successfully to GitHub.")
    except Exception as e:
        logger.error(f"Error saving leaderboard to GitHub: {e}")

async def test_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual trigger for weekly test (for owner)"""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    await start_weekly_test(context)
    await update.message.reply_text("✅ Weekly test triggered.")

async def heartbeat(context: ContextTypes.DEFAULT_TYPE):
    """Send periodic heartbeat to owner"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await context.bot.send_message(chat_id=OWNER_ID, text=f"💓 Heartbeat check - Bot is alive at {now}")

def get_utc_time(hour, minute, timezone_str):
    """Convert local time to UTC"""
    tz = pytz.timezone(timezone_str)
    local_time = datetime.now(tz).replace(hour=hour, minute=minute, second=0, microsecond=0)
    utc_time = local_time.astimezone(pytz.utc).time()
    return utc_time

def main():
    # Load initial data
    load_questions()

    application = Application.builder().token(BOT_TOKEN).build()
    job_queue = application.job_queue

    # Daily question schedule
    job_queue.run_daily(send_question, get_utc_time(8, 0, "Asia/Gaza"))
    job_queue.run_daily(send_question, get_utc_time(12, 30, "Asia/Gaza"), name="second_question")
    job_queue.run_daily(send_question, get_utc_time(18, 0, "Asia/Gaza"))

    # Weekly test scheduling
    friday = 4  # Monday is 0, Tuesday is 1, ..., Friday is 4
    context = ContextTypes.DEFAULT_TYPE
    job_queue.run_once(
        lambda ctx: asyncio.create_task(schedule_weekly_test(ctx)),
        5,  # Initial delay
        name="initial_weekly_schedule"
    )

    # Heartbeat
    job_queue.run_repeating(heartbeat, interval=60)

    # Handlers
    application.add_handler(CommandHandler("test", test_weekly))
    application.add_handler(CallbackQueryHandler(handle_answer))
    application.add_handler(CommandHandler("testweekly", test_weekly))
    application.add_handler(PollAnswerHandler(handle_weekly_poll_answer))

    # Start bot
    port = int(os.environ.get("PORT", 5000))
    if WEBHOOK_URL:
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
            drop_pending_updates=True
        )
    else:
        application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
