import os
import logging
import asyncio
from telegram import Update, Poll, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, PollAnswerHandler, ContextTypes, CallbackQueryHandler

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
        if group_username:
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
        else:
            # Fallback if no username available
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=f"❓ *Question {question_index + 1}* ❓\n\n{question['question']}\n\n👉 Answer in our discussion group! (10 seconds)",
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
        # Try to send an error message to the channel
        try:
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=f"❗ Error sending question {question_index + 1}: {str(e)}"
            )
        except:
            pass

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
    
    try:
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
    except Exception as e:
        logger.error(f"Error handling poll answer: {e}")
    
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
        
        try:
            await context.bot.send_message(
                chat_id=GROUP_ID,
                text=f"Test completed! See the results in the channel or below:\n\n{message}",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error sending results to group: {e}")
        
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
        # Verify GROUP_ID is set and valid
        if GROUP_ID == 0:
            await update.message.reply_text("❌ GROUP_ID is not set in environment variables. Please set it and try again.")
            logger.error("GROUP_ID environment variable not set")
            return
        
        # Check if bot can access the group
        try:
            group_chat = await context.bot.get_chat(GROUP_ID)
            logger.info(f"Successfully connected to group: {group_chat.title}")
        except Exception as e:
            await update.message.reply_text(f"❌ Cannot access group with ID {GROUP_ID}. Make sure the bot is a member of the group and has proper permissions.")
            logger.error(f"Failed to access group: {e}")
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
        await update.message.reply_text(f"Starting weekly test... Polls will be sent to group: {group_chat.title}")
        
        # Send first announcement and poll
        await send_channel_announcement(context, 0)
    
    except Exception as e:
        logger.error(f"Error in weekly test command: {e}")
        await update.message.reply_text(f"Failed to start weekly test: {str(e)}")

# Fallback to using inline keyboard buttons directly in the channel
async def send_button_questions(context, question_index):
    """Alternative approach: Send questions with inline buttons in the channel"""
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
        
        logger.info(f"Question {question_index + 1} sent with inline keyboard")
        
        # Schedule next question after delay
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_button_questions(ctx, question_index + 1)),
            12  # Wait 12 seconds before sending next question
        )
        
        # Schedule removal of buttons after 10 seconds
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(reveal_correct_answer(ctx, message.message_id, question_index)),
            10  # Show correct answer after 10 seconds
        )
    except Exception as e:
        logger.error(f"Error sending question {question_index + 1}: {e}")

async def reveal_correct_answer(context, message_id, question_index):
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
            message_id=message_id,
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

async def fallback_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fallback command handler when group setup fails"""
    global weekly_test
    
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID and update.effective_chat.id != CHANNEL_ID:
        await update.message.reply_text("❌ Not authorized")
        return
    
    try:
        # Reset and prepare the test
        weekly_test.reset()
        weekly_test.questions = sample_questions
        weekly_test.active = True
        
        # Start the sequence with the first question
        await update.message.reply_text("Starting weekly test with inline buttons (fallback mode)...")
        
        # Send first question with buttons
        await send_button_questions(context, 0)
    
    except Exception as e:
        logger.error(f"Error in fallback test command: {e}")
        await update.message.reply_text("Failed to start test in fallback mode. Check logs for details.")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("weeklytest", weekly_test_command))
    application.add_handler(CommandHandler("fallbacktest", fallback_test_command))
    
    # Add poll answer handler
    application.add_handler(PollAnswerHandler(handle_poll_answer))
    
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
