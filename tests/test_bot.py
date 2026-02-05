import pytest
from unittest.mock import MagicMock, patch, AsyncMock, ANY
from telegram import Update, Message, User
from telegram.ext import ContextTypes
import bot
import core
from handlers.commands import start, help_command
from handlers.finance import set_gaji, set_budget, get_ai_insight
from handlers.transactions import undo, hapus_transaksi, history, export_data
from handlers.saving import set_target, add_savings, list_targets
from handlers.messages import handle_message, handle_photo
from handlers.callbacks import handle_callback, send_report
from handlers.digest import daily_digest
from utils.dashboard import update_pinned_dashboard
from handlers.messages import send_budget_summary

import pandas as pd
from datetime import datetime

@pytest.fixture(autouse=True)
def setup_bot_components():
    with patch('core.db', MagicMock()) as mock_db, \
         patch('core.ocr', MagicMock()) as mock_ocr, \
         patch('core.nlp', MagicMock()) as mock_nlp, \
         patch('core.ai', MagicMock()) as mock_ai, \
         patch('core.budget_mgr', MagicMock()) as mock_budget_mgr, \
         patch('core.analyzer', MagicMock()) as mock_analyzer, \
         patch('core.rules', MagicMock()) as mock_rules, \
         patch('core.visual_reporter', MagicMock()) as mock_visual_reporter:
        
        # Patch bot module references as well for backward compatibility if needed
        with patch('bot.db', mock_db), \
             patch('bot.ocr', mock_ocr), \
             patch('bot.nlp', mock_nlp), \
             patch('bot.ai', mock_ai), \
             patch('bot.budget_mgr', mock_budget_mgr), \
             patch('bot.analyzer', mock_analyzer), \
             patch('bot.rules', mock_rules), \
             patch('bot.visual_reporter', mock_visual_reporter):
             
            # Set some default behaviors for mocks
            mock_db.get_or_create_user.return_value = MagicMock(id=1, telegram_id=12345)
            mock_db.get_user.return_value = MagicMock(id=1, telegram_id=12345)
            
            yield {
                'db': mock_db,
                'ocr': mock_ocr,
                'nlp': mock_nlp,
                'ai': mock_ai,
                'budget_mgr': mock_budget_mgr,
                'analyzer': mock_analyzer,
                'rules': mock_rules,
                'visual_reporter': mock_visual_reporter
            }

@pytest.fixture
def mock_update():
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 12345
    update.effective_user.username = "testuser"
    update.effective_user.first_name = "Test"
    update.message = MagicMock(spec=Message)
    update.message.reply_text = AsyncMock()
    update.message.reply_document = AsyncMock()
    update.callback_query = None
    return update

@pytest.fixture
def mock_context():
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = []
    context.user_data = {}
    context.bot = AsyncMock()
    return context

