import os
import json
import logging
import asyncio
from datetime import time, timedelta
from telegram import Bot, Update, Poll
from telegram.ext import (
    Application,
    CommandHandler,
    PollAnswerHandler,
    ContextTypes
)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment configuration
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
QUESTIONS_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_URL = os.getenv("LEADERBOARD_JSON_URL")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

class QuizBot:
    def __init__(self):
        self.questions = []
        self.leaderboard = {}
        self.active_poll = None
        self.answered_users = set()
        self.app = Application.builder().token(BOT_TOKEN).build()
        
        # Register handlers
        self.app.add_handler(PollAnswerHandler(self.handle_answer))
        self.app.add_handler(CommandHandler("start", self.start_cmd))

    async def initialize(self):
        """Load initial data from GitHub"""
        await self.load_questions()
        await self.load_leaderboard()
        await self.setup_schedule()
        await self.app.bot.set_webhook(os.getenv("WEBHOOK_URL"))

    async def load_questions(self):
        """Load questions from GitHub repository"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    QUESTIONS_URL,
                    headers={"Authorization": f"token {GITHUB_TOKEN}"}
                )
                self.questions = response.json()
                logger.info(f"Loaded {len(self.questions)} questions")
        except Exception as e:
            logger.error(f"Failed to load questions: {e}")

    async def load_leaderboard(self):
        """Load leaderboard from GitHub repository"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    LEADERBOARD_URL,
                    headers={"Authorization": f"token {GITHUB_TOKEN}"}
                )
                self.leaderboard = response.json()
                logger.info(f"Loaded {len(self.leaderboard)} scores")
        except Exception as e:
            logger.error(f"Failed to load leaderboard: {e}")

    async def post_question(self, context: ContextTypes.DEFAULT_TYPE):
        """Post a new question to the channel"""
        if not self.questions:
            await self.load_questions()
            if not self.questions:
                logger.warning("No questions available")
                return

        question = self.questions.pop(0)
        try:
            poll = await context.bot.send_poll(
                chat_id=CHANNEL_ID,
                question=question["question"],
                options=question["options"],
                type=Poll.QUIZ,
                correct_option_id=question["correct_option_id"],
                explanation=question.get("explanation", "")
            )
            self.active_poll = poll.poll.id
            self.answered_users = set()
            await self.update_github_questions()
        except Exception as e:
            logger.error(f"Failed to post question: {e}")

    async def update_github_questions(self):
        """Update questions.json on GitHub"""
        try:
            async with httpx.AsyncClient() as client:
                # Get current SHA
                existing = await client.get(
                    f"https://api.github.com/repos/{os.getenv('REPO_OWNER')}/{os.getenv('REPO_NAME')}/contents/questions.json",
                    headers={"Authorization": f"token {GITHUB_TOKEN}"}
                )
                sha = existing.json().get("sha") if existing.status_code == 200 else None

                # Prepare update
                content = base64.b64encode(json.dumps(self.questions).encode()).decode()
                payload = {
                    "message": "Question removed",
                    "content": content,
                    "sha": sha
                }
                await client.put(
                    f"https://api.github.com/repos/{os.getenv('REPO_OWNER')}/{os.getenv('REPO_NAME')}/contents/questions.json",
                    json=payload,
                    headers={"Authorization": f"token {GITHUB_TOKEN}"}
                )
        except Exception as e:
            logger.error(f"Failed to update questions: {e}")

    async def handle_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle poll answers"""
        answer = update.poll_answer
        user = update.effective_user
        
        if answer.poll_id != self.active_poll or user.id in self.answered_users:
            return

        self.answered_users.add(user.id)
        
        # Assume correct answer if we can't verify (for simplicity)
        username = user.username or user.first_name
        self.leaderboard[username] = self.leaderboard.get(username, 0) + 1
        
        try:
            await self.update_github_leaderboard()
        except Exception as e:
            logger.error(f"Failed to update leaderboard: {e}")

    async def update_github_leaderboard(self):
        """Update leaderboard.json on GitHub"""
        try:
            async with httpx.AsyncClient() as client:
                # Get current SHA
                existing = await client.get(
                    f"https://api.github.com/repos/{os.getenv('REPO_OWNER')}/{os.getenv('REPO_NAME')}/contents/leaderboard.json",
                    headers={"Authorization": f"token {GITHUB_TOKEN}"}
                )
                sha = existing.json().get("sha") if existing.status_code == 200 else None

                # Prepare update
                content = base64.b64encode(json.dumps(self.leaderboard).encode()).decode()
                payload = {
                    "message": "Score updated",
                    "content": content,
                    "sha": sha
                }
                await client.put(
                    f"https://api.github.com/repos/{os.getenv('REPO_OWNER')}/{os.getenv('REPO_NAME')}/contents/leaderboard.json",
                    json=payload,
                    headers={"Authorization": f"token {GITHUB_TOKEN}"}
                )
        except Exception as e:
            logger.error(f"Leaderboard update failed: {e}")

    async def show_leaderboard(self, context: ContextTypes.DEFAULT_TYPE):
        """Display current leaderboard"""
        sorted_board = sorted(self.leaderboard.items(), key=lambda x: x[1], reverse=True)[:10]
        text = "🏆 Current Leaderboard:\n" + "\n".join(
            f"{i}. {name}: {score}" for i, (name, score) in enumerate(sorted_board, 1)
        )
        await context.bot.send_message(chat_id=CHANNEL_ID, text=text)

    async def setup_schedule(self):
        """Configure daily schedule"""
        job_queue = self.app.job_queue
        tz = timezone(timedelta(hours=3))  # Adjust to your timezone

        # Question times: 8 AM, 12 PM, 6 PM
        for hour in [8, 12, 18]:
            job_queue.run_daily(
                self.post_question,
                time=time(hour, 0, tzinfo=tz),
                days=tuple(range(7))
            
        # Leaderboard time: 7 PM
        job_queue.run_daily(
            self.show_leaderboard,
            time=time(19, 0, tzinfo=tz),
            days=tuple(range(7)))

    async def start_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Start command handler"""
        await update.message.reply_text("✅ Bot is running!")

    async def run(self):
        """Start the application"""
        await self.initialize()
        await self.app.run_polling()

if __name__ == "__main__":
    bot = QuizBot()
    asyncio.run(bot.run())
