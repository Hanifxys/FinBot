import pytest
from unittest.mock import MagicMock, patch, AsyncMock, ANY
from telegram import Update, Message, User
from telegram.ext import ContextTypes
import bot
import pandas as pd
from datetime import datetime

@pytest.fixture(autouse=True)
def setup_bot_components():
    with patch('bot.db', MagicMock()) as mock_db, \
         patch('bot.ocr', MagicMock()) as mock_ocr, \
         patch('bot.nlp', MagicMock()) as mock_nlp, \
         patch('bot.ai', MagicMock()) as mock_ai, \
         patch('bot.budget_mgr', MagicMock()) as mock_budget_mgr, \
         patch('bot.analyzer', MagicMock()) as mock_analyzer, \
         patch('bot.rules', MagicMock()) as mock_rules, \
         patch('bot.visual_reporter', MagicMock()) as mock_visual_reporter:
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
    with patch('bot.db') as mock_db:
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        await bot.start(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()
        assert "Halo" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_help_command(mock_update, mock_context):
    mock_update.callback_query = None
    await bot.help_command(mock_update, mock_context)
    mock_update.message.reply_text.assert_called_once()
    assert "FINBOT PRO" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_set_target_command(mock_update, mock_context):
    mock_context.args = ["Laptop", "10.000.000"]
    with patch('bot.db') as mock_db:
        mock_db.get_user.return_value = MagicMock(id=1)
        await bot.set_target(mock_update, mock_context)
        mock_db.add_saving_goal.assert_called_once_with(1, "Laptop", 10000000.0)
        mock_update.message.reply_text.assert_called_once()

@pytest.mark.asyncio
async def test_add_savings_command(mock_update, mock_context):
    mock_context.args = ["1", "500rb"]
    with patch('bot.db') as mock_db, patch('bot.update_pinned_dashboard', new_callable=AsyncMock):
        mock_db.get_user.return_value = MagicMock(id=1)
        mock_goal = MagicMock(id=1, name="Laptop", current_amount=500000.0, target_amount=10000000.0)
        mock_db.update_saving_progress.return_value = mock_goal
        
        await bot.add_savings(mock_update, mock_context)
        
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
    
    with patch('bot.db') as mock_db, patch('bot.budget_mgr') as mock_bm, patch('bot.rules') as mock_rules, patch('bot.update_pinned_dashboard', new_callable=AsyncMock):
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        mock_rules.evaluate.return_value = []
        mock_bm.check_budget_status.return_value = ""
        mock_db.get_current_balance.return_value = 1000000.0
        
        await bot.handle_callback(mock_update, mock_context)
        
        mock_db.add_transaction.assert_called_once()
        query.answer.assert_called_once()

@pytest.mark.asyncio
async def test_set_salary_command(mock_update, mock_context):
    mock_context.args = ["10000000"]
    with patch('bot.db') as mock_db, patch('bot.update_pinned_dashboard', new_callable=AsyncMock):
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        
        await bot.set_gaji(mock_update, mock_context)
        
        mock_db.add_monthly_income.assert_called_once_with(1, 10000000.0)
        mock_update.message.reply_text.assert_called_once()

@pytest.mark.asyncio
async def test_set_budget_command(mock_update, mock_context):
    mock_context.args = ["Makanan", "2000000"]
    with patch('bot.db') as mock_db, patch('bot.update_pinned_dashboard', new_callable=AsyncMock):
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        
        await bot.set_budget(mock_update, mock_context)
        
        mock_db.set_budget.assert_called_once_with(1, "Makanan", 2000000.0)
        mock_update.message.reply_text.assert_called_once()

@pytest.mark.asyncio
async def test_undo_command(mock_update, mock_context):
    with patch('bot.db') as mock_db, patch('bot.update_pinned_dashboard', new_callable=AsyncMock):
        mock_db.get_user.return_value = MagicMock(id=1)
        mock_db.undo_last_transaction.return_value = True
        
        await bot.undo(mock_update, mock_context)
        
        mock_db.undo_last_transaction.assert_called_once_with(1)
        mock_update.message.reply_text.assert_called_once()
        assert "berhasil dibatalkan" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_delete_transaction_command(mock_update, mock_context):
    mock_context.args = ["123"]
    with patch('bot.db') as mock_db, patch('bot.update_pinned_dashboard', new_callable=AsyncMock):
        mock_db.get_user.return_value = MagicMock(id=1)
        mock_db.delete_transaction.return_value = True
        
        await bot.hapus_transaksi(mock_update, mock_context)
        
        mock_db.delete_transaction.assert_called_once_with(1, 123)
        mock_update.message.reply_text.assert_called_once()
        assert "berhasil dihapus" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_get_ai_insight(mock_update, mock_context):
    with patch('bot.db') as mock_db, patch('bot.analyzer') as mock_analyzer, patch('bot.ai') as mock_ai:
        mock_db.get_user.return_value = MagicMock(id=1)
        mock_analyzer.analyze_patterns.return_value = "raw insight"
        mock_ai.generate_smart_insight.return_value = "Insight AI"
        
        await bot.get_ai_insight(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
        assert "Insight AI" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_export_data_success(mock_update, mock_context):
    with patch('bot.db') as mock_db, patch('builtins.open', MagicMock()), patch('os.remove', MagicMock()):
        mock_db.get_user.return_value = MagicMock(id=1, telegram_id=123)
        # Match the method name in bot.py line 146
        
        await bot.export_data(mock_update, mock_context)
        
        mock_db.export_transactions_to_csv.assert_called_once()
        mock_update.message.reply_document.assert_called_once()

@pytest.mark.asyncio
async def test_export_data_failure(mock_update, mock_context):
    with patch('bot.db') as mock_db:
        mock_db.get_user.return_value = MagicMock(id=1)
        mock_db.export_transactions_to_csv.side_effect = Exception("Export failed")
        
        await bot.export_data(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
        assert "Gagal mengekspor data" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_list_targets(mock_update, mock_context):
    with patch('bot.db') as mock_db:
        mock_db.get_user.return_value = MagicMock(id=1)
        mock_goal = MagicMock(name="Laptop", target_amount=10000000.0, current_amount=500000.0)
        mock_db.get_user_saving_goals.return_value = [mock_goal]
        
        await bot.list_targets(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
        assert "Laptop" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_handle_message_transaction(mock_update, mock_context):
    mock_update.message.text = "makan 50rb"
    with patch('bot.db') as mock_db, patch('bot.nlp') as mock_nlp, patch('bot.ai') as mock_ai:
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        mock_ai.parse_transaction.return_value = {
            'is_transaction': True,
            'amount': 50000.0,
            'category': 'Makanan',
            'description': 'makan',
            'type': 'expense'
        }
        
        await bot.handle_message(mock_update, mock_context)
        
        # Verify reply_text was called with expected amount
        mock_update.message.reply_text.assert_called()
        call_args = str(mock_update.message.reply_text.call_args)
        assert "50,000" in call_args
        assert "Simpan transaksi ini?" in call_args

@pytest.mark.asyncio
async def test_handle_message_chat(mock_update, mock_context):
    mock_update.message.text = "Halo bot"
    with patch('bot.db') as mock_db, patch('bot.nlp') as mock_nlp, patch('bot.ai') as mock_ai:
        mock_user = MagicMock(id=1)
        mock_db.get_or_create_user.return_value = mock_user
        mock_nlp.classify_intent.return_value = {'intent': 'GREETING', 'confidence': 0.9}
        mock_ai.parse_transaction.return_value = {'is_transaction': False}
        mock_ai.chat_response.return_value = "Halo juga!"
        
        await bot.handle_message(mock_update, mock_context)
        
        # In bot.py line 302, GREETING calls reply_text with a keyboard
        mock_update.message.reply_text.assert_called_once()
        assert "Halo" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_handle_photo(mock_update, mock_context):
    mock_file = AsyncMock()
    mock_file.download_to_drive = AsyncMock()
    
    mock_photo = MagicMock()
    mock_photo.get_file = AsyncMock(return_value=mock_file)
    mock_update.message.photo = [mock_photo]
    
    # Mock the return value of reply_text ("Memproses gambar... ⏳")
    processing_msg = AsyncMock()
    mock_update.message.reply_text.return_value = processing_msg
    
    with patch('bot.db') as mock_db, patch('bot.ocr') as mock_ocr, patch('bot.nlp') as mock_nlp, patch('os.path.exists') as mock_exists, patch('os.remove') as mock_remove:
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        mock_ocr.process_receipt.return_value = {'amount': 75000.0, 'merchant': 'Test Shop'}
        mock_nlp._detect_category.return_value = "Makanan"
        mock_exists.return_value = True
        
        await bot.handle_photo(mock_update, mock_context)
        
        mock_ocr.process_receipt.assert_called_once()
        # Verify edit_text was called on the processing message
        processing_msg.edit_text.assert_called_once()
        call_args = str(processing_msg.edit_text.call_args)
        assert "75,000" in call_args

@pytest.mark.asyncio
async def test_handle_callback_ignore(mock_update, mock_context):
    query = AsyncMock()
    query.data = "tx_ignore"
    mock_update.callback_query = query
    
    with patch('bot.db') as mock_db:
        # bot.py line 430 calls get_or_create_user
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        await bot.handle_callback(mock_update, mock_context)
        # Match message in bot.py line 583
        query.edit_message_text.assert_called_once()
        assert "Transaksi diabaikan" in query.edit_message_text.call_args[0][0]

@pytest.mark.asyncio
async def test_history_command(mock_update, mock_context):
    mock_context.args = []
    with patch('bot.db') as mock_db:
        mock_user = MagicMock(id=1)
        mock_db.get_user.return_value = mock_user
        mock_tx = MagicMock()
        mock_tx.id = 1
        mock_tx.amount = 50000
        mock_tx.category = "Makanan"
        mock_tx.description = "test"
        mock_tx.date = datetime.now()
        mock_db.get_transactions_history.return_value = [mock_tx]
        
        await bot.history(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
        assert "Makanan" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_history_command_filtered(mock_update, mock_context):
    mock_context.args = ["cat:Makanan", "min:10k"]
    with patch('bot.db') as mock_db:
        mock_user = MagicMock(id=1)
        mock_db.get_user.return_value = mock_user
        mock_db.get_transactions_history.return_value = []
        
        await bot.history(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
        assert "Belum ada riwayat transaksi" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_update_pinned_dashboard(mock_context):
    with patch('bot.db') as mock_db, patch('bot.budget_mgr') as mock_budget:
        mock_user = MagicMock(id=1)
        mock_db.get_user.return_value = mock_user
        mock_db.get_current_balance.return_value = 1000000
        mock_budget.generate_report.return_value = "Monthly Report"
        mock_db.get_user_budgets.return_value = []
        mock_db.get_user_saving_goals.return_value = []
        
        # We need to mock context.bot.edit_message_text
        mock_context.bot.edit_message_text = AsyncMock()
        # Mock pinned message ID
        mock_db.get_user_metadata.return_value = 123
        
        await bot.update_pinned_dashboard(mock_context, 1)
        
        mock_context.bot.edit_message_text.assert_called_once()
        assert "Monthly Report" in mock_context.bot.edit_message_text.call_args[1]['text']

@pytest.mark.asyncio
async def test_daily_digest(mock_context):
    with patch('bot.db') as mock_db, patch('bot.budget_mgr') as mock_budget:
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
        
        await bot.daily_digest(mock_context)
        
        mock_context.bot.send_message.assert_called_once()
        assert "DAILY DIGEST" in mock_context.bot.send_message.call_args[1]['text']

@pytest.mark.asyncio
async def test_handle_callback_report(mock_update, mock_context):
    query = AsyncMock()
    query.data = "report_monthly"
    mock_update.callback_query = query
    
    with patch('bot.db') as mock_db, patch('bot.budget_mgr') as mock_bm:
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        mock_bm.generate_report.return_value = "Laporan Bulanan"
        
        await bot.handle_callback(mock_update, mock_context)
        
        mock_bm.generate_report.assert_called_once_with(1, period="monthly")
        query.edit_message_text.assert_called_once_with("Laporan Bulanan")

@pytest.mark.asyncio
async def test_handle_message_waiting_edit_amount(mock_update, mock_context):
    mock_update.message.text = "100rb"
    mock_context.user_data['state'] = 'WAITING_EDIT_AMOUNT'
    mock_context.user_data['pending_tx'] = {'amount': 50000, 'category': 'Makanan'}
    
    with patch('bot.nlp') as mock_nlp, patch('bot.ai') as mock_ai:
        mock_ai.parse_transaction.return_value = {'is_transaction': False}
        mock_nlp.classify_intent.return_value = {'intent': 'NONE', 'confidence': 0.0}
        mock_nlp.validate_edit.return_value = {'valid': True, 'new_value': 100000.0}
        
        await bot.handle_message(mock_update, mock_context)
        
        assert mock_context.user_data['pending_tx']['amount'] == 100000.0
        assert 'state' not in mock_context.user_data
        mock_update.message.reply_text.assert_called()
        assert "Berhasil diubah" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_handle_message_waiting_edit_cancel(mock_update, mock_context):
    mock_update.message.text = "batal"
    mock_context.user_data['state'] = 'WAITING_EDIT_AMOUNT'
    
    with patch('bot.nlp') as mock_nlp, patch('bot.ai') as mock_ai:
        mock_ai.parse_transaction.return_value = {'is_transaction': False}
        mock_nlp.classify_intent.return_value = {'intent': 'CANCEL', 'confidence': 1.0}
        
        await bot.handle_message(mock_update, mock_context)
        
        assert 'state' not in mock_context.user_data
        mock_update.message.reply_text.assert_called_with("Edit dibatalkan.")

@pytest.mark.asyncio
async def test_handle_message_add_transaction_intent(mock_update, mock_context):
    mock_update.message.text = "makan 50k"
    with patch('bot.db') as mock_db, patch('bot.nlp') as mock_nlp, patch('bot.ai') as mock_ai:
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        mock_ai.parse_transaction.return_value = {'is_transaction': False}
        mock_nlp.classify_intent.return_value = {'intent': 'ADD_TRANSACTION', 'confidence': 0.9}
        mock_nlp.extract_transaction_data.return_value = {
            'amount': 50000.0,
            'category': 'Makanan',
            'merchant': 'Warung',
            'confidence': 0.9
        }
        
        await bot.handle_message(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called()
        assert "50,000" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_handle_callback_edit_actions(mock_update, mock_context):
    actions = ["tx_edit", "edit_amount", "edit_category", "edit_date"]
    for action in actions:
        query = AsyncMock()
        query.data = action
        mock_update.callback_query = query
        with patch('bot.db') as mock_db:
            mock_db.get_or_create_user.return_value = MagicMock(id=1)
            await bot.handle_callback(mock_update, mock_context)
            query.edit_message_text.assert_called()

@pytest.mark.asyncio
async def test_handle_callback_set_cat(mock_update, mock_context):
    query = AsyncMock()
    query.data = "set_cat_Makanan"
    mock_update.callback_query = query
    mock_context.user_data['pending_tx'] = {'amount': 50000, 'category': 'Lain-lain'}
    
    with patch('bot.db') as mock_db:
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        await bot.handle_callback(mock_update, mock_context)
        assert mock_context.user_data['pending_tx']['category'] == "Makanan"
        query.edit_message_text.assert_called()

@pytest.mark.asyncio
async def test_send_budget_summary(mock_update, mock_context):
    with patch('bot.db') as mock_db, patch('bot.budget_mgr') as mock_bm:
        mock_db.get_or_create_user.return_value = MagicMock(id=1)
        mock_db.get_user_budgets.return_value = [
            MagicMock(category="Makanan", limit_amount=2000000, current_usage=500000)
        ]
        mock_bm.get_detailed_budget_status.return_value = "Budget Utilization Makanan"
            
        await bot.send_budget_summary(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called()
        assert "Budget Utilization Makanan" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_handle_message_intents(mock_update, mock_context):
    intents = ["CHECK_BUDGET", "QUERY_SUMMARY", "HELP"]
    for intent in intents:
        mock_update.message.text = "test"
        with patch('bot.db') as mock_db, patch('bot.nlp') as mock_nlp, patch('bot.ai') as mock_ai:
            mock_db.get_or_create_user.return_value = MagicMock(id=1)
            mock_ai.parse_transaction.return_value = {'is_transaction': False}
            mock_nlp.classify_intent.return_value = {'intent': intent, 'confidence': 0.9}
            
            # Patch dependent functions
            with patch('bot.send_budget_summary', new_callable=AsyncMock) as mock_sbs, \
                 patch('bot.send_report', new_callable=AsyncMock) as mock_sr, \
                 patch('bot.help_command', new_callable=AsyncMock) as mock_hc:
                
                await bot.handle_message(mock_update, mock_context)
                
                if intent == "CHECK_BUDGET":
                    mock_sbs.assert_called_once()
                elif intent == "QUERY_SUMMARY":
                    mock_sr.assert_called_once()
                elif intent == "HELP":
                    # bot.py line 271-289 handles HELP intent directly
                    mock_update.message.reply_text.assert_called()
                    assert "FinBot Command Center" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_handle_callback_misc(mock_update, mock_context):
    actions = ["view_salary_summary", "show_budget_menu", "change_allocation"]
    for action in actions:
        query = AsyncMock()
        query.data = action
        mock_update.callback_query = query
        with patch('bot.db') as mock_db, patch('bot.budget_mgr') as mock_bm:
            mock_db.get_user.return_value = MagicMock(id=1)
            mock_db.get_monthly_income.return_value = 10000000.0
            mock_bm.get_allocation_recommendation.return_value = ("Rekomendasi", {})
            
            await bot.handle_callback(mock_update, mock_context)
            
            if action == "view_salary_summary":
                query.edit_message_text.assert_called_with("Rekomendasi")
            elif action == "show_budget_menu":
                query.edit_message_text.assert_called_with("Mau ubah alokasi?")
            elif action == "change_allocation":
                # Assuming this might be handled by suggested_ or similar fallback
                pass

@pytest.mark.asyncio
async def test_handle_callback_suggest(mock_update, mock_context):
    suggestions = ["suggest_/setgaji", "suggest_/setbudget", "suggest_laporan", "suggest_budget", "suggest_insight", "suggest_help"]
    for suggestion in suggestions:
        query = AsyncMock()
        query.data = suggestion
        mock_update.callback_query = query
        with patch('bot.db') as mock_db, \
             patch('bot.send_budget_summary', new_callable=AsyncMock) as mock_sbs, \
             patch('bot.get_ai_insight', new_callable=AsyncMock) as mock_gai, \
             patch('bot.help_command', new_callable=AsyncMock) as mock_hc:
            
            mock_db.get_or_create_user.return_value = MagicMock(id=1)
            await bot.handle_callback(mock_update, mock_context)
            
            if suggestion == "suggest_budget":
                mock_sbs.assert_called_once()
            elif suggestion == "suggest_insight":
                mock_gai.assert_called_once()
            elif suggestion == "suggest_help":
                mock_hc.assert_called_once()
            else:
                query.edit_message_text.assert_called()

@pytest.mark.asyncio
async def test_error_handler(mock_update, mock_context):
    mock_context.error = Exception("Test error")
    with patch('logging.error') as mock_log:
        await bot.error_handler(mock_update, mock_context)
        mock_log.assert_called()

@pytest.mark.asyncio
async def test_post_init(mock_context):
    application = MagicMock()
    application.bot = AsyncMock()
    await bot.post_init(application)
    application.bot.set_my_commands.assert_called_once()

@pytest.mark.asyncio
async def test_handle_message_waiting_edit_category(mock_update, mock_context):
    mock_update.message.text = "Makanan"
    mock_context.user_data['state'] = 'WAITING_EDIT_CATEGORY'
    mock_context.user_data['pending_tx'] = {'amount': 50000, 'category': 'Lain-lain'}
    
    with patch('bot.nlp') as mock_nlp, patch('bot.ai') as mock_ai:
        mock_ai.parse_transaction.return_value = {'is_transaction': False}
        mock_nlp.classify_intent.return_value = {'intent': 'EDIT_TRANSACTION', 'confidence': 0.9}
        mock_nlp.validate_edit.return_value = {'valid': True, 'new_value': 'Makanan'}
        
        await bot.handle_message(mock_update, mock_context)
        
        assert mock_context.user_data['pending_tx']['category'] == 'Makanan'
        assert 'state' not in mock_context.user_data
        mock_update.message.reply_text.assert_called()
        assert "Berhasil diubah" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_handle_message_waiting_edit_date(mock_update, mock_context):
    mock_update.message.text = "2024-01-01"
    mock_context.user_data['state'] = 'WAITING_EDIT_DATE'
    mock_context.user_data['pending_tx'] = {'amount': 50000, 'category': 'Makanan', 'date': '2024-01-01'}
    
    with patch('bot.nlp') as mock_nlp, patch('bot.ai') as mock_ai:
        mock_ai.parse_transaction.return_value = {'is_transaction': False}
        mock_nlp.classify_intent.return_value = {'intent': 'EDIT_TRANSACTION', 'confidence': 0.9}
        mock_nlp.validate_edit.return_value = {'valid': True, 'new_value': '2024-01-01'}
        
        await bot.handle_message(mock_update, mock_context)
        
        assert mock_context.user_data['pending_tx']['date'] == '2024-01-01'
        assert 'state' not in mock_context.user_data
        mock_update.message.reply_text.assert_called()
        assert "Berhasil diubah" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_handle_message_casual_chat(mock_update, mock_context, setup_bot_components):
    mock_update.message.text = "Halo bot, apa kabar?"
    mock_ai = setup_bot_components['ai']
    mock_ai.parse_transaction.return_value = {'is_transaction': False}
    mock_ai.chat_response.return_value = "Kabar baik!"
    
    await bot.handle_message(mock_update, mock_context)
    
    mock_ai.chat_response.assert_called_once()
    mock_update.message.reply_text.assert_called_once()
    assert "Kabar baik!" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_send_report_callback(mock_update, mock_context, setup_bot_components):
    mock_update.callback_query = AsyncMock()
    mock_update.callback_query.message = MagicMock()
    mock_update.callback_query.message.reply_text = AsyncMock()
    
    await bot.send_report(mock_update, mock_context)
    
    mock_update.callback_query.message.reply_text.assert_called_with(
        "Pilih periode laporan:", 
        reply_markup=ANY
    )

@pytest.mark.asyncio
async def test_handle_photo_success(mock_update, mock_context, setup_bot_components):
    mock_photo = MagicMock()
    mock_photo.get_file = AsyncMock()
    mock_file = AsyncMock()
    mock_file.download_to_drive = AsyncMock()
    mock_photo.get_file.return_value = mock_file
    mock_update.message.photo = [mock_photo]
    
    # Setup processing_msg mock
    processing_msg = AsyncMock()
    mock_update.message.reply_text.return_value = processing_msg
    
    mock_ocr = setup_bot_components['ocr']
    mock_ocr.process_receipt.return_value = {'amount': 50000, 'merchant': 'Test Store', 'date': '2024-02-05'}
    
    with patch('os.path.exists', return_value=True), \
         patch('os.remove') as mock_remove:
        await bot.handle_photo(mock_update, mock_context)
        
        assert mock_context.user_data['pending_tx']['amount'] == 50000
        mock_update.message.reply_text.assert_called_with("Sedang memproses struk... ⏳")
        processing_msg.edit_text.assert_called()
        mock_remove.assert_called()

@pytest.mark.asyncio
async def test_handle_photo_failure(mock_update, mock_context, setup_bot_components):
    mock_photo = MagicMock()
    mock_photo.get_file = AsyncMock()
    mock_file = AsyncMock()
    mock_file.download_to_drive = AsyncMock()
    mock_photo.get_file.return_value = mock_file
    mock_update.message.photo = [mock_photo]
    
    # Setup processing_msg mock
    processing_msg = AsyncMock()
    mock_update.message.reply_text.return_value = processing_msg
    
    mock_ocr = setup_bot_components['ocr']
    mock_ocr.process_receipt.return_value = {'amount': 0}
    
    with patch('os.path.exists', return_value=True), \
         patch('os.remove'):
        await bot.handle_photo(mock_update, mock_context)
        
        assert "Maaf, aku nggak nemu total harganya" in processing_msg.edit_text.call_args[0][0]

@pytest.mark.asyncio
async def test_handle_callback_report(mock_update, mock_context, setup_bot_components):
    query = AsyncMock()
    query.data = "report_7days"
    query.message = AsyncMock()
    mock_update.callback_query = query
    
    mock_budget_mgr = setup_bot_components['budget_mgr']
    mock_budget_mgr.generate_report.return_value = "Laporan 7 Hari"
    
    # Mock visual_reporter to return None to avoid photo sending logic in this test
    setup_bot_components['visual_reporter'].generate_expense_pie.return_value = None
    
    await bot.handle_callback(mock_update, mock_context)
    query.edit_message_text.assert_called()
    assert "Laporan 7 Hari" in query.edit_message_text.call_args[0][0]

@pytest.mark.asyncio
async def test_handle_callback_tx_confirm_with_date(mock_update, mock_context, setup_bot_components):
    query = AsyncMock()
    query.data = "tx_confirm"
    mock_update.callback_query = query
    mock_context.user_data['pending_tx'] = {
        'amount': 50000, 
        'category': 'Makanan', 
        'date': '2024-01-01',
        'merchant': 'Warung'
    }
    
    mock_db = setup_bot_components['db']
    mock_budget_mgr = setup_bot_components['budget_mgr']
    mock_budget_mgr.check_budget_status.return_value = "Budget aman"
    
    with patch('bot.update_pinned_dashboard') as mock_pinned:
        await bot.handle_callback(mock_update, mock_context)
        
        mock_db.add_transaction.assert_called()
        # Check if date was parsed correctly (roughly)
        call_args = mock_db.add_transaction.call_args[1]
        assert call_args['trans_date'].year == 2024
        assert "Budget aman" in query.edit_message_text.call_args[0][0]

@pytest.mark.asyncio
async def test_handle_callback_tx_edit_options(mock_update, mock_context, setup_bot_components):
    query = AsyncMock()
    query.data = "tx_edit"
    mock_update.callback_query = query
    
    await bot.handle_callback(mock_update, mock_context)
    assert "Pilih bagian yang ingin diubah" in query.edit_message_text.call_args[0][0]

@pytest.mark.asyncio
async def test_handle_callback_edit_amount(mock_update, mock_context, setup_bot_components):
    query = AsyncMock()
    query.data = "edit_amount"
    mock_update.callback_query = query
    
    await bot.handle_callback(mock_update, mock_context)
    assert mock_context.user_data['state'] == 'WAITING_EDIT_AMOUNT'

@pytest.mark.asyncio
async def test_handle_callback_edit_category(mock_update, mock_context, setup_bot_components):
    query = AsyncMock()
    query.data = "edit_category"
    mock_update.callback_query = query
    
    await bot.handle_callback(mock_update, mock_context)
    assert mock_context.user_data['state'] == 'WAITING_EDIT_CATEGORY'