@pytest.mark.asyncio
async def test_start_command(mock_update, mock_context):
    with patch('core.db') as mock_db:
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        await start(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()
        assert "Halo" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_help_command(mock_update, mock_context):
    mock_update.callback_query = None
    await help_command(mock_update, mock_context)
    mock_update.message.reply_text.assert_called_once()
    assert "FINBOT PRO" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_set_target_command(mock_update, mock_context):
    mock_context.args = ["Laptop", "10.000.000"]
    with patch('core.db') as mock_db:
        mock_db.get_user.return_value = MagicMock(id=1)
        await set_target(mock_update, mock_context)
        mock_db.add_saving_goal.assert_called_once_with(1, "Laptop", 10000000.0)
        mock_update.message.reply_text.assert_called_once()

@pytest.mark.asyncio
async def test_add_savings_command(mock_update, mock_context):
    mock_context.args = ["1", "500rb"]
    with patch('core.db') as mock_db, patch('handlers.saving.update_pinned_dashboard', new_callable=AsyncMock):
        mock_db.get_user.return_value = MagicMock(id=1)
        mock_goal = MagicMock(id=1, name="Laptop", current_amount=500000.0, target_amount=10000000.0)
        mock_db.update_saving_progress.return_value = mock_goal
        
        await add_savings(mock_update, mock_context)
        
        mock_db.update_saving_progress.assert_called_once_with(1, 1, 500000.0)
        mock_update.message.reply_text.assert_called_once()
        assert "Tabungan Ditambah" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_handle_callback_confirm(mock_update, mock_context):
    query = AsyncMock()
    query.data = "tx_confirm"
    mock_update.callback_query = query
    mock_context.user_data['pending_tx'] = {
        'amount': 25000,
        'category': 'Makanan',
        'merchant': 'Kopi',
        'type': 'expense'
    }
    
    with patch('core.db') as mock_db, patch('core.budget_mgr') as mock_bm, patch('core.rules') as mock_rules, patch('handlers.callbacks.update_pinned_dashboard', new_callable=AsyncMock):
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        mock_rules.evaluate.return_value = []
        mock_bm.check_budget_status.return_value = ""
        mock_db.get_current_balance.return_value = 1000000.0
        
        await handle_callback(mock_update, mock_context)
        
        mock_db.add_transaction.assert_called_once()
        query.answer.assert_called_once()

@pytest.mark.asyncio
async def test_set_salary_command(mock_update, mock_context):
    mock_context.args = ["10000000"]
    with patch('core.db') as mock_db, patch('handlers.finance.update_pinned_dashboard', new_callable=AsyncMock):
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        
        await set_gaji(mock_update, mock_context)
        
        mock_db.add_monthly_income.assert_called_once_with(1, 10000000.0)
        mock_update.message.reply_text.assert_called_once()

@pytest.mark.asyncio
async def test_set_budget_command(mock_update, mock_context):
    mock_context.args = ["Makanan", "2000000"]
    with patch('core.db') as mock_db, patch('handlers.finance.update_pinned_dashboard', new_callable=AsyncMock):
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        
        await set_budget(mock_update, mock_context)
        
        mock_db.set_budget.assert_called_once_with(1, "Makanan", 2000000.0)
        mock_update.message.reply_text.assert_called_once()

@pytest.mark.asyncio
async def test_undo_command(mock_update, mock_context):
    with patch('core.db') as mock_db, patch('handlers.transactions.update_pinned_dashboard', new_callable=AsyncMock):
        mock_db.get_user.return_value = MagicMock(id=1)
        mock_db.undo_last_transaction.return_value = True
        
        await undo(mock_update, mock_context)
        
        mock_db.undo_last_transaction.assert_called_once_with(1)
        mock_update.message.reply_text.assert_called_once()
        assert "berhasil dibatalkan" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_delete_transaction_command(mock_update, mock_context):
    mock_context.args = ["123"]
    with patch('core.db') as mock_db, patch('handlers.transactions.update_pinned_dashboard', new_callable=AsyncMock):
        mock_db.get_user.return_value = MagicMock(id=1)
        mock_db.delete_transaction.return_value = True
        
        await hapus_transaksi(mock_update, mock_context)
        
        mock_db.delete_transaction.assert_called_once_with(1, 123)
        mock_update.message.reply_text.assert_called_once()
        assert "berhasil dihapus" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_get_ai_insight(mock_update, mock_context):
    with patch('core.db') as mock_db, patch('core.analyzer') as mock_analyzer, patch('core.ai') as mock_ai:
        mock_db.get_user.return_value = MagicMock(id=1)
        mock_analyzer.analyze_patterns.return_value = "raw insight"
        mock_ai.generate_smart_insight.return_value = "Insight AI"
        
        await get_ai_insight(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
        assert "Insight AI" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_export_data_success(mock_update, mock_context):
    with patch('core.db') as mock_db, patch('builtins.open', MagicMock()), patch('os.remove', MagicMock()):
        mock_db.get_user.return_value = MagicMock(id=1, telegram_id=123)
        
        await export_data(mock_update, mock_context)
        
        mock_db.export_transactions_to_csv.assert_called_once()
        mock_update.message.reply_document.assert_called_once()

@pytest.mark.asyncio
async def test_export_data_failure(mock_update, mock_context):
    with patch('core.db') as mock_db:
        mock_db.get_user.return_value = MagicMock(id=1)
        mock_db.export_transactions_to_csv.side_effect = Exception("Export failed")
        
        await export_data(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
        assert "Gagal mengekspor data" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_list_targets(mock_update, mock_context):
    with patch('core.db') as mock_db:
        mock_db.get_user.return_value = MagicMock(id=1)
        mock_goal = MagicMock(name="Laptop", target_amount=10000000.0, current_amount=500000.0)
        mock_db.get_user_saving_goals.return_value = [mock_goal]
        
        await list_targets(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
        assert "Laptop" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_handle_message_transaction(mock_update, mock_context):
    mock_update.message.text = "makan 50rb"
    with patch('core.db') as mock_db, patch('core.nlp') as mock_nlp:
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        mock_nlp.process_text.return_value = (50000.0, 'Makanan', 'expense')
        
        await handle_message(mock_update, mock_context)
        
        mock_db.add_transaction.assert_called_once()
        mock_update.message.reply_text.assert_called()
        call_args = str(mock_update.message.reply_text.call_args)
        assert "50,000" in call_args
        assert "Tercatat" in call_args

@pytest.mark.asyncio
async def test_handle_message_chat(mock_update, mock_context):
    mock_update.message.text = "Halo bot"
    with patch('core.db') as mock_db, patch('core.nlp') as mock_nlp:
        mock_user = MagicMock(id=1)
        mock_db.get_or_create_user.return_value = mock_user
        mock_nlp.process_text.return_value = (0, None, None)
        mock_nlp.parse_message.return_value = {'intent': 'greeting'}
        
        await handle_message(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
        assert "Halo" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_handle_photo(mock_update, mock_context):
    mock_file = AsyncMock()
    mock_file.download_to_drive = AsyncMock()
    
    mock_photo = MagicMock()
    mock_photo.get_file = AsyncMock(return_value=mock_file)
    mock_update.message.photo = [mock_photo]
    
    processing_msg = AsyncMock()
    mock_update.message.reply_text.return_value = processing_msg
    
    with patch('core.db') as mock_db, patch('core.ocr') as mock_ocr, patch('core.nlp') as mock_nlp, patch('os.path.exists') as mock_exists, patch('os.remove') as mock_remove:
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        mock_ocr.process_receipt.return_value = {'amount': 75000.0, 'merchant': 'Test Shop'}
        mock_nlp._detect_category.return_value = "Makanan"
        mock_exists.return_value = True
        
        await handle_photo(mock_update, mock_context)
        
        mock_ocr.process_receipt.assert_called_once()
        processing_msg.edit_text.assert_called_once()
        call_args = str(processing_msg.edit_text.call_args)
        assert "75,000" in call_args

@pytest.mark.asyncio
async def test_handle_callback_ignore(mock_update, mock_context):
    query = AsyncMock()
    query.data = "tx_ignore"
    mock_update.callback_query = query
    
    with patch('core.db') as mock_db:
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        await handle_callback(mock_update, mock_context)
        query.edit_message_text.assert_called_once()
        assert "Transaksi diabaikan" in query.edit_message_text.call_args[0][0]

@pytest.mark.asyncio
async def test_history_command(mock_update, mock_context):
    mock_context.args = []
    with patch('core.db') as mock_db:
        mock_user = MagicMock(id=1)
        mock_db.get_user.return_value = mock_user
        mock_tx = MagicMock()
        mock_tx.id = 1
        mock_tx.amount = 50000
        mock_tx.category = "Makanan"
        mock_tx.description = "test"
        mock_tx.date = datetime.now()
        mock_db.get_transactions_history.return_value = [mock_tx]
        
        await history(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
        assert "Makanan" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_history_command_filtered(mock_update, mock_context):
    mock_context.args = ["cat:Makanan", "min:10k"]
    with patch('core.db') as mock_db:
        mock_user = MagicMock(id=1)
        mock_db.get_user.return_value = mock_user
        mock_db.get_transactions_history.return_value = []
        
        await history(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
        assert "Belum ada riwayat transaksi" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_update_pinned_dashboard(mock_context):
    with patch('core.db') as mock_db, patch('core.budget_mgr') as mock_budget:
        mock_user = MagicMock(id=1)
        mock_db.get_user.return_value = mock_user
        mock_db.get_current_balance.return_value = 1000000
        mock_budget.generate_report.return_value = "Monthly Report"
        mock_db.get_user_budgets.return_value = []
        mock_db.get_user_saving_goals.return_value = []
        
        mock_context.bot.edit_message_text = AsyncMock()
        mock_db.get_user_metadata.return_value = 123
        
        await update_pinned_dashboard(mock_context, 1)
        
        mock_context.bot.edit_message_text.assert_called_once()
        assert "Monthly Report" in mock_context.bot.edit_message_text.call_args[1]['text']

@pytest.mark.asyncio
async def test_daily_digest(mock_context):
    with patch('core.db') as mock_db, patch('core.budget_mgr') as mock_budget:
        mock_user = MagicMock(id=1, telegram_id=123)
        mock_db.get_all_users.return_value = [mock_user]
        
        mock_tx = MagicMock()
        mock_tx.amount = 50000
        mock_tx.category = "Makanan"
        mock_tx.type = 'expense'
        mock_db.get_daily_transactions.return_value = [mock_tx]
        mock_db.get_sliding_window_transactions.return_value = [mock_tx]
        mock_budget.check_budget_status.return_value = "Budget OK"
        
        mock_context.bot.send_message = AsyncMock()
        
        await daily_digest(mock_context)
        
        mock_context.bot.send_message.assert_called_once()
        assert "DAILY DIGEST" in mock_context.bot.send_message.call_args[1]['text']

@pytest.mark.asyncio
async def test_handle_callback_report(mock_update, mock_context):
    query = AsyncMock()
    query.data = "report_monthly"
    mock_update.callback_query = query
    
    with patch('core.db') as mock_db, patch('core.budget_mgr') as mock_bm:
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        mock_bm.generate_report.return_value = "Laporan Bulanan"
        
        await handle_callback(mock_update, mock_context)
        
        mock_bm.generate_report.assert_called_once_with(1, period="monthly")
        query.edit_message_text.assert_called_once_with("Laporan Bulanan", reply_markup=ANY)

@pytest.mark.asyncio
async def test_handle_message_waiting_edit_amount(mock_update, mock_context):
    mock_update.message.text = "100rb"
    mock_context.user_data['state'] = 'WAITING_EDIT_AMOUNT'
    mock_context.user_data['pending_tx'] = {'amount': 50000, 'category': 'Makanan'}
    
    await handle_message(mock_update, mock_context)
    
    assert mock_context.user_data['pending_tx']['amount'] == 100000.0
    assert mock_context.user_data['state'] is None
    mock_update.message.reply_text.assert_called()
    assert "Nominal diubah ke" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_handle_message_waiting_edit_invalid(mock_update, mock_context):
    mock_update.message.text = "bukan angka"
    mock_context.user_data['state'] = 'WAITING_EDIT_AMOUNT'
    
    await handle_message(mock_update, mock_context)
    
    mock_update.message.reply_text.assert_called_with("Format nominal salah. Masukkan angka saja.")
    assert mock_context.user_data['state'] == 'WAITING_EDIT_AMOUNT'

@pytest.mark.asyncio
async def test_handle_message_unknown_intent(mock_update, mock_context):
    mock_update.message.text = "random text"
    with patch('core.db') as mock_db, patch('core.nlp') as mock_nlp:
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        mock_nlp.process_text.return_value = (0, None, None)
        mock_nlp.parse_message.return_value = {'intent': 'unknown'}
        
        await handle_message(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called()
        assert "nggak paham" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_handle_callback_edit_actions(mock_update, mock_context):
    actions = ["tx_edit", "edit_amount", "edit_category"]
    for action in actions:
        query = AsyncMock()
        query.data = action
        mock_update.callback_query = query
        with patch('core.db') as mock_db:
            mock_db.get_or_create_user.return_value = MagicMock(id=1)
            await handle_callback(mock_update, mock_context)
            query.edit_message_text.assert_called()

@pytest.mark.asyncio
async def test_handle_callback_set_cat(mock_update, mock_context):
    query = AsyncMock()
    query.data = "set_cat_Makanan"
    mock_update.callback_query = query
    mock_context.user_data['pending_tx'] = {'amount': 50000, 'category': 'Lain-lain'}
    
    with patch('core.db') as mock_db:
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        await handle_callback(mock_update, mock_context)
        assert mock_context.user_data['pending_tx']['category'] == "Makanan"
        query.edit_message_text.assert_called()

@pytest.mark.asyncio
async def test_send_budget_summary(mock_update, mock_context):
    with patch('core.db') as mock_db, patch('core.budget_mgr') as mock_bm:
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        mock_db.get_user_budgets.return_value = [
            MagicMock(category="Makanan", limit_amount=2000000, current_usage=500000)
        ]
        mock_bm.get_detailed_budget_status.return_value = "Budget Utilization Makanan"
            
        await send_budget_summary(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called()
        assert "Budget Utilization Makanan" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_handle_message_intents(mock_update, mock_context):
    intents = ["query_budget", "get_report", "help", "greeting"]
    for intent in intents:
        mock_update.message.text = "test"
        with patch('core.db') as mock_db, patch('core.nlp') as mock_nlp, \
             patch('handlers.messages.send_budget_summary', new_callable=AsyncMock) as mock_sbs, \
             patch('handlers.messages.send_report', new_callable=AsyncMock) as mock_sr, \
             patch('handlers.messages.help_command', new_callable=AsyncMock) as mock_hc:
            
            mock_db.get_or_create_user.return_value = MagicMock(id=1)
            mock_nlp.process_text.return_value = (0, None, None)
            mock_nlp.parse_message.return_value = {'intent': intent}
            
            await handle_message(mock_update, mock_context)
            
            if intent == "query_budget":
                mock_sbs.assert_called_once()
            elif intent == "get_report":
                mock_sr.assert_called_once()
            elif intent == "help":
                mock_hc.assert_called_once()
            else:
                mock_update.message.reply_text.assert_called()

@pytest.mark.asyncio
async def test_handle_callback_misc(mock_update, mock_context):
    actions = ["suggest_help", "suggest_budget", "suggest_insight"]
    for action in actions:
        query = AsyncMock()
        query.data = action
        mock_update.callback_query = query
        with patch('core.db') as mock_db, patch('core.budget_mgr') as mock_bm, \
             patch('handlers.callbacks.get_ai_insight', new_callable=AsyncMock) as mock_ai_insight:
            
            mock_db.get_or_create_user.return_value = MagicMock(id=1)
            mock_bm.check_budget_status.return_value = "Status"
            
            await handle_callback(mock_update, mock_context)
            
            if action == "suggest_insight":
                mock_ai_insight.assert_called_once()
            else:
                # query.answer() or similar
                pass

@pytest.mark.asyncio
async def test_handle_message_waiting_edit_category(mock_update, mock_context):
    mock_update.message.text = "Makanan"
    mock_context.user_data['state'] = 'WAITING_EDIT_CATEGORY'
    mock_context.user_data['pending_tx'] = {'amount': 50000, 'category': 'Lain-lain'}
    
    with patch('core.nlp') as mock_nlp, patch('core.ai') as mock_ai:
        mock_ai.parse_transaction.return_value = {'is_transaction': False}
        mock_nlp.classify_intent.return_value = {'intent': 'NONE', 'confidence': 0.0}
        
        await handle_message(mock_update, mock_context)
        
        assert mock_context.user_data['pending_tx']['category'] == "Makanan"
        assert 'state' not in mock_context.user_data

@pytest.mark.asyncio
async def test_handle_message_waiting_edit_date(mock_update, mock_context):
    mock_update.message.text = "2023-01-01"
    mock_context.user_data['state'] = 'WAITING_EDIT_DATE'
    mock_context.user_data['pending_tx'] = {'amount': 50000, 'category': 'Makanan', 'date': '2023-01-02'}
    
    with patch('core.nlp') as mock_nlp, patch('core.ai') as mock_ai:
        mock_ai.parse_transaction.return_value = {'is_transaction': False}
        mock_nlp.classify_intent.return_value = {'intent': 'NONE', 'confidence': 0.0}
        
        await handle_message(mock_update, mock_context)
        
        assert mock_context.user_data['pending_tx']['date'] == "2023-01-01"
        assert 'state' not in mock_context.user_data

@pytest.mark.asyncio
async def test_send_report_callback(mock_update, mock_context):
    await send_report(mock_update, mock_context)
    mock_update.message.reply_text.assert_called_once()

@pytest.mark.asyncio
async def test_handle_photo_success(mock_update, mock_context):
    # Setup for successful photo handling
    mock_file = AsyncMock()
    mock_photo = MagicMock()
    mock_photo.get_file = AsyncMock(return_value=mock_file)
    mock_update.message.photo = [mock_photo]
    
    processing_msg = AsyncMock()
    mock_update.message.reply_text.return_value = processing_msg
    
    with patch('core.db') as mock_db, patch('core.ocr') as mock_ocr, patch('core.nlp') as mock_nlp, patch('os.path.exists') as mock_exists, patch('os.remove') as mock_remove:
        mock_ocr.enabled = True
        mock_ocr.process_receipt.return_value = {'amount': 50000, 'merchant': 'Toko', 'date': '2023-01-01'}
        mock_nlp._detect_category.return_value = "Belanja"
        
        await handle_photo(mock_update, mock_context)
        
        processing_msg.edit_text.assert_called()
        assert "50,000" in str(processing_msg.edit_text.call_args)

@pytest.mark.asyncio
async def test_handle_photo_failure(mock_update, mock_context):
    # Setup for failed photo handling
    mock_file = AsyncMock()
    mock_photo = MagicMock()
    mock_photo.get_file = AsyncMock(return_value=mock_file)
    mock_update.message.photo = [mock_photo]
    
    processing_msg = AsyncMock()
    mock_update.message.reply_text.return_value = processing_msg
    
    with patch('core.db') as mock_db, patch('core.ocr') as mock_ocr:
        mock_ocr.enabled = True
        mock_ocr.process_receipt.side_effect = Exception("OCR Error")
        
        await handle_photo(mock_update, mock_context)
        
        processing_msg.edit_text.assert_called_with("Terjadi kesalahan saat memproses gambar. Coba pastikan foto struk terlihat jelas.")

@pytest.mark.asyncio
async def test_handle_callback_tx_confirm_with_date(mock_update, mock_context):
    query = AsyncMock()
    query.data = "tx_confirm"
    mock_update.callback_query = query
    mock_context.user_data['pending_tx'] = {
        'amount': 25000,
        'category': 'Makanan',
        'merchant': 'Kopi',
        'date': '2023-01-01',
        'type': 'expense'
    }
    
    with patch('core.db') as mock_db, patch('core.budget_mgr') as mock_bm, patch('core.rules') as mock_rules, patch('handlers.callbacks.update_pinned_dashboard', new_callable=AsyncMock):
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        mock_rules.evaluate.return_value = []
        mock_bm.check_budget_status.return_value = ""
        
        await handle_callback(mock_update, mock_context)
        
        mock_db.add_transaction.assert_called_once()
        # Verify date was parsed
        args, kwargs = mock_db.add_transaction.call_args
        assert kwargs['trans_date'].year == 2023

@pytest.mark.asyncio
async def test_handle_callback_tx_edit_options(mock_update, mock_context):
    query = AsyncMock()
    query.data = "tx_edit"
    mock_update.callback_query = query
    
    with patch('core.db') as mock_db:
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        await handle_callback(mock_update, mock_context)
        query.edit_message_text.assert_called()
        assert "Pilih bagian" in query.edit_message_text.call_args[0][0]

@pytest.mark.asyncio
async def test_handle_callback_edit_amount(mock_update, mock_context):
    query = AsyncMock()
    query.data = "edit_amount"
    mock_update.callback_query = query
    
    with patch('core.db') as mock_db:
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        await handle_callback(mock_update, mock_context)
        assert mock_context.user_data['state'] == 'WAITING_EDIT_AMOUNT'
        query.edit_message_text.assert_called()

@pytest.mark.asyncio
async def test_handle_callback_edit_category(mock_update, mock_context):
    query = AsyncMock()
    query.data = "edit_category"
    mock_update.callback_query = query
    
    with patch('core.db') as mock_db:
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        await handle_callback(mock_update, mock_context)
        assert mock_context.user_data['state'] == 'WAITING_EDIT_CATEGORY'
        query.edit_message_text.assert_called()
