import os
import json
import time
import logging
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Bot, Update, Poll
from telegram.ext import Dispatcher, CommandHandler, PollAnswerHandler

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment configuration
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
PORT = int(os.getenv("PORT", 8443))

# Simple in-memory storage
quiz_data = {
    "questions": [],
    "leaderboard": {},
    "active_poll": None,
    "answered_users": set()
}

class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/webhook':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            update = Update.de_json(json.loads(post_data), bot)
            dispatcher.process_update(update)
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

def run_server():
    server = HTTPServer(('0.0.0.0', PORT), WebhookHandler)
    server.serve_forever()

def load_questions():
    """Simple file-based question loader (replace with your GitHub logic)"""
    try:
        with open('questions.json') as f:
            quiz_data["questions"] = json.load(f)
    except Exception as e:
        logger.error(f"Error loading questions: {e}")

def save_leaderboard():
    """Simple file-based leaderboard saver"""
    try:
        with open('leaderboard.json', 'w') as f:
            json.dump(quiz_data["leaderboard"], f)
    except Exception as e:
        logger.error(f"Error saving leaderboard: {e}")

def post_question():
    if not quiz_data["questions"]:
        return
    
    question = quiz_data["questions"].pop(0)
    try:
        poll = bot.send_poll(
            chat_id=CHANNEL_ID,
            question=question["question"],
            options=question["options"],
            type=Poll.QUIZ,
            correct_option_id=question["correct_option_id"]
        )
        quiz_data["active_poll"] = poll.poll.id
        quiz_data["answered_users"] = set()
    except Exception as e:
        logger.error(f"Error posting question: {e}")

def handle_poll_answer(update: Update, context):
    answer = update.poll_answer
    user = update.effective_user
    
    if (answer.poll_id != quiz_data["active_poll"] or 
        user.id in quiz_data["answered_users"]):
        return
    
    quiz_data["answered_users"].add(user.id)
    
    if answer.option_ids[0] == quiz_data["active_poll"].correct_option_id:
        username = user.username or user.first_name
        quiz_data["leaderboard"][username] = quiz_data["leaderboard"].get(username, 0) + 1
        save_leaderboard()

def schedule_tasks():
    """Simple scheduling without APScheduler"""
    while True:
        now = time.localtime()
        if now.tm_hour in [8, 12, 18] and now.tm_min == 0:
            post_question()
            time.sleep(61)  # Prevent duplicate posts
        elif now.tm_hour == 19 and now.tm_min == 0:
            # Post leaderboard logic
            time.sleep(61)
        else:
            time.sleep(30)

if __name__ == '__main__':
    # Initialize components
    bot = Bot(token=BOT_TOKEN)
    dispatcher = Dispatcher(bot, None, workers=0)
    
    # Set webhook
    bot.set_webhook(url=os.getenv("WEBHOOK_URL"))
    
    # Register handlers
    dispatcher.add_handler(PollAnswerHandler(handle_poll_answer))
    
    # Load initial data
    load_questions()
    
    # Start scheduler thread
    Thread(target=schedule_tasks, daemon=True).start()
    
    # Start web server
    run_server()
