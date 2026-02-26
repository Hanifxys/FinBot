import logging
from database.db_handler import DBHandler
from modules.ocr import OCRProcessor
from modules.nlp import NLPProcessor
from modules.budget import BudgetManager
from modules.analysis import ExpenseAnalyzer
from modules.rules import RuleEngine
from modules.ai_engine import AIEngine
from modules.premium_ai import PremiumAIEngine
from utils.visuals import VisualReporter
from modules.websocket_server import WebSocketServer

# Initialize Shared instances properly
db = DBHandler()
ocr = OCRProcessor()
nlp = NLPProcessor()
ai = AIEngine()
premium_ai = PremiumAIEngine()
budget_mgr = BudgetManager(db)
analyzer = ExpenseAnalyzer(db)
rules = RuleEngine()
visual_reporter = VisualReporter()

# Global WebSocket Server Instance
ws_server = WebSocketServer(port=int(os.getenv("WS_PORT", 8001)))

def init_components():
    """
    Initialize components. 
    """
    logging.info("Core components initialized with Supabase API")
    # Start WS Server in background
    ws_server.start_in_thread()
