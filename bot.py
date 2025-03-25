import os
import logging
import asyncio
import json
import random
import aiohttp
import pytz
import base64
import requests
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, PollAnswerHandler, filters

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0"))
DISCUSSION_GROUP_ID = int(os.getenv("DISCUSSION_GROUP_ID", "0"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8443"))

# JSON URLs
DAILY_QUESTIONS_JSON_URL = os.getenv("DAILY_QUESTIONS_JSON_URL")
WEEKLY_QUESTIONS_JSON_URL = os.getenv("WEEKLY_QUESTIONS_JSON_URL")
LEADERBOARD_JSON_URL = os.getenv("LEADERBOARD_JSON_URL")

# Constants
QUESTION_DURATION = 30  # seconds
MAX_DAILY_QUESTIONS = 3
MAX_WEEKLY_QUESTIONS = 10

class QuizManager:
    def __init__(self):
        self.daily_leaderboard = {}
        self.weekly_leaderboard = {}
        self.current_daily_question = None
        self.current_daily_message_id = None
        self.daily_answered_users = set()
        
        self.weekly_test = {
            'questions': [],
            'current_index': 0,
            'participants': {},
            'active': False,
            'poll_ids': {},
            'group_link': None,
            'channel_message_ids': []
        }

    def save_daily_leaderboard(self):
        try:
            github_token = os.getenv("GITHUB_TOKEN")
            repo_owner = "YourGitHubUsername"
            repo_name = "bot_data"
            file_path = "daily_leaderboard.json"

            # GitHub API to update leaderboard file
            get_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{file_path}"
            headers = {"Authorization": f"token {github_token}", "Accept": "application/vnd.github.v3+json"}
            
            get_response = requests.get(get_url, headers=headers)
            sha = get_response.json().get("sha")

            content = json.dumps(self.daily_leaderboard, indent=4).encode("utf-8")
            encoded_content = base64.b64encode(content).decode("utf-8")

            update_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{file_path}"
            data = {
                "message": "Update daily leaderboard",
                "content": encoded_content,
                "sha": sha,
                "branch": "main",
            }
            requests.put(update_url, headers=headers, json=data)
            
            logger.info("Daily leaderboard saved successfully")
        except Exception as e:
            logger.error(f"Error saving daily leaderboard: {e}")

    async def fetch_questions(self, url):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        return await response.json()
        except Exception as e:
            logger.error(f"Error fetching questions from {url}: {e}")
        return []

    async def send_daily_question(self, context):
        """Send a daily trivia question"""
        questions = await self.fetch_questions(DAILY_QUESTIONS_JSON_URL)
        if not questions:
            return

        self.current_daily_question = random.choice(questions)
        self.daily_answered_users.clear()

        keyboard = [
            [InlineKeyboardButton(option, callback_data=option)] 
            for option in self.current_daily_question.get("options", [])
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            message = await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=self.current_daily_question.get("question"),
                reply_markup=reply_markup
            )
            self.current_daily_message_id = message.message_id
        except Exception as e:
            logger.error(f"Error sending daily question: {e}")

    async def handle_daily_answer(self, update, context):
        """Process daily question answers"""
        query = update.callback_query
        user_id = query.from_user.id
        username = query.from_user.first_name

        if user_id in self.daily_answered_users:
            await query.answer("You've already answered!")
            return

        self.daily_answered_users.add(user_id)
        user_answer = query.data.strip()
        correct_answer = self.current_daily_question.get("correct_option", "").strip()

        correct = user_answer == correct_answer

        if correct:
            await query.answer("Correct!")
            if str(user_id) not in self.daily_leaderboard:
                self.daily_leaderboard[str(user_id)] = {"username": username, "score": 0}
            self.daily_leaderboard[str(user_id)]["score"] += 1
            self.save_daily_leaderboard()

            # Optional: Edit message to show explanation
            explanation = self.current_daily_question.get("explanation", "No explanation")
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=self.current_daily_message_id,
                text=f"Question: {self.current_daily_question['question']}\n"
                     f"Correct Answer: {correct_answer}\n"
                     f"Explanation: {explanation}"
            )
        else:
            await query.answer("Incorrect!")

class WeeklyQuizManager(QuizManager):
    async def start_weekly_quiz(self, context):
        """Start the weekly group quiz"""
        questions = await self.fetch_questions(WEEKLY_QUESTIONS_JSON_URL)
        if not questions:
            logger.error("No weekly questions available")
            return

        # Reset and prepare weekly test
        self.weekly_test['questions'] = questions[:MAX_WEEKLY_QUESTIONS]
        self.weekly_test['active'] = True
        self.weekly_test['current_index'] = 0
        self.weekly_test['participants'] = {}

        # Get group invite link
        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        self.weekly_test['group_link'] = chat.invite_link or (
            await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)
        ).invite_link

        # Send start message
        start_message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="🌟 Weekly Quiz Starting Now! 🌟",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Discussion", url=self.weekly_test['group_link'])]
            ])
        )
        self.weekly_test['channel_message_ids'].append(start_message.message_id)

        # Send first question
        await self.send_weekly_question(context, 0)

    async def send_weekly_question(self, context, question_index):
        """Send weekly quiz question to discussion group"""
        if not self.weekly_test['active'] or question_index >= len(self.weekly_test['questions']):
            await self.end_weekly_quiz(context)
            return

        question = self.weekly_test['questions'][question_index]
        
        try:
            poll = await context.bot.send_poll(
                chat_id=DISCUSSION_GROUP_ID,
                question=question['question'],
                options=question['options'],
                type=Poll.QUIZ,
                correct_option_id=question['correct_option'],
                open_period=QUESTION_DURATION
            )

            self.weekly_test['poll_ids'][question_index] = poll.poll.id
            
            # Schedule next question or quiz end
            context.job_queue.run_once(
                lambda ctx: asyncio.create_task(
                    self.send_weekly_question(ctx, question_index + 1)
                ),
                QUESTION_DURATION + 2
            )

        except Exception as e:
            logger.error(f"Error sending weekly question: {e}")

    async def handle_weekly_poll_answer(self, update, context):
        """Track correct answers in weekly quiz"""
        poll_answer = update.poll_answer
        user = poll_answer.user

        # Find the question index for this poll
        question_index = next(
            (idx for idx, p_id in self.weekly_test['poll_ids'].items() if p_id == poll_answer.poll_id),
            None
        )

        if question_index is not None and poll_answer.option_ids:
            # Check if the selected option is correct
            correct_option_id = self.weekly_test['questions'][question_index]['correct_option']
            if poll_answer.option_ids[0] == correct_option_id:
                user_id = user.id
                username = user.full_name or user.username or f"User {user_id}"
                
                if user_id not in self.weekly_test['participants']:
                    self.weekly_test['participants'][user_id] = {"name": username, "score": 0}
                self.weekly_test['participants'][user_id]["score"] += 1

    async def end_weekly_quiz(self, context):
        """End weekly quiz and display results"""
        if not self.weekly_test['active']:
            return

        results = sorted(
            self.weekly_test['participants'].items(),
            key=lambda x: x[1]["score"],
            reverse=True
        )

        # Prepare leaderboard message
        leaderboard_text = "🏆 Weekly Quiz Results 🏆\n\n"
        for i, (_, data) in enumerate(results[:10], 1):
            leaderboard_text += f"{i}. {data['name']}: {data['score']} points\n"

        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=leaderboard_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Discussion", url=self.weekly_test['group_link'])]
            ])
        )

        self.weekly_test['active'] = False

