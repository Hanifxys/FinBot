import logging
import os
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
from modules.gamification import GamificationEngine

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
gamify = GamificationEngine(premium_ai.redis)

# Global WebSocket Server Instance
ws_server = WebSocketServer(port=int(os.getenv("WS_PORT", 8001)))

def init_components():
    """
    Initialize components. 
    """
    logging.info("Core components initialized with Supabase API")
    # Start WS Server in background
    ws_server.start_in_thread()
    # Start Monitoring API for Koyeb Health Checks
    try:
        from modules.monitor import start_monitor_thread
        start_monitor_thread(db=db, premium_ai=premium_ai, ws_server=ws_server, auth_secret=os.getenv("WEB_JWT_SECRET", ""))
    except Exception as e:
        logging.error(f"Failed to start monitor: {e}")
