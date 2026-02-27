import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.append(os.getcwd())

from modules.nlp import NLPProcessor


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _read_json(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
        return data["data"]
    raise ValueError(f"Unsupported JSON structure in {path}")


def load_rows(path: str) -> List[Dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(file_path)
    if file_path.suffix.lower() == ".jsonl":
        return _read_jsonl(file_path)
    if file_path.suffix.lower() == ".json":
        return _read_json(file_path)
    raise ValueError("Only .json or .jsonl files are supported")


def build_hf_intent_rows(
    dataset_name: str,
    split: str,
    text_col: str,
    intent_col: str,
    max_samples: int,
) -> List[Dict[str, Any]]:
    try:
        from datasets import load_dataset
    except Exception as exc:
        raise RuntimeError(
            "datasets package is required for --hf-dataset mode. Install with: pip install datasets"
        ) from exc

    ds = load_dataset(dataset_name, split=split)
    rows: List[Dict[str, Any]] = []
    for i, item in enumerate(ds):
        if max_samples and i >= max_samples:
            break
        rows.append({"text": str(item.get(text_col, "")), "intent": str(item.get(intent_col, "UNKNOWN"))})
    return rows


def main():
    parser = argparse.ArgumentParser(description="Evaluate FinBot NLP quality and production efficiency.")
    parser.add_argument("--intent-file", type=str, help="Path to intent dataset (.json/.jsonl)")
    parser.add_argument("--tx-file", type=str, help="Path to transaction extraction dataset (.json/.jsonl)")
    parser.add_argument("--hf-dataset", type=str, help="HuggingFace dataset name for intent benchmark")
    parser.add_argument("--hf-split", type=str, default="test", help="Dataset split for --hf-dataset")
    parser.add_argument("--text-col", type=str, default="text", help="Text column in HF dataset")
    parser.add_argument("--intent-col", type=str, default="intent", help="Intent label column in HF dataset")
    parser.add_argument("--max-samples", type=int, default=0, help="Cap dataset size for quick benchmarking")
    parser.add_argument("--rounds", type=int, default=1, help="Number of rounds for latency benchmark")
    parser.add_argument(
        "--latency-texts",
        type=str,
        default="makan 25rb di warteg|cek budget bulan ini|halo finbot|split bill 450rb bagi 3 orang",
        help="Pipe-separated texts used for latency benchmark",
    )
    args = parser.parse_args()

    nlp = NLPProcessor()

    report: Dict[str, Any] = {"backend_transformer_enabled": bool(nlp.transformer_backend)}

    if args.hf_dataset:
        rows = build_hf_intent_rows(
            dataset_name=args.hf_dataset,
            split=args.hf_split,
            text_col=args.text_col,
            intent_col=args.intent_col,
            max_samples=args.max_samples,
        )
        report["intent_metrics"] = nlp.evaluate_intent_benchmark(rows)
    elif args.intent_file:
        rows = load_rows(args.intent_file)
        if args.max_samples:
            rows = rows[: args.max_samples]
        report["intent_metrics"] = nlp.evaluate_intent_benchmark(rows)

    if args.tx_file:
        tx_rows = load_rows(args.tx_file)
        if args.max_samples:
            tx_rows = tx_rows[: args.max_samples]
        report["transaction_metrics"] = nlp.evaluate_transaction_extraction(tx_rows)

    latency_texts = [x.strip() for x in args.latency_texts.split("|") if x.strip()]
    report["latency_benchmark"] = nlp.benchmark_production_inference(latency_texts, rounds=max(1, args.rounds))

    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
