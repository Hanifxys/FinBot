import sys
import os
from unittest.mock import MagicMock
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.nlp import NLPProcessor
from modules.rules import RuleEngine

def run_verification():
    print("🚀 Memulai Verifikasi Flow FinBot (Lightweight)...\n")
    
    # 1. Verifikasi NLP (Input Text -> Data)
    print("--- 1. Verifikasi NLP ---")
    nlp = NLPProcessor()
    text = "ngopi di mixue 48rb"
    amount, category, type_ = nlp.process_text(text)
    merchant = nlp.extract_merchant(text)
    
    assert amount == 48000, f"Expected 48000, got {amount}"
    assert category == "Makanan", f"Expected Makanan, got {category}"
    assert merchant == "Mixue", f"Expected Mixue, got {merchant}"
    print("✅ NLP: OK (Input terbaca dengan benar)")
    
    # 2. Verifikasi Rule Engine (Data -> Tags)
    print("\n--- 2. Verifikasi Rule Engine ---")
    rules = RuleEngine()
    tags = rules.evaluate({"category": "Makanan", "amount": 60000, "hour": 12})
    assert "boros" in tags, "Expected 'boros' tag for Makanan > 50rb"
    print("✅ Rule Engine: OK (Aturan 'boros' terdeteksi)")
    
    try:
        from modules.budget import BudgetManager
        from modules.analysis import ExpenseAnalyzer
        
        # 3. Verifikasi Budget Allocation (Salary -> Recommendation)
        print("\n--- 3. Verifikasi Budget Allocation ---")
        db_mock = MagicMock()
        bm = BudgetManager(db_mock)
        msg, recs = bm.get_allocation_recommendation(5000000)
        assert recs["Kebutuhan Pokok"] == 2500000, "50% of 5jt should be 2.5jt"
        assert recs["Tabungan"] == 1000000, "20% of 5jt should be 1jt"
        print("✅ Budget Manager: OK (Alokasi 50/20/10/20 akurat)")
        
        # 4. Verifikasi Health Score (Transactions -> Score)
        print("\n--- 4. Verifikasi Health Score ---")
        analyzer = ExpenseAnalyzer(db_mock)
        db_mock.get_latest_income.return_value = MagicMock(amount=5000000)
        db_mock.get_user_budgets.return_value = []
        db_mock.get_monthly_report.return_value = []
        
        score = analyzer.calculate_health_score(1)
        assert score == 100, "Perfect user should get score 100"
        print("✅ Analysis: OK (Health Score terhitung)")
    except ImportError as e:
        print(f"\n⚠️ Skipping Budget & Analysis tests: {e}")
        print("   (Harap install pandas untuk verifikasi penuh)")

    print("\n✨ FLOW DASAR TERVERIFIKASI!")

if __name__ == "__main__":
    try:
        run_verification()
    except AssertionError as e:
        print(f"\n❌ VERIFIKASI GAGAL: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR TERJADI: {e}")
        sys.exit(1)
