import time
import asyncio
import pandas as pd
from unittest.mock import MagicMock
from datetime import datetime, timedelta
from modules.financial_intelligence import FinancialIntelligenceEngine

async def run_benchmark():
    print("🚀 Starting Financial Intelligence Benchmark...")
    
    # Mock Setup
    db = MagicMock()
    class MockTx:
        def __init__(self, id, amount, category, type, date):
            self.id = id
            self.amount = amount
            self.category = category
            self.type = type
            self.date = date
            self.description = "Benchmark Tx"

    # Generate 1000 transactions
    txs = [
        MockTx(i, 50000 + (i % 10)*5000, "Category_"+str(i % 5), "expense", datetime.now() - timedelta(hours=i))
        for i in range(1000)
    ]
    db.get_sliding_window_transactions.return_value = txs
    db.get_monthly_report.return_value = txs[:30]
    db.get_user_budgets.return_value = []
    
    engine = FinancialIntelligenceEngine(db)
    
    tasks = [
        ("Category Avg", engine.analyze_category_averages(1)),
        ("Anomalies", engine.detect_anomalies(1)),
        ("Cashflow Forecast", engine.forecast_cashflow(1)),
        ("Health Score", engine.calculate_health_score(1)),
        ("Pattern Modeling", engine.model_spending_patterns(1))
    ]
    
    results = []
    for name, task in tasks:
        start = time.perf_counter()
        try:
            await task
            duration = (time.perf_counter() - start) * 1000
            results.append({"Feature": name, "Latency (ms)": round(duration, 2), "Status": "PASS"})
        except Exception as e:
            results.append({"Feature": name, "Latency (ms)": 0, "Status": f"FAIL: {e}"})
            
    print("\n📊 Benchmark Results:")
    df = pd.DataFrame(results)
    print(df.to_string(index=False))
    
    avg_latency = df[df['Status'] == 'PASS']['Latency (ms)'].mean()
    print(f"\n✨ Average Successful Latency: {avg_latency:.2f} ms")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
