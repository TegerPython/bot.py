import os
import json
import logging
import asyncio
import pytz
from datetime import datetime, timedelta
from telegram import Update, Poll
from telegram.ext import (
    Application,
    CommandHandler,
    PollAnswerHandler,
    ContextTypes
)
import httpx
import base64
import random

# Logging setup
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
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Timezone configuration
GAZA_TZ = pytz.timezone("Asia/Gaza")

class QuizBot:
    def __init__(self):
        self.leaderboard = {}
        self.active_poll = None
        self.answered_users = set()
        self.app = Application.builder().token(BOT_TOKEN).build()
        
        # Register handlers
        self.app.add_handler(PollAnswerHandler(self.handle_answer))
        self.app.add_handler(CommandHandler("test", self.test_cmd))
        self.app.add_handler(CommandHandler("leaderboard", self.show_leaderboard_cmd))

    async def initialize(self):
        """Initialize the bot"""
        await self.load_leaderboard()
        await self.app.bot.set_webhook(WEBHOOK_URL)
        asyncio.create_task(self.question_scheduler())  # Start custom scheduling loop

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
        """Fetch latest questions from GitHub"""
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

    async def update_github_leaderboard(self):
        """Update leaderboard on GitHub"""
        try:
            async with httpx.AsyncClient() as client:
                existing = await client.get(
                    LEADERBOARD_URL,
                    headers={"Authorization": f"token {GITHUB_TOKEN}"}
                )
                sha = existing.json().get("sha") if existing.status_code == 200 else None

                content = base64.b64encode(json.dumps(self.leaderboard).encode()).decode()
                payload = {
                    "message": "Score updated",
                    "content": content,
                    "sha": sha
                }
                await client.put(LEADERBOARD_URL, json=payload, headers={"Authorization": f"token {GITHUB_TOKEN}"})
        except Exception as e:
            logger.error(f"Leaderboard update failed: {e}")

    async def post_question(self):
        """Post a question to the channel"""
        try:
            questions = await self.fetch_questions()
            if not questions:
                logger.warning("No questions available")
                return

            question = questions[datetime.now().day % len(questions)]
            poll = await self.app.bot.send_poll(
                chat_id=CHANNEL_ID,
                question=question["question"],
                options=question["options"],
                type=Poll.QUIZ,
                correct_option_id=question["correct_option_id"],
                explanation=question.get("explanation", "")
            )
            
            self.active_poll = poll.poll.id
            self.answered_users = set()
        except Exception as e:
            logger.error(f"Failed to post question: {e}")

    async def heartbeat(self):
        """Send regular status updates"""
        while True:
            now = datetime.now(GAZA_TZ).strftime("%Y-%m-%d %H:%M:%S")
            await self.app.bot.send_message(
                chat_id=OWNER_ID,
                text=f"💓 Bot operational - Last check: {now}\n"
                     f"Questions loaded: {len(await self.fetch_questions())}\n"
                     f"Leaderboard entries: {len(self.leaderboard)}"
            )
            await asyncio.sleep(60)  # Every 1 minute

    async def question_scheduler(self):
        """Custom loop to post questions at 8 AM, 12 PM, and 6 PM"""
        post_times = [time(8, 0), time(12, 0), time(18, 0)]

        while True:
            now = datetime.now(GAZA_TZ)
            next_time = min([t for t in post_times if t > now.time()], default=post_times[0])
            next_post = datetime.combine(now.date(), next_time, GAZA_TZ)

            if next_time == post_times[0] and now.time() > post_times[-1]:
                next_post += timedelta(days=1)  # Move to next day if it's past last slot

            wait_time = (next_post - now).total_seconds()
            logger.info(f"Next question at {next_post.strftime('%Y-%m-%d %H:%M:%S')}")
            await asyncio.sleep(wait_time)
            await self.post_question()

    async def test_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Owner-only test command"""
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text("🚫 Unauthorized")
            return
            
        try:
            questions = await self.fetch_questions()  # Always fetch latest
            if not questions:
                await update.message.reply_text("❌ No questions available")
                return

            question = random.choice(questions)
            poll = await self.app.bot.send_poll(
                chat_id=CHANNEL_ID,
                question=question["question"],
                options=question["options"],
                type=Poll.QUIZ,
                correct_option_id=question["correct_option_id"],
                explanation=question.get("explanation", "")
            )
            await update.message.reply_text(f"✅ Test question sent: {poll.link}")
        except Exception as e:
            logger.error(f"Test failed: {e}")
            await update.message.reply_text(f"❌ Test failed: {str(e)}")

    async def show_leaderboard_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show leaderboard in private chat"""
        sorted_board = sorted(self.leaderboard.items(), key=lambda x: x[1], reverse=True)
        text = "🏆 Current Leaderboard:\n" + "\n".join(
            f"{i}. {name}: {score}" for i, (name, score) in enumerate(sorted_board, 1)
        )
        await update.message.reply_text(text)

    async def handle_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            logger.error(f"Leaderboard update failed: {e}")

    async def run(self):
        """Start the application"""
        await self.initialize()
        await self.app.initialize()
        await self.app.start()
        await asyncio.gather(self.heartbeat())

if __name__ == "__main__":
    bot = QuizBot()
    asyncio.run(bot.run())
