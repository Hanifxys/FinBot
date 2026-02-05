import logging
import time
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger("FinBot.LoggingMiddleware")

async def log_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Middleware-like handler to log all incoming updates.
    """
    user = update.effective_user
    chat = update.effective_chat
    
    start_time = time.time()
    
    user_info = f"User: {user.id} (@{user.username})" if user else "User: Unknown"
    chat_info = f"Chat: {chat.id} ({chat.type})" if chat else "Chat: Unknown"
    
    if update.message:
        content = f"Message: {update.message.text or '[Media]'}"
    elif update.callback_query:
        content = f"Callback: {update.callback_query.data}"
    else:
        content = "Other update type"
        
    logger.info(f"INCOMING - {user_info} | {chat_info} | {content}")
    
    # We don't return anything, so other handlers in higher groups will still run.
    # Note: If this handler is in group -1, it will always run unless we raise an exception.
