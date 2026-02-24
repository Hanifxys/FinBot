import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from telegram import Update, User, Chat, Message
from telegram.ext import ContextTypes
from middlewares.logging import log_update

@pytest.mark.asyncio
async def test_log_update_message():
    # Setup mocks
    mock_user = MagicMock(spec=User)
    mock_user.id = 12345
    mock_user.username = "testuser"
    
    mock_chat = MagicMock(spec=Chat)
    mock_chat.id = 67890
    mock_chat.type = "private"
    
    mock_message = MagicMock(spec=Message)
    mock_message.text = "halo bot"
    
    mock_update = MagicMock(spec=Update)
    mock_update.effective_user = mock_user
    mock_update.effective_chat = mock_chat
    mock_update.message = mock_message
    mock_update.callback_query = None
    
    mock_context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    
    with patch('middlewares.logging.logger') as mock_logger:
        await log_update(mock_update, mock_context)
        
        # Verify logger.info was called
        mock_logger.info.assert_called_once()
        log_msg = mock_logger.info.call_args[0][0]
        assert "INCOMING" in log_msg
        assert "12345" in log_msg
        assert "@testuser" in log_msg
        assert "halo bot" in log_msg

@pytest.mark.asyncio
async def test_log_update_callback():
    # Setup mocks
    mock_user = MagicMock(spec=User)
    mock_user.id = 12345
    mock_user.username = "testuser"
    
    mock_chat = MagicMock(spec=Chat)
    mock_chat.id = 67890
    mock_chat.type = "private"
    
    mock_query = MagicMock()
    mock_query.data = "button_click"
    
    mock_update = MagicMock(spec=Update)
    mock_update.effective_user = mock_user
    mock_update.effective_chat = mock_chat
    mock_update.message = None
    mock_update.callback_query = mock_query
    
    mock_context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    
    with patch('middlewares.logging.logger') as mock_logger:
        await log_update(mock_update, mock_context)
        
        # Verify logger.info was called
        mock_logger.info.assert_called_once()
        log_msg = mock_logger.info.call_args[0][0]
        assert "INCOMING" in log_msg
        assert "button_click" in log_msg
