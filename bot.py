import os
import json
import logging
import asyncio
import base64
from datetime import time, timedelta, timezone
from telegram import Bot, Update, Poll
from telegram.ext import (
    Application,
    CommandHandler,
    PollAnswerHandler,
    ContextTypes
)
import httpx
from aiohttp import web

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
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", 744871903))
PORT = int(os.getenv("PORT", 8443))

class QuizBot:
    def __init__(self):
        self.leaderboard = {}
        self.active_poll = None
        self.answered_users = set()
        self.app = Application.builder().token(BOT_TOKEN).build()
        
        # Register handlers
        self.app.add_handler(PollAnswerHandler(self.handle_answer))
        self.app.add_handler(CommandHandler("start", self.start_cmd))
        self.app.add_handler(CommandHandler("test", self.test_cmd))

    async def initialize(self):
        """Initialize the bot"""
        await self.load_leaderboard()
        await self.setup_schedule()
        await self.app.bot.set_webhook(os.getenv("WEBHOOK_URL"))

    async def load_leaderboard(self):
        """Load leaderboard from GitHub"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    LEADERBOARD_URL,
                    headers={"Authorization": f"token {GITHUB_TOKEN}"}
                )
                self.leaderboard = response.json()
                logger.info(f"Loaded leaderboard with {len(self.leaderboard)} entries")
        except Exception as e:
            logger.error(f"Failed to load leaderboard: {e}")
            self.leaderboard = {}

    async def fetch_questions(self):
        """Fetch questions from GitHub"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    QUESTIONS_URL,
                    headers={"Authorization": f"token {GITHUB_TOKEN}"}
                )
                return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch questions: {e}")
            return []

    async def post_question(self, context: ContextTypes.DEFAULT_TYPE):
        """Post a question to the channel"""
        try:
            questions = await self.fetch_questions()
            if not questions:
                logger.warning("No questions available")
                return

            question = questions[0]
            logger.info(f"Posting question: {question['question']}")

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
            logger.info(f"Poll posted: {poll.poll.id}")
        except Exception as e:
            logger.error(f"Failed to post question: {e}")

    async def handle_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle poll answers (FIXED METHOD)"""
        answer = update.poll_answer
        user = update.effective_user
        
        if answer.poll_id != self.active_poll or user.id in self.answered_users:
            return

        self.answered_users.add(user.id)
        
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
                existing = await client.get(
                    f"https://api.github.com/repos/{os.getenv('REPO_OWNER')}/{os.getenv('REPO_NAME')}/contents/leaderboard.json",
                    headers={"Authorization": f"token {GITHUB_TOKEN}"}
                )
                sha = existing.json().get("sha") if existing.status_code == 200 else None

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
        text = "🏆 Leaderboard:\n" + "\n".join(
            f"{i}. {name}: {score}" for i, (name, score) in enumerate(sorted_board, 1)
        )
        await context.bot.send_message(chat_id=CHANNEL_ID, text=text)

    async def setup_schedule(self):
        """Configure daily schedule"""
        job_queue = self.app.job_queue
        tz = timezone(timedelta(hours=3))  # UTC+3

        schedule = [
            (self.post_question, time(8, 0, tzinfo=tz)),
            (self.post_question, time(12, 0, tzinfo=tz)),
            (self.post_question, time(18, 0, tzinfo=tz)),
            (self.show_leaderboard, time(19, 0, tzinfo=tz))
        ]

        for job, time_spec in schedule:
            job_queue.run_daily(
                callback=job,
                time=time_spec,
                days=tuple(range(7))
            )

    async def start_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Start command handler"""
        await update.message.reply_text("✅ Bot is running!")

    async def test_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Test command handler"""
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text("🚫 Unauthorized")
            return
            
        if update.effective_chat.type != "private":
            await update.message.reply_text("⚠️ Use DMs for testing")
            return

        try:
            await self.post_question(context)
            await update.message.reply_text("✅ Test question sent!")
        except Exception as e:
            logger.error(f"Test failed: {e}")
            await update.message.reply_text(f"❌ Test failed: {str(e)}")

    async def webhook_handler(self, request):
        """Handle webhook requests"""
        data = await request.json()
        update = Update.de_json(data, self.app.bot)
        await self.app.update_queue.put(update)
        return web.Response()

    async def run(self):
        """Start application"""
        await self.initialize()
        
        app = web.Application()
        app.router.add_post('/webhook', self.webhook_handler)
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', PORT)
        await site.start()
        
        logger.info(f"Server running on port {PORT}")
        await asyncio.Event().wait()

if __name__ == "__main__":
    bot = QuizBot()
    asyncio.run(bot.run())
