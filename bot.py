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
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8443"))

# Global variables
poll_results_cache = {}

async def send_test_poll(context: ContextTypes.DEFAULT_TYPE):
    try:
        poll_message = await context.bot.send_poll(
            chat_id=CHANNEL_ID,
            question="Test Poll?",
            options=["Yes", "No"],
            type=Poll.QUIZ,
            correct_option_id=0,
            open_period=30,
            is_anonymous=False
        )
        
        poll_id = poll_message.poll.id
        message_id = poll_message.message_id
        
        logger.info(f"Poll sent successfully. ID: {poll_id}, Message ID: {message_id}")
        
        # Schedule poll closing
        context.job_queue.run_once(close_poll, 30, data={'message_id': message_id})
        
    except Exception as e:
        logger.error(f"Error sending poll: {e}")

async def close_poll(context: ContextTypes.DEFAULT_TYPE):
    message_id = context.job.data.get('message_id')
    try:
        closed_poll = await context.bot.stop_poll(
            chat_id=CHANNEL_ID, 
            message_id=message_id
        )
        
        logger.info(f"Poll closed. Results: {closed_poll.options}")
        
        # Send summary
        total_voters = closed_poll.total_voter_count
        correct_votes = closed_poll.options[0].voter_count if closed_poll.options else 0
        
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"Poll Results:\nTotal participants: {total_voters}\nCorrect answers: {correct_votes}"
        )
    except Exception as e:
        logger.error(f"Error closing poll: {e}")

async def send_inline_question(context: ContextTypes.DEFAULT_TYPE):
    try:
        keyboard = [
            [InlineKeyboardButton("Option A", callback_data="A")],
            [InlineKeyboardButton("Option B", callback_data="B")],
            [InlineKeyboardButton("Option C", callback_data="C")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text="Choose the correct option:",
            reply_markup=reply_markup
        )
        
        logger.info(f"Inline question sent successfully. Message ID: {message.message_id}")
    except Exception as e:
        logger.error(f"Error sending inline question: {e}")

async def handle_inline_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Acknowledge the callback query
    
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name
    answer = query.data
    correct_answer = "A"  # Example correct answer
    
    try:
        if answer == correct_answer:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"✅ {username} answered correctly!"
            )
        else:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"❌ {username} answered incorrectly. The correct answer is {correct_answer}."
            )
        
        # Remove inline keyboard
        await context.bot.edit_message_reply_markup(
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            reply_markup=None
        )
    except Exception as e:
        logger.error(f"Error handling inline answer: {e}")

async def test_poll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Not authorized")
        return
    
    await update.message.reply_text("Sending test poll...")
    await send_test_poll(context)

async def test_inline_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Not authorized")
        return
    
    await update.message.reply_text("Sending inline question...")
    await send_inline_question(context)

async def set_webhook_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Not authorized")
        return
    
    webhook_url = f"{WEBHOOK_URL}/{BOT_TOKEN}"
    success = await context.bot.set_webhook(url=webhook_url)
    
    if success:
        await update.message.reply_text(f"✅ Webhook set to: {webhook_url}")
    else:
        await update.message.reply_text("❌ Failed to set webhook")

async def delete_webhook_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Not authorized")
        return
    
    success = await context.bot.delete_webhook()
    
    if success:
        await update.message.reply_text("✅ Webhook deleted")
    else:
        await update.message.reply_text("❌ Failed to delete webhook")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("testpoll", test_poll_command))
    application.add_handler(CommandHandler("testinline", test_inline_command))
    application.add_handler(CommandHandler("setwebhook", set_webhook_command))
    application.add_handler(CommandHandler("deletewebhook", delete_webhook_command))
    application.add_handler(CallbackQueryHandler(handle_inline_answer))
    
    # Register error handler
    application.add_error_handler(lambda update, context: logger.error(f"Error: {context.error}", exc_info=context.error))
    
    # Check if webhook URL is provided
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
