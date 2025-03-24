import asyncio
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Constants
DISCUSSION_GROUP_ID = -1001234567890  # Replace with actual group ID
CHANNEL_ID = -1009876543210  # Replace with actual channel ID
QUESTION_DURATION = 10  # Default question duration in seconds
MAX_QUESTIONS = 3
NEXT_QUESTION_DELAY = 30  # Delay before next question

# Logger setup
logger = logging.getLogger(__name__)

# Function to get the duration for each question
def get_question_duration(question_index):
    """Return the appropriate duration in seconds for the given question index"""
    if question_index == 0:
        return 5  # Question 1: 5 seconds
    elif question_index == 2:
        return 15  # Question 3: 15 seconds
    else:
        return QUESTION_DURATION

# Function to delete forwarded messages from the channel in the group
async def delete_forwarded_channel_message(context, message_text_pattern):
    """Delete forwarded channel message from group that matches the pattern"""
    try:
        messages = await context.bot.get_chat_history(
            chat_id=DISCUSSION_GROUP_ID, limit=10
        )
        
        for message in messages:
            if (message.forward_from_chat and 
                message.forward_from_chat.id == CHANNEL_ID and
                message_text_pattern in message.text):
                
                await context.bot.delete_message(DISCUSSION_GROUP_ID, message.id)
                logger.info(f"Deleted forwarded channel message: {message.id}")
                break
    except Exception as e:
        logger.error(f"Error deleting forwarded channel message: {e}")

# Function to send quiz questions
async def send_question(context, question_index):
    """Send questions to discussion group"""
    global weekly_test
    
    if question_index >= len(weekly_test.questions):
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(send_leaderboard_results(ctx)),
            60,
            name="send_leaderboard"
        )
        return
    
    question = weekly_test.questions[question_index]
    weekly_test.current_question_index = question_index
    question_duration = get_question_duration(question_index)
    
    try:
        await context.bot.set_chat_permissions(
            DISCUSSION_GROUP_ID, permissions={"can_send_messages": False}
        )
        
        group_message = await context.bot.send_poll(
            chat_id=DISCUSSION_GROUP_ID,
            question=f"❓ Question {question_index + 1}: {question['question']}",
            options=question["options"],
            is_anonymous=False,
            protect_content=True,
            allows_multiple_answers=False,
            open_period=question_duration
        )
        
        weekly_test.poll_ids[question_index] = group_message.poll.id
        weekly_test.poll_messages[question_index] = group_message.message_id
        
        chat = await context.bot.get_chat(DISCUSSION_GROUP_ID)
        if not chat.invite_link:
            invite_link = await context.bot.create_chat_invite_link(DISCUSSION_GROUP_ID)
            group_link = invite_link.invite_link
        else:
            group_link = chat.invite_link
        
        if question_index + 1 == 3:
            keyboard = [[InlineKeyboardButton("Join Discussion Group", url=group_link)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=f"🚨 *QUESTION {question_index + 1} IS LIVE!* 🚨\n\n"
                     "Join the discussion group to answer and earn points!\n"
                     "⏱️ Only 15 seconds to answer!",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        else:
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=f"🚨 *QUESTION {question_index + 1} IS LIVE!* 🚨\n\n"
                     "Join the discussion group to answer and earn points!\n"
                     f"⏱️ Only {question_duration} seconds to answer!"
            )
        
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(delete_forwarded_channel_message(
                ctx, f"QUESTION {question_index + 1} IS LIVE")),
            2,
            name="delete_forwarded_message"
        )
        
        if question_index + 1 < min(len(weekly_test.questions), MAX_QUESTIONS):
            context.job_queue.run_once(
                lambda ctx: asyncio.create_task(send_question(ctx, question_index + 1)),
                NEXT_QUESTION_DELAY,
                name="next_question"
            )
        else:
            context.job_queue.run_once(
                lambda ctx: asyncio.create_task(send_leaderboard_results(ctx)),
                question_duration + 5,
                name="send_leaderboard"
            )
        
        context.job_queue.run_once(
            lambda ctx: asyncio.create_task(stop_poll_and_check_answers(ctx, question_index)),
            question_duration,
            name=f"stop_poll_{question_index}"
        )
    except Exception as e:
        logger.error(f"Error sending question {question_index + 1}: {e}")

# Function to stop poll and reveal correct answer
async def stop_poll_and_check_answers(context, question_index):
    """Stop the poll in discussion group and post correct answer"""
    global weekly_test
    
    if question_index not in weekly_test.poll_messages:
        return
    
    question = weekly_test.questions[question_index]
    correct_option = question["correct_option"]
    
    try:
        await context.bot.stop_poll(
            chat_id=DISCUSSION_GROUP_ID,
            message_id=weekly_test.poll_messages[question_index]
        )
        
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text=f"✅ *CORRECT ANSWER* ✅\n\n"
                 f"Question {question_index + 1}: {question['question']}\n"
                 f"Correct answer: *{question['options'][correct_option]}*",
            parse_mode="Markdown"
        )
        
        if question_index + 1 >= min(len(weekly_test.questions), MAX_QUESTIONS):
            await context.bot.set_chat_permissions(
                DISCUSSION_GROUP_ID, permissions={"can_send_messages": True}
            )
        
        logger.info(f"Poll for question {question_index + 1} stopped")
    except Exception as e:
        if "Poll has already been closed" not in str(e):
            logger.error(f"Error stopping poll for question {question_index + 1}: {e}")
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

