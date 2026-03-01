import json
import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.semantic_classifier import SemanticCategoryClassifier


def load_jsonl(path: str):
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def train_and_eval(dataset_path: str, model_path: str):
    rows = load_jsonl(dataset_path)
    split = int(len(rows) * 0.8)
    train = rows[:split]
    test = rows[split:]

    clf = SemanticCategoryClassifier()
    clf.train(train)
    clf.save(model_path)

    hit = 0
    for r in test:
        pred = clf.predict(r["text"])
        if pred.category == r["category"]:
            hit += 1

    acc = (hit / len(test)) if test else 0.0
    return {"accuracy": round(acc, 4), "samples": len(test), "trained": clf.is_trained}


def main():
    dataset = "data/nlp_id_daily_1000.jsonl"
    model = "models/semantic_classifier_id.json"
    result = train_and_eval(dataset, model)
    print(result)


if __name__ == "__main__":
    main()
