import os
import json
import logging
import asyncio
import datetime
import random
from telegram import Update, Poll, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8443"))

# Test data structure
class WeeklyTest:
    def __init__(self):
        self.questions = []
        self.current_question_index = 0
        self.participants = {}  # user_id -> {"name": name, "score": score}
        self.active = False
        self.message_ids = []  # Store message IDs of sent questions for later reference

    def reset(self):
        self.questions = []
        self.current_question_index = 0
        self.participants = {}
        self.active = False
        self.message_ids = []

    def add_point(self, user_id, user_name):
        if user_id not in self.participants:
            self.participants[user_id] = {"name": user_name, "score": 0}
        self.participants[user_id]["score"] += 1

    def get_results(self):
        sorted_participants = sorted(
            self.participants.items(),
            key=lambda x: x[1]["score"],
            reverse=True
        )
        return sorted_participants

# Global test instance
weekly_test = WeeklyTest()

# Sample test questions
sample_questions = [
    {
        "question": "What is the capital of France?",
        "options": ["Paris", "London", "Berlin", "Madrid"],
        "correct_option": 0
    },
    {
        "question": "Which planet is closest to the sun?",
        "options": ["Mercury", "Venus", "Earth", "Mars"],
        "correct_option": 0
    },
    {
        "question": "What is 2+2?",
        "options": ["3", "4", "5", "6"],
        "correct_option": 1
    }
]

async def send_question_with_buttons(context, question_index):
    """Send a question with answer buttons in the group/channel"""
    global weekly_test
    
    if question_index >= len(weekly_test.questions):
        # All questions sent, schedule leaderboard post
        logger.info("All questions sent, scheduling leaderboard results")
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_leaderboard_results(ctx)),
            60  # Wait 1 minute after the last question
        )
        return
    
    question = weekly_test.questions[question_index]
    weekly_test.current_question_index = question_index
    
    # Create inline keyboard with answer options
    keyboard = []
    row = []
    for i, option in enumerate(question["options"]):
        # Use a callback data format that includes the question index and option index
        callback_data = f"q{question_index}_a{i}"
        row.append(InlineKeyboardButton(option, callback_data=callback_data))
        if (i + 1) % 2 == 0 or i == len(question["options"]) - 1:
            keyboard.append(row)
            row = []
            
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Send question with options as buttons
    try:
        message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"Question {question_index + 1}: {question['question']}",
            reply_markup=reply_markup
        )
        weekly_test.message_ids.append(message.message_id)
        
        logger.info(f"Question {question_index + 1} sent with inline keyboard")
        
        # Schedule next question after delay
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_question_with_buttons(ctx, question_index + 1)),
            12  # Wait 12 seconds before sending next question
        )
        
        # Schedule removal of buttons after 10 seconds
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(reveal_correct_answer(ctx, question_index)),
            10  # Show correct answer after 10 seconds
        )
    except Exception as e:
        logger.error(f"Error sending question {question_index + 1}: {e}")

async def reveal_correct_answer(context, question_index):
    """Reveal the correct answer by editing the message"""
    global weekly_test
    
    if question_index >= len(weekly_test.questions):
        return
        
    question = weekly_test.questions[question_index]
    correct_option = question["correct_option"]
    
    # Create the correct answer text
    correct_text = f"Question {question_index + 1}: {question['question']}\n\n"
    correct_text += "⏱ Time's up! ⏱\n"
    correct_text += f"✅ Correct answer: {question['options'][correct_option]}"
    
    try:
        # Edit the message to show correct answer
        await context.bot.edit_message_text(
            chat_id=CHANNEL_ID,
            message_id=weekly_test.message_ids[question_index],
            text=correct_text
        )
        logger.info(f"Revealed correct answer for question {question_index + 1}")
    except Exception as e:
        logger.error(f"Error revealing answer for question {question_index + 1}: {e}")

