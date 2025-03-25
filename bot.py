import os
import logging
import random
import json
import requests
import time
import aiohttp
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, JobQueue, PollAnswerHandler, filters
import pytz
import base64

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
QUESTIONS_JSON_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")
WEEKLY_QUESTIONS_JSON_URL = os.getenv("WEEKLY_QUESTIONS_JSON_URL")
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "")

# Constants
QUESTION_DURATION = 30  # Default duration (seconds)
NEXT_QUESTION_DELAY = 2  # seconds between questions
MAX_QUESTIONS = 10  # Maximum questions per test

# Global variables
questions = []
leaderboard = {}
current_question = None
current_message_id = None
user_answers = {}
answered_users = set()

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

# Load Questions from URL (for daily quiz)
def load_questions():
    global questions
    try:
        response = requests.get(QUESTIONS_JSON_URL)
        response.raise_for_status()
        questions = response.json()
        logger.info(f"Loaded {len(questions)} daily questions")
    except Exception as e:
        logger.error(f"Error loading daily questions: {e}")

# Load Leaderboard
def load_leaderboard():
    global leaderboard
    try:
        response = requests.get(LEADERBOARD_JSON_URL)
        response.raise_for_status()
        leaderboard = response.json()
        logger.info("Leaderboard loaded")
    except Exception as e:
        logger.error(f"Error loading leaderboard: {e}")

load_questions()
load_leaderboard()

async def delete_channel_messages(context):
    """Delete all weekly test channel messages"""
    try:
        for msg_id in weekly_test.channel_message_ids:
            await context.bot.delete_message(CHANNEL_ID, msg_id)
        weekly_test.channel_message_ids = []
    except Exception as e:
        logger.error(f"Error deleting messages: {e}")

async def fetch_questions_from_url():
    """Fetch weekly questions from URL"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(WEEKLY_QUESTIONS_JSON_URL) as resp:
                if resp.status == 200:
                    return (await resp.json())[:MAX_QUESTIONS]
                logger.error(f"Failed to fetch questions: HTTP {resp.status}")
    except Exception as e:
        logger.error(f"Error fetching weekly questions: {e}")
    return []

async def start_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start weekly test (owner only)"""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Unauthorized")
        return

    try:
        questions = await fetch_questions_from_url()
        if not questions:
            await update.message.reply_text("❌ No questions available")
            return

        weekly_test.reset()
        weekly_test.questions = questions
        weekly_test.active = True

        # Get group link
        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        weekly_test.group_link = chat.invite_link or (await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)).invite_link

        # Send channel announcement
        msg = await context.bot.send_message(
            CHANNEL_ID,
            text="📢 Weekly Test Starting Now!\nJoin the discussion:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Join", url=weekly_test.group_link)]])
        )
        weekly_test.channel_message_ids.append(msg.message_id)

        await send_weekly_question(context, 0)
        await update.message.reply_text("🚀 Weekly test started")
    except Exception as e:
        logger.error(f"Error starting test: {e}")
        await update.message.reply_text(f"❌ Error: {e}")

async def send_weekly_question(context: ContextTypes.DEFAULT_TYPE, question_index: int):
    """Send a weekly question"""
    if not weekly_test.active or question_index >= len(weekly_test.questions):
        await send_leaderboard_results(context)
        return

    question = weekly_test.questions[question_index]
    weekly_test.current_question_index = question_index

    try:
        # Restrict group during question
        await context.bot.set_chat_permissions(DISCUSSION_GROUP_ID, permissions={"can_send_messages": False})

        # Send poll to group
        poll_msg = await context.bot.send_poll(
            DISCUSSION_GROUP_ID,
            question=f"Question {question_index + 1}: {question['question']}",
            options=question["options"],
            is_anonymous=False,
            type=Poll.QUIZ,
            correct_option_id=question["correct_option"],
            open_period=QUESTION_DURATION
        )
        weekly_test.poll_ids[question_index] = poll_msg.poll.id
        weekly_test.poll_messages[question_index] = poll_msg.message_id

        # Send channel alert
        channel_msg = await context.bot.send_message(
            CHANNEL_ID,
            text=f"🎯 Question {question_index + 1} LIVE!\n{QUESTION_DURATION}s remaining!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Join", url=weekly_test.group_link)]])
        )
        weekly_test.channel_message_ids.append(channel_msg.message_id)

        # Schedule next question or results
        if question_index + 1 < len(weekly_test.questions):
            context.job_queue.run_once(
                lambda ctx: asyncio.create_task(send_weekly_question(ctx, question_index + 1)),
                QUESTION_DURATION + NEXT_QUESTION_DELAY
            )
        else:
            context.job_queue.run_once(
                lambda ctx: asyncio.create_task(send_leaderboard_results(ctx)),
                QUESTION_DURATION + 5
            )

        # Schedule answer reveal
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(reveal_answer(ctx, question_index)),
            QUESTION_DURATION
        )
    except Exception as e:
        logger.error(f"Error sending question {question_index}: {e}")

