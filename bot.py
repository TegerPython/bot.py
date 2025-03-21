import os
import logging
import asyncio
from telegram import Update, Poll, Bot, PollOption
from telegram.ext import Application, CommandHandler, PollAnswerHandler, ContextTypes

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
        self.poll_ids = {}  # Maps poll_id to question_index
        self.answered_users = {}  # Maps poll_id -> {user_id -> answer_index}

    def reset(self):
        self.questions = []
        self.current_question_index = 0
        self.participants = {}
        self.active = False
        self.poll_ids = {}
        self.answered_users = {}

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

# Poll-based question approach for channels
async def send_poll_questions(context, question_index):
    """Send questions as polls in the channel"""
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
    
    try:
        # Send question as a poll
        message = await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question=f"❓ Question {question_index + 1}: {question['question']}",
            options=question["options"],
            is_anonymous=False,  # Important! We need to know who answered
            allows_multiple_answers=False,
            open_period=10,  # Poll stays open for 10 seconds
            type='quiz',  # Use quiz type so there's a correct answer
            correct_option_id=question["correct_option"],
            explanation=f"The correct answer is: {question['options'][question['correct_option']]}"
        )
        
        # Store poll ID to track answers
        poll_id = message.poll.id
        weekly_test.poll_ids[poll_id] = question_index
        weekly_test.answered_users[poll_id] = {}
        
        logger.info(f"Question {question_index + 1} sent as poll with ID {poll_id}")
        
        # Schedule next question after delay
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_poll_questions(ctx, question_index + 1)),
            15  # Wait 15 seconds before sending next question (10s poll + 5s buffer)
        )
    except Exception as e:
        logger.error(f"Error sending question {question_index + 1}: {e}")

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle poll answers"""
    global weekly_test
    
    poll_answer = update.poll_answer
    user_id = poll_answer.user.id
    user_name = poll_answer.user.full_name
    poll_id = poll_answer.poll_id
    selected_option = poll_answer.option_ids[0] if poll_answer.option_ids else None
    
    # Check if this poll is part of our test
    if poll_id in weekly_test.poll_ids and weekly_test.active:
        question_index = weekly_test.poll_ids[poll_id]
        correct_option = weekly_test.questions[question_index]["correct_option"]
        
        # Track user's answer
        weekly_test.answered_users[poll_id][user_id] = {
            "name": user_name,
            "answer": selected_option
        }
        
        # Check if answer is correct and award point
        if selected_option == correct_option:
            weekly_test.add_point(user_id, user_name)
            logger.info(f"User {user_name} answered correctly for question {question_index + 1}")
        else:
            logger.info(f"User {user_name} answered incorrectly for question {question_index + 1}")

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
    
    # Question statistics
    message += "\n*Question Statistics:*\n"
    for poll_id, question_index in weekly_test.poll_ids.items():
        question = weekly_test.questions[question_index]
        correct_option = question["correct_option"]
        correct_answer = question["options"][correct_option]
        
        total_answers = len(weekly_test.answered_users.get(poll_id, {}))
        correct_count = sum(1 for user_data in weekly_test.answered_users.get(poll_id, {}).values() 
                            if user_data.get("answer") == correct_option)
        
        if total_answers > 0:
            percentage = (correct_count / total_answers) * 100
            message += f"Q{question_index + 1}: {correct_count}/{total_answers} correct ({percentage:.1f}%)\n"
    
    try:
        # Send results to the channel
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=message,
            parse_mode="Markdown"
        )
        
        logger.info("Leaderboard results sent successfully")
        
        # Reset the test after sending results
        weekly_test.active = False
    except Exception as e:
        logger.error(f"Error sending leaderboard results: {e}")

async def weekly_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command handler for /weeklytest - now works with polls"""
    global weekly_test
    
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Not authorized")
        return
    
    try:
        # Verify CHANNEL_ID is set and valid
        if CHANNEL_ID == 0:
            await update.message.reply_text("❌ CHANNEL_ID is not set in environment variables. Please set it and try again.")
            logger.error("CHANNEL_ID environment variable not set")
            return
        
        # Check if bot can access the channel
        try:
            channel_chat = await context.bot.get_chat(CHANNEL_ID)
            logger.info(f"Successfully connected to channel: {channel_chat.title}")
        except Exception as e:
            await update.message.reply_text(f"❌ Cannot access channel with ID {CHANNEL_ID}. Make sure the bot is an admin of the channel and has proper permissions.")
            logger.error(f"Failed to access channel: {e}")
            return
        
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
        await update.message.reply_text(f"Starting weekly test... Questions will be sent to channel: {channel_chat.title}")
        
        # Send first question as poll
        await send_poll_questions(context, 0)
    
    except Exception as e:
        logger.error(f"Error in weekly test command: {e}")
        await update.message.reply_text(f"Failed to start weekly test: {str(e)}")

async def custom_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command handler for /customtest with specific questions"""
    global weekly_test
    
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Not authorized")
        return
    
    try:
        # Custom quiz questions (example)
        custom_questions = [
            {
                "question": "What is the largest planet in our solar system?",
                "options": ["Saturn", "Jupiter", "Neptune", "Uranus"],
                "correct_option": 1
            },
            {
                "question": "Which element has the chemical symbol 'Au'?",
                "options": ["Silver", "Aluminum", "Gold", "Copper"],
                "correct_option": 2
            },
            {
                "question": "Who wrote 'Romeo and Juliet'?",
                "options": ["Charles Dickens", "William Shakespeare", "Jane Austen", "Mark Twain"],
                "correct_option": 1
            }
        ]
        
        # Reset and prepare the test
        weekly_test.reset()
        weekly_test.questions = custom_questions
        weekly_test.active = True
        
        # Start the sequence with the first question
        await update.message.reply_text("Starting custom test...")
        
        # Send first question as poll
        await send_poll_questions(context, 0)
    
    except Exception as e:
        logger.error(f"Error in custom test command: {e}")
        await update.message.reply_text(f"Failed to start custom test: {str(e)}")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("weeklytest", weekly_test_command))
    application.add_handler(CommandHandler("customtest", custom_test_command))
    
    # Add poll answer handler - this is key for the new implementation
    application.add_handler(PollAnswerHandler(handle_poll_answer))
    
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
