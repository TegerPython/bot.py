import os
import telebot
import requests
import json
import time
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

# Environment variables
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')
QUESTIONS_JSON_URL = os.getenv('QUESTIONS_JSON_URL')
LEADERBOARD_JSON_URL = os.getenv('LEADERBOARD_JSON_URL')
OWNER_TELEGRAM_ID = os.getenv('OWNER_TELEGRAM_ID')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

bot = telebot.TeleBot(TOKEN)
scheduler = BackgroundScheduler()

# Helper functions
def fetch_json_data(url):
    response = requests.get(url)
    return response.json() if response.status_code == 200 else None

def update_json_data(url, data):
    headers = {'Authorization': f'token {os.getenv("GITHUB_TOKEN")}'}
    update_url = f"https://api.github.com/repos/{os.getenv('REPO_OWNER')}/{os.getenv('REPO_NAME')}/contents/{url}"
    message = {'message': 'Updated questions', 'content': json.dumps(data)}
    response = requests.put(update_url, headers=headers, json=message)
    return response.status_code == 200

def send_question_to_channel(question):
    bot.send_message(CHANNEL_ID, f"Question: {question['question']}\nOptions: {', '.join(question['options'])}")

def update_leaderboard(user_id, points):
    leaderboard = fetch_json_data(LEADERBOARD_JSON_URL)
    if leaderboard is None:
        leaderboard = {}

    if user_id in leaderboard:
        leaderboard[user_id] += points
    else:
        leaderboard[user_id] = points
    
    update_json_data("leaderboard.json", leaderboard)

# Scheduler functions
def post_daily_questions():
    questions = fetch_json_data(QUESTIONS_JSON_URL)
    if questions and len(questions) > 0:
        question = questions.pop(0)
        send_question_to_channel(question)
        update_json_data("questions.json", questions)

# Bot commands
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Welcome! Ready to play? Let's go!")

@bot.message_handler(commands=['test'])
def test(message):
    bot.reply_to(message, "Test successful!")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text.lower()
    if text in ["option1", "option2", "option3", "option4"]:
        response = "Correct!"  # This will need to be customized for the actual correct answer.
        bot.reply_to(message, response)

# Set up scheduler to post questions at specified times
scheduler.add_job(post_daily_questions, 'interval', hours=8, start_date=datetime.now())
scheduler.start()

# Webhook setup
@bot.route('/webhook', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('UTF-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])

# Start the bot with webhook
bot.remove_webhook()
bot.set_webhook(url=WEBHOOK_URL)

# Keep the program running
if __name__ == '__main__':
    while True:
        time.sleep(60)  # Keep running the scheduler
