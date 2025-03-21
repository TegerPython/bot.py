import os
import logging
import asyncio
from telegram import Update, Poll, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, PollAnswerHandler, ContextTypes

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
GROUP_ID = int(os.getenv("GROUP_ID", "0"))  # Add a group ID environment variable
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8443"))

# Test data structure
class WeeklyTest:
    def __init__(self):
        self.questions = []
        self.current_question_index = 0
        self.participants = {}  # user_id -> {"name": name, "score": score}
        self.active = False
        self.poll_ids = {}  # Maps poll_id to question_index

    def reset(self):
        self.questions = []
        self.current_question_index = 0
        self.participants = {}
        self.active = False
        self.poll_ids = {}

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

# Sample test questions
sample_questions = [
    {
        "question": "What is the capital of France?",
        "options": ["Paris", "London", "Berlin", "Madrid"],
        "correct_option": 0
    },
    {
        "question": "Which planet is closest to the sun?",
        "options": ["Mercury", "Venus", "Earth", "Mars"],
        "correct_option": 0
    },
    {
        "question": "What is 2+2?",
        "options": ["3", "4", "5", "6"],
        "correct_option": 1
    }
]

async def send_channel_announcement(context, question_index):
    """Send an announcement to the channel with a link to the poll in the group"""
    global weekly_test
    
    if question_index >= len(weekly_test.questions):
        # All questions done
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_leaderboard_results(ctx)),
            60  # Wait 1 minute after the last question
        )
        return
    
    question = weekly_test.questions[question_index]
    weekly_test.current_question_index = question_index
    
    try:
        # First, send the poll to the group where non-anonymous polls work
        poll_message = await context.bot.send_poll(
            chat_id=GROUP_ID,
            question=question["question"],
            options=question["options"],
            type=Poll.QUIZ,
            correct_option_id=question["correct_option"],
            open_period=10,  # 10 seconds
            is_anonymous=False  # Non-anonymous poll in the group
        )
        
        # Store the poll ID for later reference
        weekly_test.poll_ids[poll_message.poll.id] = question_index
        
        # Create a deep link to the poll in the group
        group_username = await get_chat_username(context.bot, GROUP_ID)
        if group_username:
            poll_link = f"https://t.me/{group_username}/{poll_message.message_id}"
            
            # Send announcement to the channel with a link to participate
            keyboard = [[InlineKeyboardButton("Answer this question", url=poll_link)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=CHANNEL_ID
