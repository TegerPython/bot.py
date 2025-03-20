import os
import json
import logging
import asyncio
import datetime
from telegram import Update, Poll, User
from telegram.ext import Application, CommandHandler, PollHandler, ContextTypes

# Leaderboard data structure
class WeeklyLeaderboard:
    def __init__(self):
        self.participants = {}  # user_id -> {"name": name, "score": score}
        self.current_questions = []
        self.answered_questions = 0
        self.active = False
    
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
    
    def reset(self):
        self.participants = {}
        self.answered_questions = 0
        self.active = False

# Global leaderboard instance
leaderboard = WeeklyLeaderboard()

async def send_poll_with_delay(context, question_index):
    """Send a single poll with proper timing"""
    global leaderboard
    
    if question_index >= len(leaderboard.current_questions):
        # All questions sent, schedule leaderboard post
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_leaderboard_results(ctx)),
            60  # Wait 1 minute after the last question
        )
        return
    
    question = leaderboard.current_questions[question_index]
    logging.info(f"Sending question {question_index+1}: {question['question']}")
    
    try:
        # Send poll
        await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question=question["question"],
            options=question["options"],
            type=Poll.QUIZ,
            correct_option_id=question["correct_option"],
            open_period=5,  # 5 seconds
            is_anonymous=True
        )
        
        logging.info(f"Poll {question_index+1} sent, scheduling next poll")
        
        # Schedule next poll after this one completes
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_poll_with_delay(ctx, question_index + 1)), 
            7  # Wait 7 seconds before sending next poll
        )
    except Exception as e:
        logging.error(f"Error sending poll {question_index+1}: {e}")

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle poll answers and update leaderboard"""
    global leaderboard
    
    if not leaderboard.active:
        return
    
    poll_answer = update.poll_answer
    user_id = poll_answer.user.id
    user_name = poll_answer.user.full_name
    
    # Check if the answer is correct
    question_index = leaderboard.answered_questions
    if question_index < len(leaderboard.current_questions):
        correct_option = leaderboard.current_questions[question_index]["correct_option"]
        if poll_answer.option_ids and poll_answer.option_ids[0] == correct_option:
            leaderboard.add_point(user_id, user_name)
            logging.info(f"User {user_name} answered correctly for question {question_index+1}")
    
    leaderboard.answered_questions += 1

async def send_leaderboard_results(context):
    """Send the leaderboard results in a visually appealing format"""
    global leaderboard
    
    if not leaderboard.active:
        return
    
    results = leaderboard.get_results()
    
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
        logging.info("Leaderboard results sent successfully")
    except Exception as e:
        logging.error(f"Error sending leaderboard results: {e}")
    
    # Reset the leaderboard for next time
    leaderboard.reset()

async def weekly_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command handler for /weeklytest"""
    global leaderboard
    
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID and update.effective_chat.id != CHANNEL_ID:
        await update.message.reply_text("❌ Not authorized")
        return
    
    # Load questions from JSON URL
    try:
        # Reset and prepare the leaderboard
        leaderboard.reset()
        
        # For testing, use the hardcoded questions
        # In production, you would uncomment the fetch from URL:
        # import requests
        # response = requests.get(os.getenv("WEEKLY_QUESTIONS_JSON_URL"))
        # questions = response.json()
        
        # For testing, use the hardcoded questions
        questions = [
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
        
        leaderboard.current_questions = questions
        leaderboard.active = True
        
        # Start the sequence with the first question
        await update.message.reply_text("Starting weekly test...")
        
        # Send first poll and let the chain continue
        await send_poll_with_delay(context, 0)
    
    except Exception as e:
        logging.error(f"Error in weekly test command: {e}")
        await update.message.reply_text("Failed to start weekly test. Check logs for details.")

def main():
    # Set up your bot as before
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("weeklytest", weekly_test_command))
    
    # Add poll answer handler
    application.add_handler(PollHandler(handle_poll_answer))
    
    # Register error handler
    application.add_error_handler(lambda update, context: 
                                 logging.error(f"Error: {context.error}", exc_info=context.error))
    
    # Start the bot
    if WEBHOOK_URL:
        # Run in webhook mode
        logging.info(f"Starting bot in webhook mode on port {PORT}")
        webhook_url = f"{WEBHOOK_URL}/{BOT_TOKEN}"
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=webhook_url
        )
    else:
        # Run in polling mode
        logging.info("Starting bot in polling mode")
        application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(level=logging.INFO, 
                      format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Define environment variables
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
    OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0"))
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    PORT = int(os.getenv("PORT", "8443"))
    
    main()
