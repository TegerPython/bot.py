import os
import json
import logging
import asyncio
import pytz
from datetime import datetime, time, timedelta
import telebot
from telebot import types
import httpx
import base64
import random
import threading
import time

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
        self.answered_users = {}
        self.questions = []
        self.current_question_index = 0
        self.bot = telebot.TeleBot(BOT_TOKEN)

        # Register handlers
        self.bot.message_handler(commands=['test'])(self.test_cmd)
        self.bot.message_handler(commands=['leaderboard'])(self.show_leaderboard_cmd)
        self.bot.callback_query_handler(func=lambda call: True)(self.callback_query_handler)

    async def initialize(self):
        """Initialize the bot"""
        await self.load_leaderboard()
        await self.fetch_questions_and_setup()
        self.bot.remove_webhook()
        self.bot.set_webhook(url=WEBHOOK_URL)

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

    async def fetch_questions_and_setup(self):
        """Fetch questions and set up scheduling"""
        self.questions = await self.fetch_questions()
        if self.questions:
            self.setup_schedule()

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

    def ask_question(self):
        """Post a question to the channel"""
        if not self.questions:
            logger.warning("No questions available")
            return

        q_data = self.questions[self.current_question_index % len(self.questions)]
        self.current_question_index += 1

        question_text = f"📚 *English Learning Challenge!*\n{q_data['question']}\n\n🕒 You have *30 minutes* to answer!"

        markup = types.InlineKeyboardMarkup()
        for ans in q_data["answers"]:
            markup.add(types.InlineKeyboardButton(ans, callback_data=ans))

        async def send_and_schedule():
            msg = self.bot.send_message(CHANNEL_ID, question_text, parse_mode="Markdown", reply_markup=markup)
            self.answered_users["message_id"] = msg.message_id
            threading.Timer(1800, self.delete_question, args=[msg.message_id]).start()

        asyncio.run(send_and_schedule())

    def delete_question(self, message_id):
        """Delete the question message"""
        async def delete():
            try:
                self.bot.delete_message(chat_id=CHANNEL_ID, message_id=message_id)
            except Exception as e:
                logger.error(f"Failed to delete message: {e}")
        asyncio.run(delete())

    async def heartbeat(self):
        """Send regular status updates"""
        now = datetime.now(GAZA_TZ).strftime("%Y-%m-%d %H:%M:%S")
        self.bot.send_message(
            chat_id=OWNER_ID,
            text=f"💓 Bot operational - Last check: {now}\n"
                 f"Questions loaded: {len(self.questions)}\n"
                 f"Leaderboard entries: {len(self.leaderboard)}"
        )

    def get_utc_time(self, hour, minute):
        local_time = GAZA_TZ.localize(datetime.now().replace(hour=hour, minute=minute))
        return local_time.astimezone(pytz.utc).time()

    def question_scheduler(self):
        gaza_tz = pytz.timezone('Asia/Gaza')
        while True:
            current_time = datetime.now(gaza_tz).strftime("%H:%M")
            if current_time == "13:45":
                self.ask_question()
            elif current_time == "14:05":
                self.ask_question()
            elif current_time == "18:35":
                self.ask_question()
            time.sleep(60)

    def setup_schedule(self):
        threading.Thread(target=self.question_scheduler).start()
        self.bot.set_update_listener(self.heartbeat)

    def test_cmd(self, message):
        """Owner-only test command"""
        if message.from_user.id != OWNER_ID:
            self.bot.reply_to(message, "🚫 Unauthorized")
            return

        try:
            question = random.choice(self.questions)
            poll = self.bot.send_poll(
                chat_id=CHANNEL_ID,
                question=question["question"],
                options=question["answers"],
                type="quiz",
                correct_option_id=question["answers"].index(question["correct"]),
                explanation=question.get("explanation", "")
            )
            self.bot.reply_to(message, f"✅ Test question sent: {poll.link}")
        except Exception as e:
            logger.error(f"Test failed: {e}")
            self.bot.reply_to(message, f"❌ Test failed: {str(e)}")

    def show_leaderboard_cmd(self, message):
        """Show leaderboard in private chat"""
        sorted_board = sorted(self.leaderboard.items(), key=lambda x: x[1], reverse=True)
        text = "🏆 Current Leaderboard:\n" + "\n".join(
            f"{i}. {name}: {score}" for i, (name, score) in enumerate(sorted_board, 1)
        )
        self.bot.reply_to(message, text)

    def show_leaderboard(self):
        """Post daily leaderboard to channel"""
        sorted_board = sorted(self.leaderboard.items(), key=lambda x: x[1], reverse=True)
        text = "🏆 Daily Leaderboard:\n" + "\n".join(
            f"{i}. {name}: {score}" for i, (name, score) in enumerate(sorted_board, 1)
        )
        self.bot.send_message(chat_id=CHANNEL_ID, text=text)

    def callback_query_handler(self, call):
        """Handle answer selection"""
        user_id = call.from_user.id
        username = call.from_user.username or call.from_user.first_name
        answer = call.data

        if user_id in self.answered_users:
            self.bot.answer_callback_query(call.id, "❌ You've already answered!", show_alert=True)
            return

        self.answered_users[user_id] = True  # Mark as answered

        # Check correctness
        current_question = self.questions[(self.current_question_index - 1) % len(self.questions)]
        if answer == current_question["correct"]:
            self.leaderboard[username] = self.leaderboard.get(username, 0) + 1
            self.bot.edit_message_text(
                f"✅ *{username} answered correctly!* The correct answer was *{answer}*.\n\n📖 Explanation: {current_question['explanation']}",
                CHANNEL_ID, self.answered_users["message_id"], parse_mode="Markdown"
            )
            self.show_leaderboard()
        else:
            self.bot.answer_callback_query(
                call.id, f"❌ Wrong answer! The correct answer was *{current_question['correct']}*.\n\n📖 Explanation: {current_question['explanation']}", show_alert=True
            )

        # Inform about the next question
        next_question_time = "14:00"  # Example: Next question at 2:00 PM
        self.bot.send_message(call.from_user.id, f"⏳ *Next question will be posted at {next_question_time}*.\nStay tuned!")

        try:
            self.update_github_leaderboard()
        except Exception as e:
            logger.error(f"Leaderboard update failed: {e}")

    def run(self):
        """Start the application"""
        self.bot.polling(none_stop=True)

if __name__ == "__main__":
    bot = QuizBot()
    bot.run()
