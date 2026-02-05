import logging
from database.db_handler import DBHandler
from modules.ocr import OCRProcessor
from modules.nlp import NLPProcessor
from modules.budget import BudgetManager
from modules.analysis import ExpenseAnalyzer
from modules.rules import RuleEngine
from modules.ai_engine import AIEngine
from utils.visuals import VisualReporter

# Shared instances
db = DBHandler()
ocr = OCRProcessor()
nlp = NLPProcessor()
ai = AIEngine()
budget_mgr = BudgetManager(db)
analyzer = ExpenseAnalyzer(db)
rules = RuleEngine()
visual_reporter = VisualReporter()

def init_components():
    # This is now handled by module-level instantiation
    # but kept for backward compatibility if needed
    pass
