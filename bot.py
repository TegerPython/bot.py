import os
import logging
import asyncio
import json
import aiohttp
import pytz
from datetime import datetime, timedelta
from telegram import Update, Bot, Poll, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, PollAnswerHandler, CallbackQueryHandler, filters, MessageHandler

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0"))
DISCUSSION_GROUP_ID = int(os.getenv("DISCUSSION_GROUP_ID", "0"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8443"))
WEEKLY_LEADERBOARD_JSON_URL = os.getenv("WEEKLY_LEADERBOARD_JSON_URL")
WEEKLY_QUESTIONS_JSON_URL = os.getenv("WEEKLY_QUESTIONS_JSON_URL")

# Constants - MODIFIED FOR TESTING
QUESTION_DURATIONS = {
    1: 5,  # Question 1 has 5 seconds
    3: 15  # Question 3 has 15 seconds
}
NEXT_QUESTION_DELAY = 10  # seconds (changed from 35 to 10 for testing)
MAX_QUESTIONS = 3  # New constant to limit number of questions for testing

# Leaderboard library to store points
leaderboard_library = {}

class WeeklyTest:
    def __init__(self):
        self.questions = []
        self.current_question_index = 0
        self.participants = {}  # user_id -> {"name": name, "score": score}
        self.active = False
        self.poll_ids = {}  # question_index -> poll_id
        self.poll_messages = {}  # question_index -> poll_message_id
        self.scheduled = False
        self.scheduled_time = None
        self.channel_messages_to_delete = []  # Store message IDs to delete

    def reset(self):
        self.questions = []
        self.current_question_index = 0
        self.participants = {}
        self.active = False
        self.poll_ids = {}
        self.poll_messages = {}
        self.scheduled = False
        self.scheduled_time = None
        self.channel_messages_to_delete = []

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

async def fetch_questions_from_url():
    """Fetch questions from external JSON URL"""
    try:
        if not WEEKLY_QUESTIONS_JSON_URL:
            logger.error("WEEKLY_QUESTIONS_JSON_URL not set")
            return []
            
        async with aiohttp.ClientSession() as session:
            async with session.get(WEEKLY_QUESTIONS_JSON_URL) as response:
                if response.status == 200:
                    text_content = await response.text()
                    try:
                        data = json.loads(text_content)
                        logger.info(f"Fetched {len(data)} questions from external source")
                        return data[:MAX_QUESTIONS]
                    except json.JSONDecodeError as je:
                        logger.error(f"JSON parsing error: {je}, content: {text_content[:100]}...")
                        return []
                else:
                    logger.error(f"Failed to fetch questions: HTTP {response.status}")
                    return []
    except Exception as e:
        logger.error(f"Error fetching questions: {e}")
        return []

async def send_channel_announcement(context):
    """Send announcement to channel with button to join discussion group"""
    try:
        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        if not chat.invite_link:
            invite_link = await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)
            group_link = invite_link.invite_link
        else:
            group_link = chat.invite_link
            
        keyboard = [
            [InlineKeyboardButton("🏆 Join & Participate!", url=group_link)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="📢 *WEEKLY TEST ANNOUNCEMENT* 📢\n\n"
                 "A new weekly test will start in 5 minutes!\n\n"
                 "📌 *Want to earn points and compete in the leaderboard?*\n"
                 "👉 Join our discussion group by clicking the button below\n"
                 "🏅 Only answers in the discussion group count toward your score!\n\n"
                 "⏰ Test begins in 5 minutes. Get ready!",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        
        logger.info("Channel announcement with group join button sent successfully")
        
    except Exception as e:
        logger.error(f"Error sending channel announcement: {e}")

async def delete_forwarded_channel_message(context, message_text_pattern):
    """Delete forwarded channel message from group that matches the pattern"""
    try:
        # Use get_updates to get recent messages (alternative approach)
        messages = await context.bot.get_chat_history(DISCUSSION_GROUP_ID, limit=10)
        
        async for message in messages:
            # Check if message is forwarded from channel and matches pattern
            if (message.forward_from_chat and 
                message.forward_from_chat.id == CHANNEL_ID and
                message.text and message_text_pattern in message.text):
                
                await context.bot.delete_message(DISCUSSION_GROUP_ID, message.message_id)
                logger.info(f"Deleted forwarded channel message: {message.message_id}")
                break
    except Exception as e:
        logger.error(f"Error deleting forwarded channel message: {e}")

async def send_question(context, question_index):
    """Send questions to discussion group only"""
    global weekly_test
    
    if not weekly_test.active:
        logger.info("Test was stopped. Cancelling remaining questions.")
        return
    
    if question_index >= len(weekly_test.questions):
        logger.info("All questions sent, scheduling leaderboard results")
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_leaderboard_results(ctx)),
            60,  # Wait 1 minute after the last question
            name="send_leaderboard"
        )
        return
    
    question = weekly_test.questions[question_index]
    weekly_test.current_question_index = question_index
    
    try:
        # Set chat permissions to restrict member messaging during quiz
        await context.bot.set_chat_permissions(
            DISCUSSION_GROUP_ID,
            permissions={"can_send_messages": False}
        )
        
        # Get the duration for this question (default to 5 seconds if not specified)
        question_number = question_index + 1
        duration = QUESTION_DURATIONS.get(question_number, 5)
        
        # Send question to discussion group (non-anonymous)
        group_message = await context.bot.send_poll(
            chat_id=DISCUSSION_GROUP_ID,
            question=f"❓ Question {question_number}: {question['question']}",
            options=question["options"],
            is_anonymous=False,
            protect_content=True,
            allows_multiple_answers=False,
            open_period=duration  # Set timer for poll to auto-close
        )
        
        # Store the poll information
        weekly_test.poll_ids[question_index] = group_message.poll.id
        weekly_test.poll_messages[question_index] = group_message.message_id
        
        # Notify channel that a question is live in the group
        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        if not chat.invite_link:
            invite_link = await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)
            group_link = invite_link.invite_link
        else:
            group_link = chat.invite_link
        
        # Different handling for Question 1 and Question 3
        if question_number == 1:
            # For Question 1, send message and schedule deletion
            channel_message = await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=f"🚨 *QUESTION {question_number} IS LIVE!* 🚨\n\n"
                     f"Join the discussion group to answer and earn points!\n"
                     f"⏱️ Only {duration} seconds to answer!"
            )
            
            # Schedule deletion of the forwarded channel message from the group
            context.job_queue.run_once(
                lambda ctx: asyncio.create_task(delete_forwarded_channel_message(
                    ctx, f"QUESTION {question_number} IS LIVE")),
                2,
                name="delete_forwarded_message"
            )
            
        elif question_number == 3:
            # For Question 3, send message with button
            keyboard = [
                [InlineKeyboardButton("Join Discussion Group", url=group_link)]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=f"🚨 *QUESTION {question_number} IS LIVE!* 🚨\n\n"
                     f"Join the discussion group to answer and earn points!\n"
                     f"⏱️ You have {duration} seconds to answer!",
                reply_markup=reply_markup
            )
        else:
            # For other questions, just send regular message
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=f"🚨 *QUESTION {question_number} IS LIVE!* 🚨\n\n"
                     f"Join the discussion group to answer and earn points!\n"
                     f"⏱️ Only {duration} seconds to answer!"
            )
        
        logger.info(f"Question {question_number} sent to discussion group")
        
        # Schedule next question after delay or end if we've reached MAX_QUESTIONS
        if question_index + 1 < min(len(weekly_test.questions), MAX_QUESTIONS):
            context.job_queue.run_once(
                lambda ctx: asyncio.create_task(send_question(ctx, question_index + 1)),
                NEXT_QUESTION_DELAY,
                name="next_question"
            )
        else:
            context.job_queue.run_once(
                lambda ctx: asyncio.create_task(send_leaderboard_results(ctx)),
                duration + 5,
                name="send_leaderboard"
            )
        
        # Schedule poll closure and restoring chat permissions
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(stop_poll_and_check_answers(ctx, question_index)),
            duration,
            name=f"stop_poll_{question_index}"
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
        # Poll should auto-close due to open_period, but we'll stop it explicitly too
        poll = await context.bot.stop_poll(
            chat_id=DISCUSSION_GROUP_ID,
            message_id=weekly_test.poll_messages[question_index]
        )
        
        # Send correct answer message to discussion group only
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text=f"✅ Correct answer: *{question['options'][correct_option]}*",
            parse_mode="Markdown"
        )
        
        # Restore chat permissions if this is the last question
        if question_index + 1 >= min(len(weekly_test.questions), MAX_QUESTIONS):
            await context.bot.set_chat_permissions(
                DISCUSSION_GROUP_ID,
                permissions={"can_send_messages": True}
            )
            
        logger.info(f"Poll for question {question_index + 1} stopped")
    except Exception as e:
        if "Poll has already been closed" not in str(e):
            logger.error(f"Error stopping poll for question {question_index + 1}: {e}")