async def reveal_answer(context: ContextTypes.DEFAULT_TYPE, question_index: int):
    """Reveal correct answer in group"""
    try:
        question = weekly_test.questions[question_index]
        await context.bot.send_message(
            DISCUSSION_GROUP_ID,
            text=f"✅ Correct: {question['options'][question['correct_option']]}"
        )
        # Re-enable messaging after last question
        if question_index + 1 >= len(weekly_test.questions):
            await context.bot.set_chat_permissions(DISCUSSION_GROUP_ID, permissions={"can_send_messages": True})
    except Exception as e:
        logger.error(f"Error revealing answer: {e}")

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle poll answers for weekly test"""
    answer = update.poll_answer
    if not weekly_test.active:
        return

    try:
        # Find which question this poll belongs to
        question_index = next(
            (i for i, poll_id in weekly_test.poll_ids.items() if poll_id == answer.poll_id),
            None
        )
        if question_index is None:
            return

        # Check if answer is correct
        question = weekly_test.questions[question_index]
        if answer.option_ids and answer.option_ids[0] == question["correct_option"]:
            user = answer.user
            weekly_test.add_point(user.id, user.full_name)
    except Exception as e:
        logger.error(f"Error handling poll answer: {e}")

async def send_leaderboard_results(context: ContextTypes.DEFAULT_TYPE):
    """Send final leaderboard to channel"""
    if not weekly_test.active:
        return

    results = weekly_test.get_results()
    leaderboard_text = "🏆 Final Results 🏆\n\n"
    for rank, (user_id, data) in enumerate(results, 1):
        leaderboard_text += f"{rank}. {data['name']}: {data['score']}pts\n"

    try:
        await delete_channel_messages(context)
        msg = await context.bot.send_message(
            CHANNEL_ID,
            text=leaderboard_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Discussion", url=weekly_test.group_link)]])
        )
        weekly_test.channel_message_ids.append(msg.message_id)
        weekly_test.active = False
    except Exception as e:
        logger.error(f"Error sending leaderboard: {e}")

async def schedule_weekly_test(context: ContextTypes.DEFAULT_TYPE):
    """Schedule weekly test every Friday 6PM Gaza time"""
    try:
        gaza_tz = pytz.timezone("Asia/Gaza")
        now = datetime.now(gaza_tz)
        
        days_until_friday = (4 - now.weekday()) % 7
        if days_until_friday == 0 and now.hour >= 18:
            days_until_friday = 7
            
        next_friday = now + timedelta(days=days_until_friday)
        next_friday = next_friday.replace(hour=18, minute=0, second=0)
        
        # Schedule 30-minute countdown
        teaser_time = next_friday - timedelta(minutes=30)
        seconds_until_teaser = (teaser_time - now).total_seconds()
        
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_weekly_teaser(ctx)),
            max(0, seconds_until_teaser)
        )
        logger.info(f"Scheduled weekly test for {next_friday}")
    except Exception as e:
        logger.error(f"Error scheduling: {e}")

async def send_weekly_teaser(context: ContextTypes.DEFAULT_TYPE):
    """Send countdown teaser messages"""
    try:
        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        invite_link = chat.invite_link or (await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)).invite_link
        
        msg = await context.bot.send_message(
            CHANNEL_ID,
            text="🕒 Weekly Test starts in 30 minutes!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Join", url=invite_link)]])
        )
        weekly_test.channel_message_ids.append(msg.message_id)
        
        # Schedule test start
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(start_test_command(ctx)),
            1800  # 30 minutes
        )
    except Exception as e:
        logger.error(f"Error sending teaser: {e}")

# ... [Keep existing daily quiz functions unchanged] ...

async def test_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test command for weekly quiz"""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Unauthorized")
        return
    await start_test_command(update, context)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Daily Quiz Handlers
    application.add_handler(CommandHandler("test", test_question))
    application.add_handler(CallbackQueryHandler(handle_answer))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    
    # Weekly Quiz Handlers
    application.add_handler(CommandHandler("weeklytest", test_weekly, filters=filters.ChatType.PRIVATE))
    application.add_handler(PollAnswerHandler(handle_poll_answer))
    
    # Scheduling
    job_queue = application.job_queue
    job_queue.run_daily(send_question, get_utc_time(8, 0, "Asia/Gaza"))
    job_queue.run_daily(send_question, get_utc_time(12, 30, "Asia/Gaza"), name="second_question")
    job_queue.run_daily(send_question, get_utc_time(18, 0, "Asia/Gaza"))
    job_queue.run_once(schedule_weekly_test, 5)  # Initial schedule
    
    # Webhook setup
    port = int(os.getenv("PORT", 5000))
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
    )

if __name__ == "__main__":
    main()
