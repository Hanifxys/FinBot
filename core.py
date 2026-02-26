import logging
from database.db_handler import DBHandler
from modules.ocr import OCRProcessor
from modules.nlp import NLPProcessor
from modules.budget import BudgetManager
from modules.analysis import ExpenseAnalyzer
from modules.rules import RuleEngine
from modules.ai_engine import AIEngine
from utils.visuals import VisualReporter

# Initialize Shared instances lazily or properly
db = DBHandler()
ocr = OCRProcessor()
nlp = NLPProcessor()
ai = AIEngine()
budget_mgr = BudgetManager(db)
analyzer = ExpenseAnalyzer(db)
rules = RuleEngine()
visual_reporter = VisualReporter()

def init_components():
    """
    Initialize components. 
    Database initialization is now handled by Supabase, 
    so this is mostly for backward compatibility.
    """
    logging.info("Core components initialized with Supabase API")
    pass
