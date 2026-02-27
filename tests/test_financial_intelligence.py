import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta
from modules.financial_intelligence import FinancialIntelligenceEngine, DataQualityError

@pytest.fixture
def mock_db():
    db = MagicMock()
    # Mock transaction object
    class MockTx:
        def __init__(self, id, amount, category, type, date, description="Test"):
            self.id = id
            self.amount = amount
            self.category = category
            self.type = type
            self.date = date
            self.description = description

    # Sample data
    txs = [
        MockTx(i, 100000 + i*1000, "Makanan", "expense", datetime.now() - timedelta(days=i))
        for i in range(30)
    ]
    db.get_sliding_window_transactions.return_value = txs
    
    # Mock budget
    class MockBudget:
        def __init__(self, category, limit, current):
            self.category = category
            self.limit_amount = limit
            self.current_usage = current
    
    db.get_user_budgets.return_value = [
        MockBudget("Makanan", 5000000, 4500000),
        MockBudget("Transportasi", 1000000, 200000)
    ]
    
    db.get_monthly_report.return_value = txs
    db.get_latest_income.return_value = MagicMock(amount=10000000)
    
    return db

@pytest.fixture
def mock_redis():
    with patch("redis.from_url") as mock:
        client = MagicMock()
        client.get.return_value = None
        mock.return_value = client
        yield client

@pytest.mark.asyncio
async def test_analyze_category_averages(mock_db, mock_redis):
    engine = FinancialIntelligenceEngine(mock_db)
    result = await engine.analyze_category_averages(1)
    
    assert "Makanan" in result
    assert result["Makanan"]["average"] > 0
    assert "monthly_growth" in result["Makanan"]

@pytest.mark.asyncio
async def test_detect_budget_drift(mock_db, mock_redis):
    engine = FinancialIntelligenceEngine(mock_db)
    # Mock high usage
    mock_db.get_user_budgets.return_value[0].current_usage = 4900000 # 98%
    
    result = await engine.detect_budget_drift(1)
    assert len(result) > 0
    assert result[0]["category"] == "Makanan"
    assert result[0]["severity"] == "high"

@pytest.mark.asyncio
async def test_detect_anomalies(mock_db, mock_redis):
    engine = FinancialIntelligenceEngine(mock_db)
    result = await engine.detect_anomalies(1)
    # Isolation forest might not find anomalies in perfectly linear data, 
    # but we test if it runs without error
    assert isinstance(result, list)

@pytest.mark.asyncio
async def test_forecast_cashflow(mock_db, mock_redis):
    engine = FinancialIntelligenceEngine(mock_db)
    result = await engine.forecast_cashflow(1, days=7)
    
    assert result["forecast_days"] == 7
    assert len(result["daily_forecast"]) == 7
    assert "predicted_total_flow" in result

@pytest.mark.asyncio
async def test_calculate_health_score(mock_db, mock_redis):
    engine = FinancialIntelligenceEngine(mock_db)
    result = await engine.calculate_health_score(1)
    
    assert 0 <= result["total_score"] <= 1000
    assert "rating" in result
    assert "breakdown" in result

@pytest.mark.asyncio
async def test_insufficient_data_error(mock_db, mock_redis):
    mock_db.get_sliding_window_transactions.return_value = []
    engine = FinancialIntelligenceEngine(mock_db)
    
    with pytest.raises(FinancialIntelligenceEngine.FinancialIntelligenceError):
        await engine.analyze_category_averages(1)
