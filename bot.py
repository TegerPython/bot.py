import os
import logging
import asyncio
from telegram import Update, Bot, Poll
from telegram.ext import Application, CommandHandler, ContextTypes, PollAnswerHandler

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0"))
DISCUSSION_GROUP_ID = int(os.getenv("DISCUSSION_GROUP_ID", "0"))  # Add discussion group ID
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8443"))

# Test data structure
class WeeklyTest:
    def __init__(self):
        self.questions = []
        self.current_question_index = 0
        self.participants = {}  # user_id -> {"name": name, "score": score}
        self.active = False
        self.poll_ids = {}  # question_index -> poll_id
        self.poll_messages = {}  # question_index -> poll_message_id (in discussion group)

    def reset(self):
        self.questions = []
        self.current_question_index = 0
        self.participants = {}
        self.active = False
        self.poll_ids = {}
        self.poll_messages = {}

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

async def send_question(context, question_index):
    """Send questions to both channel and discussion group"""
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
        # 1. Send question to channel (anonymous poll)
        channel_message = await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question=f"❓ Question {question_index + 1}: {question['question']}",
            options=question["options"],
            is_anonymous=True,  # Must be true for channels
            type=Poll.QUIZ,
            correct_option_id=question["correct_option"],
            explanation=f"The correct answer is: {question['options'][question['correct_option']]}",
            open_period=15  # Close after 15 seconds
        )
        
        # 2. Send the same poll to discussion group (non-anonymous)
        group_message = await context.bot.send_poll(
            chat_id=DISCUSSION_GROUP_ID,
            question=f"❓ Question {question_index + 1}: {question['question']}",
            options=question["options"],
            is_anonymous=False,  # Non-anonymous to track users
            protect_content=True,  # Prevent forwarding
            allows_multiple_answers=False
        )
        
        # Store the poll information
        weekly_test.poll_ids[question_index] = group_message.poll.id
        weekly_test.poll_messages[question_index] = group_message.message_id
        
        # Send announcement to discussion group linking to the question
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text=f"⚠️ Answer Question {question_index + 1} in the poll above. You have 15 seconds! Answers will be tracked for the leaderboard."
        )
        
        logger.info(f"Question {question_index + 1} sent to channel and discussion group")
        logger.info(f"Poll ID for question {question_index + 1}: {group_message.poll.id}")
        
        # Schedule next question after delay
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_question(ctx, question_index + 1)),
            20  # Send next question after 20 seconds
        )
        
        # Schedule poll closure in discussion group
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(stop_poll_and_check_answers(ctx, question_index)),
            15  # Close poll after 15 seconds
        )
    except Exception as e:
        logger.error(f"Error sending question {question_index + 1}: {e}")

async def stop_poll_and_check_answers(context, question_index):
    """Stop the poll in discussion group and record correct answers"""
    global weekly_test
    
    if question_index not in weekly_test.poll_messages:
        return
    
    question = weekly_test.questions[question_index]
    correct_option = question["correct_option"]
    
    try:
        # Stop the poll
        poll = await context.bot.stop_poll(
            chat_id=DISCUSSION_GROUP_ID,
            message_id=weekly_test.poll_messages[question_index]
        )
        
        # Send correct answer message
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text=f"✅ Correct answer: *{question['options'][correct_option]}*",
            parse_mode="Markdown"
        )
        
        logger.info(f"Poll for question {question_index + 1} stopped")
    except Exception as e:
        logger.error(f"Error stopping poll for question {question_index + 1}: {e}")

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle poll answers from discussion group members"""
    global weekly_test
    
    try:
        poll_answer = update.poll_answer
        poll_id = poll_answer.poll_id
        
        # Debug logging
        logger.info(f"Received poll answer for poll ID: {poll_id}")
        logger.info(f"Current active poll IDs: {weekly_test.poll_ids}")
        
        if not weekly_test.active:
            logger.info("Weekly test not active, ignoring poll answer")
            return
        
        # Find which question this poll belongs to
        question_index = None
        for idx, p_id in weekly_test.poll_ids.items():
            if p_id == poll_id:
                question_index = idx
                break
        
        if question_index is None:
            logger.warning(f"Poll ID {poll_id} not found in tracked polls")
            return
        
        # Get user information
        user_id = poll_answer.user.id
        user_name = poll_answer.user.full_name if hasattr(poll_answer.user, 'full_name') else f"User {user_id}"
        
        logger.info(f"Processing answer from user {user_name} (ID: {user_id})")
        
        # Check if the user answered correctly
        if poll_answer.option_ids:
            selected_option = poll_answer.option_ids[0]
            correct_option = weekly_test.questions[question_index]["correct_option"]
            
            logger.info(f"User selected option {selected_option}, correct is {correct_option}")
            
            if selected_option == correct_option:
                weekly_test.add_point(user_id, user_name)
                logger.info(f"User {user_name} answered question {question_index + 1} correctly")
    except Exception as e:
        logger.error(f"Error handling poll answer: {e}")

async def send_leaderboard_results(context):
    """Send the leaderboard results in a visually appealing format"""
    global weekly_test
    
    if not weekly_test.active:
        return
    
    results = weekly_test.get_results()
    logger.info(f"Preparing leaderboard with {len(results)} participants")
    
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
        # Send results to channel only
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
    """Command handler for /weeklytest"""
    global weekly_test
    
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Not authorized")
        return
    
    try:
        # Verify CHANNEL_ID and DISCUSSION_GROUP_ID are set
        if CHANNEL_ID == 0 or DISCUSSION_GROUP_ID == 0:
            await update.message.reply_text("❌ CHANNEL_ID or DISCUSSION_GROUP_ID not set in environment variables.")
            logger.error("Required environment variables not set")
            return
        
        # Reset and prepare the test
        weekly_test.reset()
        weekly_test.questions = sample_questions
        weekly_test.active = True
        
        # Start the sequence with the first question
        await update.message.reply_text("Starting weekly test...")
        
        # Send announcement to discussion group
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text="🎮 *WEEKLY TEST STARTING* 🎮\n\nAnswer the questions that will appear here to participate in the leaderboard!",
            parse_mode="Markdown"
        )
        
        # Send first question
        await send_question(context, 0)
    
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
        
        # Send announcement to discussion group
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text="🎮 *CUSTOM TEST STARTING* 🎮\n\nAnswer the questions that will appear here to participate in the leaderboard!",
            parse_mode="Markdown"
        )
        
        # Send first question
        await send_question(context, 0)
    
    except Exception as e:
        logger.error(f"Error in custom test command: {e}")
        await update.message.reply_text(f"Failed to start custom test: {str(e)}")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("weeklytest", weekly_test_command))
    application.add_handler(CommandHandler("customtest", custom_test_command))
    
    # Add poll answer handler
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
