import os

os.environ["GROQ_API_KEY"] = ""

from modules.nlp import NLPProcessor


class _MockBackend:
    is_ready = True

    def classify_intent(self, text, intent_descriptions, context_messages=None):
        return {"intent": "ADD_TRANSACTION", "confidence": 0.93, "source": "mock_transformer"}

    def benchmark_intent_latency(self, texts, intent_descriptions, rounds=1):
        return {"samples": len(texts), "p95_ms": 5.5}


def test_context_intent_classification_prefers_transformer():
    nlp = NLPProcessor()
    nlp.transformer_backend = _MockBackend()
    res = nlp.classify_intent_with_context(
        "itu yang tadi aku bilang jadi catat ya",
        context_messages=["kemarin makan di warteg", "25rb"],
    )
    assert res["intent"] == "ADD_TRANSACTION"
    assert res["source"] == "mock_transformer"


def test_extract_transaction_data_with_context_merges_partial():
    nlp = NLPProcessor()
    res = nlp.extract_transaction_data_with_context(
        "25rb",
        context_messages=["di mixue"],
    )
    assert res.get("amount") == 25000.0
    assert res.get("merchant") == "Mixue"
    assert res.get("is_partial") is False


def test_intent_benchmark_metrics_shape():
    nlp = NLPProcessor()
    samples = [
        {"text": "makan 20rb", "intent": "ADD_TRANSACTION"},
        {"text": "cek budget", "intent": "CHECK_BUDGET"},
        {"text": "halo", "intent": "GREETING"},
    ]
    metrics = nlp.evaluate_intent_benchmark(samples)
    assert metrics["samples"] == 3
    assert 0.0 <= metrics["accuracy"] <= 1.0
    assert "confusion_matrix" in metrics


def test_transaction_extraction_metrics_shape():
    nlp = NLPProcessor()
    samples = [
        {"text": "makan 20rb di warteg", "amount": 20000, "category": "Makanan", "merchant": "Warteg"},
        {"text": "isi bensin 50rb", "amount": 50000, "category": "Transportasi", "merchant": "Transaksi"},
    ]
    metrics = nlp.evaluate_transaction_extraction(samples)
    assert metrics["samples"] == 2
    assert "amount_mae" in metrics
    assert "field_f1" in metrics
