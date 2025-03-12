import os
import json
import asyncio
import logging
import requests
from datetime import time
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
QUESTIONS_URL = os.getenv("QUESTIONS_JSON_URL")
LEADERBOARD_URL = os.getenv("LEADERBOARD_JSON_URL")

class QuizBot:
    def __init__(self):
        self.app = Application.builder().token(TOKEN).build()
        self.scheduler = AsyncIOScheduler()
        self.questions = []
        self.leaderboard = {}
        self.current_poll = None

        # Register handlers
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CallbackQueryHandler(self.handle_answer))

        # Schedule jobs
        self.schedule_jobs()

    def schedule_jobs(self):
        """Schedule daily tasks"""
        times = [(8, 0), (12, 0), (18, 0), (20, 0)]
        for hour, minute in times[:3]:
            self.scheduler.add_job(
                self.post_question,
                'cron',
                hour=hour,
                minute=minute,
                args=[self.app]
            )
        self.scheduler.add_job(
            self.post_leaderboard,
            'cron',
            hour=times[3][0],
            minute=times[3][1],
            args=[self.app]
        )

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        await update.message.reply_text("Welcome to Daily Quiz! 🧠")

    async def post_question(self, context: ContextTypes.DEFAULT_TYPE):
        """Post a new question to the channel"""
        if not self.questions:
            self.questions = self.fetch_questions()
        
        try:
            question = self.questions.pop(0)
            keyboard = [
                [InlineKeyboardButton(opt, callback_data=json.dumps({
                    "q": question['id'],
                    "a": idx
                }))] for idx, opt in enumerate(question['options'])
            ]
            
            message = await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=question['question'],
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            self.current_poll = {
                "id": question['id'],
                "correct": question['answer'],
                "message_id": message.message_id
            }

        except Exception as e:
            logger.error(f"Failed to post question: {e}")

    async def handle_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle user's answer selection"""
        query = update.callback_query
        await query.answer()
        
        try:
            data = json.loads(query.data)
            if not self.current_poll or data['q'] != self.current_poll['id']:
                return

            user = query.from_user
            leaderboard = self.fetch_leaderboard()
            
            if data['a'] == self.current_poll['correct']:
                leaderboard[str(user.id)] = leaderboard.get(str(user.id), 0) + 1
                await query.edit_message_text(f"✅ {user.first_name} got it right!")
            else:
                await query.edit_message_text(f"❌ {user.first_name} missed this one")

            self.update_leaderboard(leaderboard)

        except Exception as e:
            logger.error(f"Error handling answer: {e}")

    async def post_leaderboard(self, context: ContextTypes.DEFAULT_TYPE):
        """Post current leaderboard"""
        leaderboard = self.fetch_leaderboard()
        if not leaderboard:
            return
        
        sorted_lb = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)
        lb_text = "\n".join(
            f"{i+1}. {uid}: {score}" for i, (uid, score) in enumerate(sorted_lb)
        )
        
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"🏆 Leaderboard:\n{lb_text}"
        )

    def fetch_questions(self):
        """Load questions from GitHub"""
        try:
            response = requests.get(QUESTIONS_URL)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error loading questions: {e}")
            return []

    def fetch_leaderboard(self):
        """Load leaderboard from GitHub"""
        try:
            response = requests.get(LEADERBOARD_URL)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error loading leaderboard: {e}")
            return {}

    def update_leaderboard(self, leaderboard):
        """Update leaderboard on GitHub"""
        # Implement your GitHub API update logic here
        pass

    async def run(self):
        """Start the bot"""
        self.scheduler.start()
        await self.app.initialize()
        await self.app.start_polling()
        
        # Keep the bot running
        while True:
            await asyncio.sleep(3600)  # Sleep for 1 hour

if __name__ == "__main__":
    bot = QuizBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        bot.scheduler.shutdown()
        bot.app.stop()
