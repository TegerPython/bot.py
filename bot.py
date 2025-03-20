import os
import json
import logging
import asyncio
from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, PollAnswerHandler, ContextTypes

# Leaderboard data structure
class WeeklyLeaderboard:
    def __init__(self):
        self.participants = {}  # user_id -> {"name": name, "score": score}
        self.current_questions = []
        self.current_poll_id = None  # Track the ID of the current active poll
        self.question_index = 0  # Track which question we're on
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
        self.question_index = 0
        self.current_poll_id = None
        self.active = False

# Global leaderboard instance
leaderboard = WeeklyLeaderboard()

async def send_poll_with_delay(context, question_index):
    """Send a single poll with proper timing"""
    global leaderboard
    
    if question_index >= len(leaderboard.current_questions):
        # All questions sent, schedule leaderboard post
        logging.info("All questions sent, scheduling leaderboard results in 60 seconds")
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_leaderboard_results(ctx)),
            60  # Wait 1 minute after the last question
        )
        return
    
    question = leaderboard.current_questions[question_index]
    logging.info(f"Sending question {question_index+1}: {question['question']}")
    
    try:
        # Send poll
        message = await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question=question["question"],
            options=question["options"],
            type=Poll.QUIZ,
            correct_option_id=question["correct_option"],
            open_period=20,  # 20 seconds to answer
            is_anonymous=True  # Important: Set to False to track user answers
        )
        
        # Store the poll ID so we can match answers to the current question
        leaderboard.current_poll_id = message.poll.id
        leaderboard.question_index = question_index
        
        logging.info(f"Poll {question_index+1} sent with poll_id: {leaderboard.current_poll_id}")
        
        # Schedule next poll after this one completes (wait for open_period + 2 seconds)
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_poll_with_delay(ctx, question_index + 1)), 
            25  # Wait for poll duration (20s) plus a 5-second gap
        )
    except Exception as e:
        logging.error(f"Error sending poll {question_index+1}: {e}")

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle poll answers and update leaderboard"""
    global leaderboard
    
    if not leaderboard.active:
        return
    
    poll_answer = update.poll_answer
    
    # Check if this answer is for our current poll
    if poll_answer.poll_id != leaderboard.current_poll_id:
        logging.info(f"Received answer for a different poll: {poll_answer.poll_id}")
        return
    
    user_id = poll_answer.user.id
    user_name = poll_answer.user.first_name
    
    # Get the full name if available
    if poll_answer.user.last_name:
        user_name += f" {poll_answer.user.last_name}"
    
    logging.info(f"User {user_name} (ID: {user_id}) answered poll {poll_answer.poll_id}")
    
    # Check if the answer is correct
    if leaderboard.question_index < len(leaderboard.current_questions):
        correct_option = leaderboard.current_questions[leaderboard.question_index]["correct_option"]
        
        # Check if user selected the correct option
        if poll_answer.option_ids and poll_answer.option_ids[0] == correct_option:
            leaderboard.add_point(user_id, user_name)
            logging.info(f"User {user_name} answered correctly for question {leaderboard.question_index+1}")
        else:
            logging.info(f"User {user_name} answered incorrectly for question {leaderboard.question_index+1}")

async def send_leaderboard_results(context):
    """Send the leaderboard results in a visually appealing format"""
    global leaderboard
    
    if not leaderboard.active:
        return
    
    results = leaderboard.get_results()
    logging.info(f"Sending leaderboard results with {len(results)} participants")
    
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
        message += f"      {gold_score} pts\n\n"
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
    
    # Check authorization
    if user_id != OWNER_ID and update.effective_chat.id != CHANNEL_ID:
        await update.message.reply_text("❌ Not authorized")
        return
    
    try:
        # Reset and prepare the leaderboard
        leaderboard.reset()
        
        # Load just 3 test questions
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
        await update.message.reply_text("Starting weekly test with 3 questions...")
        
        # Send first poll and let the chain continue
        await send_poll_with_delay(context, 0)
    
    except Exception as e:
        logging.error(f"Error in weekly test command: {e}")
        await update.message.reply_text("Failed to start weekly test. Check logs for details.")

def main():
    # Set up logging
    logging.basicConfig(level=logging.INFO, 
                      format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Define environment variables
    global BOT_TOKEN, CHANNEL_ID, OWNER_ID, WEBHOOK_URL, PORT
    
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
    OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0"))
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    PORT = int(os.getenv("PORT", "8443"))
    
    if not BOT_TOKEN:
        logging.error("TELEGRAM_BOT_TOKEN environment variable not set!")
        return
    
    # Set up your bot
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("weeklytest", weekly_test_command))
    
    # Add poll answer handler - IMPORTANT: Use PollAnswerHandler, not PollHandler
    application.add_handler(PollAnswerHandler(handle_poll_answer))
    
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
    main()
