import json
import asyncio
from unittest.mock import AsyncMock, MagicMock

from modules.ai_engine import AIEngine


def test_parse_transaction_coerces_llm_schema():
    ai = AIEngine()
    ai._safe_ai_call = AsyncMock(
        return_value=json.dumps(
            {
                "amount": "50000",
                "category": "makanan",
                "merchant": "Warteg Sederhana",
                "type": "expense",
                "is_transaction": True,
            }
        )
    )

    out = asyncio.run(ai.parse_transaction("makan warteg 50rb"))
    assert out["amount"] == 50000.0
    assert out["category"] == "Makanan"
    assert out["is_transaction"] is True


def test_detect_autonomous_intent_coerces_and_applies_threshold():
    ai = AIEngine()
    ai._safe_ai_call = AsyncMock(
        return_value=json.dumps(
            {
                "intent": "query_budget",
                "confidence": 0.91,
                "structured_data": {"period": "monthly"},
                "suggested_response": "Sisa budget bulan ini aman.",
                "needs_live_update": True,
            }
        )
    )
    out = asyncio.run(ai.detect_autonomous_intent("sisa budget bulan ini"))
    assert out["intent"] == "query_budget"
    assert out["confidence"] >= 0.9
    assert out["needs_live_update"] is True


def test_chat_response_fallback_contains_finbot():
    ai = AIEngine()
    ai._safe_ai_call = AsyncMock(return_value=None)
    text = asyncio.run(ai.chat_response("halo", user_name="Ayu"))
    assert "FinBot" in text


def test_benchmark_production_returns_metrics():
    ai = AIEngine()
    ai.parse_transaction = AsyncMock(return_value=ai._fallback_parse())
    ai.detect_autonomous_intent = AsyncMock(return_value=ai._fallback_intent())
    ai.chat_response = AsyncMock(return_value="ok")
    metrics = asyncio.run(ai.benchmark_production(["a", "b"], rounds=1))
    assert metrics["samples"] == 2
    assert "throughput_qps" in metrics