# [Previous handler functions remain the same...]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages in the group to auto-delete specific messages"""
    try:
        # Check if message is in the discussion group and contains the specific text
        if (update.effective_chat.id == DISCUSSION_GROUP_ID and 
            "🚨 *QUESTION 1 IS LIVE!* 🚨" in update.message.text):
            
            # Delete the message immediately
            await context.bot.delete_message(
                chat_id=DISCUSSION_GROUP_ID,
                message_id=update.message.message_id
            )
            logger.info(f"Deleted message with QUESTION 1 announcement")
            
    except Exception as e:
        logger.error(f"Error handling message: {e}")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("weeklytest", weekly_test_command, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("scheduletest", schedule_test_command, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("stopweekly", stop_weekly_test_command, filters=filters.ChatType.PRIVATE))
    
    # Add message handler for auto-deleting messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Add poll answer handler
    application.add_handler(PollAnswerHandler(handle_poll_answer))
    
    # Add callback query handler for buttons
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    
    # Register error handler
    application.add_error_handler(lambda update, context: 
                                 logger.error(f"Error: {context.error}", exc_info=context.error))
    
    # Schedule initial weekly test
    application.job_queue.run_once(
        lambda ctx: asyncio.create_task(schedule_weekly_test(ctx)),
        1,
        name="schedule_weekly_test"
    )
    
    # Start the bot
    if WEBHOOK_URL:
        logger.info(f"Starting bot in webhook mode on port {PORT}")
        webhook_url = f"{WEBHOOK_URL}/{BOT_TOKEN}"
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=webhook_url
        )
    else:
        logger.info("Starting bot in polling mode")
        application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
