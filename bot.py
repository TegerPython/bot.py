import os
import logging
import asyncio
from telegram import Update, Bot, Poll
from telegram.ext import Application, CommandHandler, ContextTypes, PollAnswerHandler, MessageHandler, filters

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

# Test data structure
class WeeklyTest:
    def __init__(self):
        self.questions = []
        self.current_question_index = 0
        self.participants = {}  # user_id -> {"name": name, "score": score}
        self.active = False
        self.poll_ids = {}  # question_index -> {"channel": poll_id, "group": poll_id}
        self.poll_messages = {}  # question_index -> {"channel": message_id, "group": message_id}
        self.user_answers = {}  # user_id -> {question_index: option_id}

    def reset(self):
        self.questions = []
        self.current_question_index = 0
        self.participants = {}
        self.active = False
        self.poll_ids = {}
        self.poll_messages = {}
        self.user_answers = {}

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
        # Initialize storage for this question
        weekly_test.poll_ids[question_index] = {}
        weekly_test.poll_messages[question_index] = {}
        
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
        
        # Store channel poll info
        weekly_test.poll_ids[question_index]["channel"] = channel_message.poll.id
        weekly_test.poll_messages[question_index]["channel"] = channel_message.message_id
        
        # 2. Send the same poll to discussion group (non-anonymous)
        group_message = await context.bot.send_poll(
            chat_id=DISCUSSION_GROUP_ID,
            question=f"❓ Question {question_index + 1}: {question['question']}",
            options=question["options"],
            is_anonymous=False,  # Non-anonymous to track users
            protect_content=True,  # Prevent forwarding
            allows_multiple_answers=False
        )
        
        # Store group poll info
        weekly_test.poll_ids[question_index]["group"] = group_message.poll.id
        weekly_test.poll_messages[question_index]["group"] = group_message.message_id
        
        # Send announcement to discussion group linking to the poll
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text=f"⚠️ Answer Question {question_index + 1} in the poll above. You have 15 seconds! Answers will be tracked for the leaderboard."
        )
        
        logger.info(f"Question {question_index + 1} sent to channel and discussion group")
        logger.info(f"Poll IDs for question {question_index + 1}: Channel={channel_message.poll.id}, Group={group_message.poll.id}")
        
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
    """Stop the polls in both channel and discussion group and record correct answers"""
    global weekly_test
    
    if question_index not in weekly_test.poll_messages:
        return
    
    question = weekly_test.questions[question_index]
    correct_option = question["correct_option"]
    
    try:
        # Stop the polls
        if "group" in weekly_test.poll_messages[question_index]:
            await context.bot.stop_poll(
                chat_id=DISCUSSION_GROUP_ID,
                message_id=weekly_test.poll_messages[question_index]["group"]
            )
            logger.info(f"Poll for question {question_index + 1} stopped in discussion group")
        
        if "channel" in weekly_test.poll_messages[question_index]:
            await context.bot.stop_poll(
                chat_id=CHANNEL_ID,
                message_id=weekly_test.poll_messages[question_index]["channel"]
            )
            logger.info(f"Poll for question {question_index + 1} stopped in channel")
        
        # Send correct answer message to discussion group
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text=f"✅ Correct answer: *{question['options'][correct_option]}*",
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logger.error(f"Error stopping polls for question {question_index + 1}: {e}")

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle poll answers and synchronize between channel and group polls"""
    global weekly_test
    
    try:
        poll_answer = update.poll_answer
        poll_id = poll_answer.poll_id
        user_id = poll_answer.user.id
        user_name = poll_answer.user.full_name if hasattr(poll_answer.user, 'full_name') else f"User {user_id}"
        
        logger.info(f"Received poll answer from {user_name} (ID: {user_id}) for poll ID: {poll_id}")
        
        if not weekly_test.active:
            logger.info("Weekly test not active, ignoring poll answer")
            return
        
        # Find which question this poll belongs to and whether it's from channel or group
        question_index = None
        poll_source = None
        
        for idx, poll_ids in weekly_test.poll_ids.items():
            if "channel" in poll_ids and poll_ids["channel"] == poll_id:
                question_index = idx
                poll_source = "channel"
                break
            elif "group" in poll_ids and poll_ids["group"] == poll_id:
                question_index = idx
                poll_source = "group"
                break
        
        if question_index is None:
            logger.warning(f"Poll ID {poll_id} not found in tracked polls")
            return
        
        logger.info(f"Poll answer belongs to question {question_index + 1} from {poll_source}")
        
        # If no option selected (user retracted vote), return
        if not poll_answer.option_ids:
            logger.info(f"User {user_name} retracted their vote")
            return
        
        selected_option = poll_answer.option_ids[0]
        correct_option = weekly_test.questions[question_index]["correct_option"]
        
        # Store user's answer
        if user_id not in weekly_test.user_answers:
            weekly_test.user_answers[user_id] = {}
        
        weekly_test.user_answers[user_id][question_index] = selected_option
        
        # Check if answer is correct
        if selected_option == correct_option:
            weekly_test.add_point(user_id, user_name)
            logger.info(f"User {user_name} answered question {question_index + 1} correctly")
        
        # If answer came from discussion group, we need to put the same answer in the channel poll
        # But this is not possible because channel polls are anonymous
        # Instead, we could track and simulate results for analytics
        
        logger.info(f"User {user_name} selected option {selected_option} for question {question_index + 1}")
        
    except Exception as e:
        logger.error(f"Error handling poll answer: {e}")

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
        
        # Announce test start in discussion group
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
        
        # Announce test start in discussion group
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

async def handle_channel_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle forwarded messages from channel to group"""
    try:
        message = update.message
        
        # Check if this is a forwarded message from our channel
        if message.forward_from_chat and message.forward_from_chat.id == CHANNEL_ID:
            # Delete the forwarded message to avoid duplicates
            await message.delete()
            logger.info(f"Deleted forwarded channel message in discussion group")
    except Exception as e:
        logger.error(f"Error handling forwarded message: {e}")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("weeklytest", weekly_test_command))
    application.add_handler(CommandHandler("customtest", custom_test_command))
    
    # Add poll answer handler
    application.add_handler(PollAnswerHandler(handle_poll_answer))
    
    # Add handler to delete forwarded messages from channel
    application.add_handler(MessageHandler(filters.FORWARDED, handle_channel_forward))
    
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
