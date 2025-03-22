import os
import logging
import asyncio
from telegram import Update, Poll, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, PollAnswerHandler, ContextTypes

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
GROUP_ID = int(os.getenv("GROUP_ID", "0"))  # Add a group ID environment variable
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

    def reset(self):
        self.questions = []
        self.current_question_index = 0
        self.participants = {}
        self.active = False
        self.poll_ids = {}

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

async def send_channel_announcement(context, question_index):
    """Send an announcement to the channel with a link to the poll in the group"""
    global weekly_test
    
    if question_index >= len(weekly_test.questions):
        # All questions done
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_leaderboard_results(ctx)),
            60  # Wait 1 minute after the last question
        )
        return
    
    question = weekly_test.questions[question_index]
    weekly_test.current_question_index = question_index
    
    try:
        # First, send the poll to the group where non-anonymous polls work
        poll_message = await context.bot.send_poll(
            chat_id=GROUP_ID,
            question=question["question"],
            options=question["options"],
            type=Poll.QUIZ,
            correct_option_id=question["correct_option"],
            open_period=10,  # 10 seconds
            is_anonymous=False  # Non-anonymous poll in the group
        )
        
        # Store the poll ID for later reference
        weekly_test.poll_ids[poll_message.poll.id] = question_index
        
        # Create a deep link to the poll in the group
        group_username = await get_chat_username(context.bot, GROUP_ID)
        poll_link = f"https://t.me/{group_username}/{poll_message.message_id}"
        
        # Send announcement to the channel with a link to participate
        keyboard = [[InlineKeyboardButton("Answer this question", url=poll_link)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"❓ *Question {question_index + 1}* ❓\n\n{question['question']}\n\n👉 Click below to answer in our group! (10 seconds)",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
        logger.info(f"Question {question_index + 1} sent as a non-anonymous poll in group with channel announcement")
        
        # Schedule the next question
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_channel_announcement(ctx, question_index + 1)),
            12  # Wait 12 seconds before sending next question
        )
        
    except Exception as e:
        logger.error(f"Error sending question {question_index + 1}: {e}")

async def get_chat_username(bot, chat_id):
    """Get the username of a chat for creating deep links"""
    try:
        chat = await bot.get_chat(chat_id)
        if chat.username:
            return chat.username
        else:
            logger.error(f"Chat {chat_id} doesn't have a username for deep linking")
            return None
    except Exception as e:
        logger.error(f"Error getting chat info: {e}")
        return None

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle poll answers and update leaderboard"""
    global weekly_test
    
    if not weekly_test.active:
        return
    
    poll_answer = update.poll_answer
    user_id = poll_answer.user.id
    user = await context.bot.get_chat_member(GROUP_ID, user_id)
    user_name = user.user.full_name
    
    # Get the poll ID to identify which question this is
    poll_id = poll_answer.poll_id
    
    # Check if we're tracking this poll
    if poll_id in weekly_test.poll_ids:
        question_index = weekly_test.poll_ids[poll_id]
        question = weekly_test.questions[question_index]
        
        # Check if the answer is correct
        if poll_answer.option_ids and poll_answer.option_ids[0] == question["correct_option"]:
            weekly_test.add_point(user_id, user_name)
            logger.info(f"User {user_name} answered correctly for question {question_index + 1}")
    
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
        # Send results to both the channel and group
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=message,
            parse_mode="Markdown"
        )
        
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=f"Test completed! See the results in the channel or below:\n\n{message}",
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
        
        # Send first announcement and poll
        await send_channel_announcement(context, 0)
    
    except Exception as e:
        logger.error(f"Error in weekly test command: {e}")
        await update.message.reply_text("Failed to start weekly test. Check logs for details.")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("weeklytest", weekly_test_command))
    
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
