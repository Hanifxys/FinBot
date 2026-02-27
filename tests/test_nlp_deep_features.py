from modules.nlp import NLPProcessor


def test_audit_nlp_capabilities_has_priorities():
    nlp = NLPProcessor()
    report = nlp.audit_nlp_capabilities()
    assert "features" in report
    assert "improvement_priorities" in report
    assert isinstance(report["improvement_priorities"], list)
    assert len(report["improvement_priorities"]) >= 2


def test_deep_understanding_analysis_returns_strategy():
    nlp = NLPProcessor()
    res = nlp.deep_understanding_analysis(
        "tolong analisa cashflow dan risiko investasi saham saya bulan ini",
        context_messages=["gaji masuk 10jt", "beli saham bbca 2jt"],
    )
    assert "recommended_strategy" in res
    assert "complexity_score" in res
    assert 0.0 <= float(res["complexity_score"]) <= 1.0
    assert isinstance(res.get("dominant_topics", []), list)


def test_build_finetuning_corpus_formats_output():
    nlp = NLPProcessor()
    rows = [
        {
            "text": "makan 25rb di warteg",
            "intent": "ADD_TRANSACTION",
            "category": "Makanan",
            "amount": 25000,
            "merchant": "Warteg",
            "context_messages": ["lagi laper"],
        }
    ]
    corpus = nlp.build_finetuning_corpus(rows)
    assert len(corpus) == 1
    assert "input" in corpus[0]
    assert "output" in corpus[0]
    assert corpus[0]["output"]["intent"] == "ADD_TRANSACTION"
