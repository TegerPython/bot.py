import os
import logging
import asyncio
from telegram import Update, Poll, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID"))

# Global variables
poll_results_cache = {}

async def send_test_poll(context: ContextTypes.DEFAULT_TYPE):
    try:
        # Send poll
        poll_message = await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question="Test Poll?",
            options=["Yes", "No"],
            type=Poll.QUIZ,
            correct_option_id=0,
            open_period=30,  # 30-second poll
            is_anonymous=False
        )
        
        poll_id = poll_message.poll.id
        message_id = poll_message.message_id
        
        # Store reference for later
        poll_results_cache[poll_id] = {
            "message_id": message_id,
            "question": "Test Poll?",
            "options": ["Yes", "No"],
            "correct_option_id": 0
        }
        
        # Wait for poll to close
        await asyncio.sleep(30)
        
        try:
            # Get final results
            closed_poll = await context.bot.stop_poll(
                chat_id=CHANNEL_ID, 
                message_id=message_id
            )
            
            # Process results
            total_voters = closed_poll.total_voter_count
            correct_votes = closed_poll.options[0].voter_count
            
            # Send summary
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=f"Poll Results:\n"
                     f"Total participants: {total_voters}\n"
                     f"Correct answers: {correct_votes}"
            )
            
        except Exception as e:
            logger.error(f"Error closing poll: {e}")
            
    except Exception as e:
        logger.error(f"Error sending poll: {e}")

async def send_inline_question(context: ContextTypes.DEFAULT_TYPE):
    try:
        # Create inline keyboard
        keyboard = [
            [InlineKeyboardButton("Option A", callback_data="A")],
            [InlineKeyboardButton("Option B", callback_data="B")],
            [InlineKeyboardButton("Option C", callback_data="C")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send question
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="Choose the correct option:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error sending inline question: {e}")

async def handle_inline_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name
    
    # Check if authorized (optional)
    if update.effective_user.id != OWNER_ID:
        # Optional: restrict to specific users
        pass
    
    answer = query.data
    correct_answer = "A"  # Example correct answer
    
    if answer == correct_answer:
        await query.answer("✅ Correct!")
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"✅ {username} answered correctly!"
        )
    else:
        await query.answer("❌ Wrong answer!")
    
    # Remove inline keyboard after answering
    await context.bot.edit_message_reply_markup(
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        reply_markup=None
    )

async def test_poll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    await update.message.reply_text("Sending test poll...")
    await send_test_poll(context)

async def test_inline_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    await update.message.reply_text("Sending inline question...")
    await send_inline_question(context)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("testpoll", test_poll_command))
    application.add_handler(CommandHandler("testinline", test_inline_command))
    application.add_handler(CallbackQueryHandler(handle_inline_answer))
    
    # Run the bot
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
