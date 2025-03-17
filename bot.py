import os
import json
import logging
import asyncio
import pytz
from datetime import datetime, time
from telegram import Update, Poll
from telegram.ext import (
    Application,
    CommandHandler,
    PollAnswerHandler,
    ContextTypes,
    JobQueue,
    Defaults
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

# Timezone configuration
GAZA_TZ = pytz.timezone("Asia/Gaza")

class QuizBot:
    def __init__(self):
        self.leaderboard = {}
        self.active_poll = None
        self.answered_users = set()
        defaults = Defaults(tzinfo=GAZA_TZ)
        self.app = Application.builder().token(BOT_TOKEN).defaults(defaults).build()

        # Register handlers
        self.app.add_handler(PollAnswerHandler(self.handle_answer))
        self.app.add_handler(CommandHandler("test", self.test_cmd))
        self.app.add_handler(CommandHandler("leaderboard", self.leaderboard_cmd))

    async def initialize(self):
        """Initialize the bot"""
        await self.load_leaderboard()
        await self.setup_schedule()

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

    async def post_question(self, context: ContextTypes.DEFAULT_TYPE):
        """Post a question to the channel"""
        try:
            questions = await self.fetch_questions()
            if not questions:
                logger.warning("No questions available")
                return

            question = random.choice(questions)
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
        except Exception as e:
            logger.error(f"Failed to post question: {e}")

    async def heartbeat(self, context: ContextTypes.DEFAULT_TYPE):
        """Send regular status updates"""
        now = datetime.now(GAZA_TZ).strftime("%Y-%m-%d %H:%M:%S")
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=f"💓 Bot operational - Last check: {now}\n"
                 f"Questions loaded: {len(await self.fetch_questions())}\n"
                 f"Leaderboard entries: {len(self.leaderboard)}"
        )

    def get_utc_time(self, hour, minute):
        local_time = GAZA_TZ.localize(datetime.now().replace(hour=hour, minute=minute))
        return local_time.astimezone(pytz.utc).time()

    async def setup_schedule(self):
        """Configure daily schedule"""
        job_queue = self.app.job_queue

        # Three daily questions
        for t in [(8, 0), (12, 0), (18, 0)]:
            job_queue.run_daily(
                self.post_question,
                time=self.get_utc_time(*t),
                days=tuple(range(7))  # 0-6, Monday-Sunday
            )

        # Daily leaderboard
        job_queue.run_daily(
            self.show_leaderboard,
            time=self.get_utc_time(19, 0),
            days=tuple(range(7))  # 0-6, Monday-Sunday
        )

        # 1-minute heartbeat
        job_queue.run_repeating(self.heartbeat, interval=60)

    async def test_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Post a test question to the channel"""
        try:
            questions = await self.fetch_questions()
            if not questions:
                await update.message.reply_text("❌ No questions available")
                return

            question = random.choice(questions)
            poll = await context.bot.send_poll(
                chat_id=CHANNEL_ID,
                question=question["question"],
                options=question["options"],
                type=Poll.QUIZ,
                correct_option_id=question["correct_option_id"],
                explanation=question.get("explanation", "")
            )
            if update.effective_chat.id != CHANNEL_ID:
                await update.message.reply_text(f"✅ Test question sent to channel: {poll.link}")

            self.active_poll = poll.poll.id
            self.answered_users = set()
        except Exception as e:
            logger.error(f"Test failed: {e}")
            await update.message.reply_text(f"❌ Test failed: {str(e)}")

    async def leaderboard_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show leaderboard in the channel or DM"""
        sorted_board = sorted(self.leaderboard.items(), key=lambda x: x[1], reverse=True)
        text = "🏆 Leaderboard:\n" + "\n".join(
            f"{i}. {name}: {score}" for i, (name, score) in enumerate(sorted_board, 1)
        )
        if update.effective_chat.id != CHANNEL_ID:
            await update.message.reply_text(text)
        else:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=text)

    async def show_leaderboard(self, context: ContextTypes.DEFAULT_TYPE):
        """Post daily leaderboard to channel"""
        sorted_board = sorted(self.leaderboard.items(), key=lambda x: x[1], reverse=True)
        text = "🏆 Daily Leaderboard:\n" + "\n".join(
            f"{i}. {name}: {score}" for i, (name, score) in enumerate(sorted_board, 1)
        )
        await context.bot.send_message(chat_id=CHANNEL_ID, text=text)

    async def handle_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        import telegram
        print(f"Telegram Bot Version: {telegram.__version__}")
        logger.info(f"Telegram Bot Version: {telegram.__version__}")
        await self.app.run_polling()

if __name__ == "__main__":
    bot = QuizBot()
    asyncio.get_event_loop().run_until_complete(bot.run())
