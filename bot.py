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
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", 744871903))  # Your Telegram ID
PORT = int(os.getenv("PORT", 8443))

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
        self.app.add_handler(CommandHandler("test", self.test_cmd))

    async def initialize(self):
        """Load initial data from GitHub"""
        await self.load_questions()
        await self.load_leaderboard()
        await self.setup_schedule()
        await self.app.bot.set_webhook(os.getenv("WEBHOOK_URL"))

    # ... [Keep all previous methods unchanged until test_cmd] ...

    async def test_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Owner-only test command for sending questions"""
        # Verify identity and chat type
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text("🚫 Unauthorized access")
            return
            
        if update.effective_chat.type != "private":
            await update.message.reply_text("⚠️ This command only works in DMs")
            return

        try:
            # Preserve original questions list
            original_questions = self.questions.copy()
            
            # Force reload latest questions
            await self.load_questions()
            
            if not self.questions:
                await update.message.reply_text("❌ No questions available")
                return
                
            # Send test question
            question = self.questions[0]  # Don't remove from list for testing
            poll = await context.bot.send_poll(
                chat_id=CHANNEL_ID,
                question=question["question"],
                options=question["options"],
                type=Poll.QUIZ,
                correct_option_id=question["correct_option_id"],
                explanation=question.get("explanation", "")
            )
            
            # Restore original questions
            self.questions = original_questions
            
            await update.message.reply_text(
                f"✅ Test question sent!\n"
                f"Preview: {poll.link}"
            )
        except Exception as e:
            logger.error(f"Test failed: {e}")
            await update.message.reply_text(f"❌ Test failed: {str(e)}")

    # ... [Rest of the code remains unchanged] ...

if __name__ == "__main__":
    bot = QuizBot()
    asyncio.run(bot.run())