async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks (answers)"""
    global weekly_test
    
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    user_name = user.full_name
    
    # Parse the callback data to get question and answer
    callback_data = query.data
    try:
        # Extract question index and answer index from callback data format "q{question_index}_a{answer_index}"
        parts = callback_data.split('_')
        question_index = int(parts[0][1:])  # Remove 'q' prefix
        answer_index = int(parts[1][1:])    # Remove 'a' prefix
        
        # Check if this is the current question
        if weekly_test.active and question_index == weekly_test.current_question_index:
            # Check if the answer is correct
            correct_option = weekly_test.questions[question_index]["correct_option"]
            if answer_index == correct_option:
                weekly_test.add_point(user_id, user_name)
                feedback = "✅ Correct!"
            else:
                feedback = "❌ Wrong!"
                
            # Acknowledge the answer
            await query.answer(feedback)
            logger.info(f"User {user_name} answered question {question_index + 1} with option {answer_index}")
        else:
            # Question timing has passed
            await query.answer("Time's up for this question!")
    except Exception as e:
        logger.error(f"Error handling button click: {e}")
        await query.answer("An error occurred with your answer")

async def send_leaderboard_results(context):
    """Send the leaderboard results in a visually appealing format"""
    global weekly_test
    
    if not weekly_test.active:
        return
    
    results = weekly_test.get_results()
    
    # Create the leaderboard message
    message = "🏆 *WEEKLY TEST RESULTS* 🏆\n\n"
    
    # Display the podium (top 3) 
    if len(results) >= 3:
        # Second place (silver)
        silver_id, silver_data = results[1]
        silver_name = silver_data["name"]
        silver_score = silver_data["score"]
        
        # First place (gold)
        gold_id, gold_data = results[0]
        gold_name = gold_data["name"]
        gold_score = gold_data["score"]
        
        # Third place (bronze)
        bronze_id, bronze_data = results[2]
        bronze_name = bronze_data["name"]
        bronze_score = bronze_data["score"]
        
        # Create the podium display
        message += "      🥇\n"
        message += f"      {gold_name}\n"
        message += f"      {gold_score} pts\n"
        message += "  🥈         🥉\n"
        message += f"  {silver_name}    {bronze_name}\n"
        message += f"  {silver_score} pts    {bronze_score} pts\n\n"
        
        # Other participants
        if len(results) > 3:
            message += "*Other participants:*\n"
            for i, (user_id, data) in enumerate(results[3:], start=4):
                message += f"{i}. {data['name']} - {data['score']} pts\n"
    
    # If we have fewer than 3 participants
    elif len(results) > 0:
        for i, (user_id, data) in enumerate(results, start=1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else ""
            message += f"{medal} {i}. {data['name']} - {data['score']} pts\n"
    else:
        message += "No participants this week."
    
    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=message,
            parse_mode="Markdown"
        )
        logger.info("Leaderboard results sent successfully")
        
        # Reset the test after sending results
        weekly_test.reset()
    except Exception as e:
        logger.error(f"Error sending leaderboard results: {e}")

async def weekly_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command handler for /weeklytest"""
    global weekly_test
    
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID and update.effective_chat.id != CHANNEL_ID:
        await update.message.reply_text("❌ Not authorized")
        return
    
    try:
        # Reset and prepare the test
        weekly_test.reset()
        
        # For testing, use the hardcoded questions
        # In production, you would uncomment the fetch from URL:
        # import requests
        # response = requests.get(os.getenv("WEEKLY_QUESTIONS_JSON_URL"))
        # weekly_test.questions = response.json()
        
        # For testing, use the sample questions
        weekly_test.questions = sample_questions
        weekly_test.active = True
        
        # Start the sequence with the first question
        await update.message.reply_text("Starting weekly test...")
        
        # Send first question with buttons
        await send_question_with_buttons(context, 0)
    
    except Exception as e:
        logger.error(f"Error in weekly test command: {e}")
        await update.message.reply_text("Failed to start weekly test. Check logs for details.")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("weeklytest", weekly_test_command))
    
    # Add callback query handler for button clicks
    application.add_handler(CallbackQueryHandler(handle_button_click))
    
    # Register error handler
    application.add_error_handler(lambda update, context: 
                                 logger.error(f"Error: {context.error}", exc_info=context.error))
    
    # Start the bot
    if WEBHOOK_URL:
        # Run in webhook mode
        logger.info(f"Starting bot in webhook mode on port {PORT}")
        webhook_url = f"{WEBHOOK_URL}/{BOT_TOKEN}"
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=webhook_url
        )
    else:
        # Run in polling mode
        logger.info("Starting bot in polling mode")
        application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