# Function to delete forwarded channel message from the group
async def delete_forwarded_channel_message(context, message_text_pattern):
    """Delete forwarded channel message from group that matches the pattern"""
    try:
        # Get recent messages from the group
        messages = await context.bot.get_chat_history(
            chat_id=DISCUSSION_GROUP_ID,
            limit=10
        )
        
        for message in messages:
            # Check if message is forwarded from channel and matches pattern
            if (message.forward_from_chat and 
                message.forward_from_chat.id == CHANNEL_ID and
                message_text_pattern in message.text):
                
                # Delete the message
                await context.bot.delete_message(DISCUSSION_GROUP_ID, message.id)
                logger.info(f"Deleted forwarded channel message: {message.id}")
                break
    except Exception as e:
        logger.error(f"Error deleting forwarded channel message: {e}")

# Main function to run the quiz flow
async def start_quiz(context):
    global weekly_test
    
    if not weekly_test.active:
        logger.info("Test was stopped. Cancelling remaining questions.")
        return
    
    # Send first question
    await send_question(context, 0)

# Setup job for sending quiz
def schedule_quiz(context):
    context.job_queue.run_once(lambda ctx: asyncio.create_task(start_quiz(ctx)), 0, name="start_quiz")

# Schedule job for each question based on intervals
def schedule_questions(context):
    for i in range(len(weekly_test.questions)):
        context.job_queue.run_once(lambda ctx, i=i: asyncio.create_task(send_question(ctx, i)),
                                   QUESTION_INTERVAL * i, name=f"question_{i}")

# Function to send leaderboard results
async def send_leaderboard_results(context):
    global weekly_test
    
    if not weekly_test.active:
        logger.info("Leaderboard not sent. Test was stopped.")
        return
    
    leaderboard = sorted(weekly_test.players.items(), key=lambda x: x[1], reverse=True)
    leaderboard_text = "🏆 **Leaderboard** 🏆\n\n"
    
    for idx, (player, score) in enumerate(leaderboard, 1):
        leaderboard_text += f"{idx}. {player}: {score} points\n"
    
    await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=leaderboard_text,
        parse_mode="Markdown"
    )
    logger.info("Leaderboard sent")

# Function to handle sending messages to the discussion group
async def send_message_to_group(context, text):
    try:
        await context.bot.send_message(
            chat_id=DISCUSSION_GROUP_ID,
            text=text
        )
    except Exception as e:
        logger.error(f"Error sending message to group: {e}")

# Function to check the bot status and send a DM update
async def send_status_update(context):
    try:
        await context.bot.send_message(
            chat_id=USER_ID,  # The user's ID for DM updates
            text="✅ The bot is running successfully! ✅"
        )
    except Exception as e:
        logger.error(f"Error sending status update: {e}")
# Function to handle remote control commands via Telegram DMs
async def handle_remote_commands(update, context):
    command = update.message.text.lower()
    
    if command.startswith("/run"):
        await context.bot.send_message(update.message.chat.id, "Running the bot...")
        # Code to run the bot here
        await start_quiz(context)
    elif command.startswith("/kill"):
        await context.bot.send_message(update.message.chat.id, "Stopping the bot...")
        # Code to stop the bot here
        # Perform necessary cleanup actions before stopping the bot
        weekly_test.active = False
    elif command.startswith("/status"):
        await send_status_update(context)
    elif command.startswith("/update"):
        # Extract code from the message
        code = command[7:].strip()
        if code:
            await context.bot.send_message(update.message.chat.id, "Updating bot with new code...")
            # Code to update the bot
            # Example: update the bot code or handle the update functionality here
        else:
            await context.bot.send_message(update.message.chat.id, "Please provide the new code.")
    else:
        await context.bot.send_message(update.message.chat.id, "Unknown command. Try /run, /kill, /status, or /update <new_code>.")

# Main entry point to start the bot
def main():
    # Initialize the updater
    updater = Updater(TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    # Command handlers
    dispatcher.add_handler(CommandHandler("start", start_quiz))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_remote_commands))

    # Add job to handle quiz schedule
    job_queue = updater.job_queue
    job_queue.run_repeating(schedule_questions, interval=QUESTION_INTERVAL * 60, first=0)

    # Start the bot
    updater.start_polling()

    # Set up idle to stop gracefully
    updater.idle()

if __name__ == '__main__':
    main()


