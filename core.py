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
from modules.oom_engine import OOMEngine
from modules.ai_persona import PersonaManager
from modules.financial_intelligence import FinancialIntelligenceEngine
from modules.multimodal_engine import MultiModalEngine
from modules.market_data import MarketDataConnector
from modules.document_processor import DocumentProcessor
from modules.ux_analytics import UXAnalytics
from modules.recurring import RecurringManager
from modules.budget_autopilot import BudgetAutopilot
from modules.weekly_challenges import WeeklyChallengeManager
from modules.personal_finance_ai import PersonalFinanceAI

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
gamify = GamificationEngine()
oom_engine = OOMEngine(db, premium_ai)
persona_mgr = PersonaManager()
fin_intel = FinancialIntelligenceEngine(db)
multimodal_ai = MultiModalEngine()
market_data = MarketDataConnector(api_key=os.getenv("ALPHA_VANTAGE_KEY"))
doc_processor = DocumentProcessor()
ux_analytics = UXAnalytics()
recurring_mgr = RecurringManager(db)
autopilot_mgr = BudgetAutopilot(db)
weekly_challenges = WeeklyChallengeManager()
personal_finance_ai = PersonalFinanceAI(db, persona_mgr)

# Global WebSocket Server Instance
ws_server = WebSocketServer(port=int(os.getenv("WS_PORT", 8001)))

def init_components():
    """
    Initialize components. 
    """
    logging.info("Core components initialized with Supabase API")
    # Start WS Server in background
    ws_server.start_in_thread()
    # Start OOM Engine for Real-time Monitoring
    try:
        oom_engine.start()
    except Exception as e:
        logging.error(f"Failed to start OOM Engine: {e}")
    # Start Monitoring API for Koyeb Health Checks
    try:
        from modules.monitor import start_monitor_thread
        start_monitor_thread(db=db, premium_ai=premium_ai, ws_server=ws_server, oom_engine=oom_engine, fin_intel=fin_intel, auth_secret=os.getenv("WEB_JWT_SECRET", ""))
    except Exception as e:
        logging.error(f"Failed to start monitor: {e}")
