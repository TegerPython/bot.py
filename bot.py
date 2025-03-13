from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
import os
import httpx
import json

# Initialize Flask app
app = Flask(__name__)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Function to be scheduled
def scheduled_task():
    logger.info("Scheduled task executed.")
    # Add your task logic here, e.g., sending messages via Telegram

# Initialize the scheduler
scheduler = BackgroundScheduler(daemon=True)

# Add a daily job at 2:00 AM
scheduler.add_job(
    func=scheduled_task,
    trigger=CronTrigger(hour=2, minute=0),
    id='daily_task',
    name='Daily Task',
    replace_existing=True
)

# Start the scheduler
scheduler.start()

# Define a route for the Flask app
@app.route('/')
def index():
    return 'Flask app with APScheduler is running!'

# Define a route to handle webhooks
@app.route('/webhook', methods=['POST'])
async def webhook():
    data = await request.get_json()
    # Process the webhook data as needed
    return jsonify({'status': 'success'}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8443)))
