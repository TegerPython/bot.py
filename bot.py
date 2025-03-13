import os
import json
import logging
import requests
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot, Update, ParseMode
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, filters

# Initialize Flask app
app = Flask(__name__)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')
GITHUB_REPO = os.getenv('GITHUB_REPO')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

# Initialize Telegram Bot
bot = Bot(token=TELEGRAM_TOKEN)

# GitHub API URLs
QUESTIONS_URL = f'https://api.github.com/repos/{GITHUB_REPO}/contents/questions.json'
LEADERBOARD_URL = f'https://api.github.com/repos/{GITHUB_REPO}/contents/leaderboard.json'

# Function to fetch data from GitHub
def fetch_github_data(url):
    headers = {'Authorization': f'token {GITHUB_TOKEN}'}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        content = response.json()['content']
        return json.loads(content)
    else:
        logger.error(f'Failed to fetch data from GitHub: {response.status_code}')
        return []

# Function to update data on GitHub
def update_github_data(url, data):
    headers = {'Authorization': f'token {GITHUB_TOKEN}'}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        sha = response.json()['sha']
        update_url = url.replace('repos', 'repos/{GITHUB_REPO}/contents')
        payload = {
            'message': 'Update data',
            'sha': sha,
            'content': json.dumps(data)
        }
        update_response = requests.put(update_url, headers=headers, json=payload)
        if update_response.status_code == 200:
            logger.info('Data updated successfully on GitHub')
        else:
            logger.error(f'Failed to update data on GitHub: {update_response.status_code}')
    else:
        logger.error(f'Failed to fetch data from GitHub: {response.status_code}')

# Function to send a question as a poll
def send_question(context):
    questions = fetch_github_data(QUESTIONS_URL)
    if questions:
        question = questions.pop(0)
        options = question.get('options', [])
        message = bot.send_poll(
            chat_id=CHANNEL_ID,
            question=question.get('question', ''),
            options=options,
            is_anonymous=False
        )
        questions_data = {'questions': questions}
        update_github_data(QUESTIONS_URL, questions_data)

# Set up scheduled tasks
scheduler = BackgroundScheduler()
scheduler.add_job(
    func=send_question,
    trigger=CronTrigger(hour='8,12,18', minute='0', second='0'),
    id='send_question_job',
    name='Send daily questions at 8 AM, 12 PM, and 6 PM',
    replace_existing=True
)
scheduler.start()

# Webhook route
@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return jsonify({'status': 'ok'}), 200

# Set up webhook
def set_webhook():
    webhook_url = f'{WEBHOOK_URL}/{TELEGRAM_TOKEN}'
    bot.set_webhook(url=webhook_url)

# Command handler to test if the bot is online
def test(update, context):
    update.message.reply_text('Bot is online!')

# Set up the dispatcher and add handlers
dispatcher = Dispatcher(bot, None, workers=0)
dispatcher.add_handler(CommandHandler('test', test))

if __name__ == '__main__':
    set_webhook()
    app.run(host='0.0.0.0', port=8443)
