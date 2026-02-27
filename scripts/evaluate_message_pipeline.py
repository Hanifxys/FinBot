import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.append(os.getcwd())

from modules.nlp import NLPProcessor


def _read_rows(path: str) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    if p.suffix.lower() == ".jsonl":
        rows = []
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows
    data = json.loads(p.read_text(encoding="utf-8-sig"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return data["data"]
    raise ValueError(f"Unsupported dataset format in {path}")


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = int(round((pct / 100.0) * (len(values) - 1)))
    idx = max(0, min(idx, len(values) - 1))
    return float(values[idx])


def evaluate_router(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    nlp = NLPProcessor()
    y_true, y_pred = [], []
    latency = []
    partial_count = 0
    disamb_count = 0

    for row in rows:
        text = str(row.get("text", ""))
        context_messages = row.get("context_messages") or []
        expected_intent = str(row.get("intent", "UNKNOWN"))
        t0 = time.perf_counter()
        cls = nlp.classify_intent_with_context(text, context_messages=context_messages)
        intent = cls.get("intent", "UNKNOWN")
        if intent not in {
            "ROAST_WALLET", "EXPORT_DATA", "WHAT_IF", "SET_MODE", "SET_REMINDER",
            "CHECK_BUDGET", "SET_GAJI", "UNDO", "EXECUTIVE_MODE", "ELITE_ANALYSIS",
            "INVESTMENT_OPPS", "DOC_ANALYSIS", "SET_BUDGET", "SET_BUDGET_ALERT",
            "QUERY_SUMMARY", "SHARING_INFO", "GREETING", "SMALL_TALK", "HELP",
            "STOP_NOTIF", "CANCEL", "ASK_FOR_NOTIF", "EDIT_TRANSACTION"
        }:
            ext = nlp.extract_transaction_data_with_context(text, context_messages=context_messages, forced_type=cls.get("type"))
            intent = ext.get("intent", intent)
            partial_count += int(bool(ext.get("is_partial")))
            disamb_count += int(bool(ext.get("needs_disambiguation")))
        latency.append((time.perf_counter() - t0) * 1000.0)
        y_true.append(expected_intent)
        y_pred.append(intent)

    try:
        from sklearn.metrics import accuracy_score, precision_recall_fscore_support
        acc = float(accuracy_score(y_true, y_pred))
        p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="macro", zero_division=0)
    except Exception:
        acc = sum(1 for a, b in zip(y_true, y_pred) if a == b) / max(len(y_true), 1)
        p = r = f1 = acc

    return {
        "samples": len(rows),
        "accuracy": round(acc, 4),
        "macro_precision": round(float(p), 4),
        "macro_recall": round(float(r), 4),
        "macro_f1": round(float(f1), 4),
        "latency_p50_ms": round(_percentile(latency, 50.0), 2),
        "latency_p95_ms": round(_percentile(latency, 95.0), 2),
        "partial_rate": round(partial_count / max(len(rows), 1), 4),
        "disambiguation_rate": round(disamb_count / max(len(rows), 1), 4),
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate message routing quality and latency.")
    parser.add_argument("--dataset", required=True, help="JSON/JSONL with fields: text, intent, context_messages(optional)")
    args = parser.parse_args()
    rows = _read_rows(args.dataset)
    report = evaluate_router(rows)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