def setup_schedules(quiz_manager, weekly_quiz_manager, job_queue):
    """Set up scheduled quiz events"""
    # Daily questions at multiple times
    daily_times = [(8, 0), (12, 30), (18, 0)]
    for hour, minute in daily_times:
        job_queue.run_daily(
            quiz_manager.send_daily_question, 
            time=datetime.now(pytz.timezone('Asia/Gaza')).replace(hour=hour, minute=minute).time()
        )

    # Weekly quiz on Friday at 6 PM
    gaza_tz = pytz.timezone('Asia/Gaza')
    now = datetime.now(gaza_tz)
    
    days_until_friday = (4 - now.weekday() + 7) % 7
    next_friday = now + timedelta(days=days_until_friday)
    next_friday = next_friday.replace(hour=18, minute=0, second=0, microsecond=0)
    
    job_queue.run_once(
        weekly_quiz_manager.start_weekly_quiz,
        (next_friday - now).total_seconds()
    )

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    quiz_manager = QuizManager()
    weekly_quiz_manager = WeeklyQuizManager()

    # Add handlers
    application.add_handler(CallbackQueryHandler(quiz_manager.handle_daily_answer))
    application.add_handler(PollAnswerHandler(weekly_quiz_manager.handle_weekly_poll_answer))
    application.add_handler(CommandHandler("start", lambda update, context: update.message.reply_text("Quiz Bot Ready!")))
    application.add_handler(CommandHandler("daily", lambda update, context: quiz_manager.send_daily_question(context) if update.effective_user.id == OWNER_ID else None))
    application.add_handler(CommandHandler("weekly", lambda update, context: weekly_quiz_manager.start_weekly_quiz(context) if update.effective_user.id == OWNER_ID else None))

    # Schedule quizzes
    setup_schedules(quiz_manager, weekly_quiz_manager, application.job_queue)

    # Start bot
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
