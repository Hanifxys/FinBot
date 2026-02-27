import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.append(os.getcwd())

from modules.ai_engine import AIEngine


def _read_json(path: Path) -> List[Dict[str, Any]]:
    content = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(content, list):
        return content
    if isinstance(content, dict) and isinstance(content.get("data"), list):
        return content["data"]
    raise ValueError(f"Unsupported JSON structure in {path}")


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_rows(path: str) -> List[Dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(file_path)
    ext = file_path.suffix.lower()
    if ext == ".json":
        return _read_json(file_path)
    if ext == ".jsonl":
        return _read_jsonl(file_path)
    raise ValueError("Only .json or .jsonl files are supported.")


async def run_eval(args):
    engine = AIEngine()
    report: Dict[str, Any] = {"transformer_enabled": bool(engine.transformer_backend)}

    if args.intent_file:
        intent_rows = load_rows(args.intent_file)
        if args.max_samples > 0:
            intent_rows = intent_rows[: args.max_samples]
        report["intent_metrics"] = await engine.evaluate_intent_model(intent_rows)

    if args.tx_file:
        tx_rows = load_rows(args.tx_file)
        if args.max_samples > 0:
            tx_rows = tx_rows[: args.max_samples]
        report["transaction_metrics"] = await engine.evaluate_transaction_parser(tx_rows)

    latency_texts = [x.strip() for x in args.latency_texts.split("|") if x.strip()]
    report["latency_benchmark"] = await engine.benchmark_production(
        latency_texts,
        rounds=max(1, args.rounds),
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Evaluate AIEngine quality and production latency.")
    parser.add_argument("--intent-file", type=str, help="JSON/JSONL file with {'text','intent','context?'}")
    parser.add_argument("--tx-file", type=str, help="JSON/JSONL file with {'text','amount','category','is_transaction'}")
    parser.add_argument("--max-samples", type=int, default=0)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument(
        "--latency-texts",
        type=str,
        default="makan 25rb di warteg|cek budget bulan ini|halo finbot|gaji masuk 5jt",
    )
    args = parser.parse_args()
    asyncio.run(run_eval(args))


if __name__ == "__main__":
    main()
