import json
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple


DEFAULT_CATEGORIES = [
    "Makanan",
    "Transportasi",
    "Belanja",
    "Lifestyle",
    "Tagihan",
    "Kesehatan",
    "Sosial",
    "Pendidikan",
    "Lain-lain",
]


TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")


def _tokenize(text: str) -> List[str]:
    text = (text or "").lower()
    return [t for t in TOKEN_RE.findall(text) if t]


@dataclass
class Prediction:
    category: str
    confidence: float
    probs: Dict[str, float]


class SemanticCategoryClassifier:
    """
    Lightweight Multinomial Naive Bayes classifier for Indonesian daily text.
    Can be trained on >=1000 samples and loaded at runtime with no extra deps.
    """

    def __init__(self, labels: List[str] = None):
        self.labels = labels or list(DEFAULT_CATEGORIES)
        self.class_counts = Counter()
        self.token_counts = defaultdict(Counter)  # label -> token -> count
        self.total_tokens = Counter()  # label -> total token count
        self.vocab = set()
        self._trained = False

    @property
    def is_trained(self) -> bool:
        return self._trained

    def train(self, samples: List[Dict[str, str]]) -> None:
        # Reset state
        self.class_counts.clear()
        self.token_counts.clear()
        self.total_tokens.clear()
        self.vocab.clear()

        for row in samples:
            text = row.get("text", "")
            label = row.get("category", "Lain-lain")
            if label not in self.labels:
                continue
            toks = _tokenize(text)
            if not toks:
                continue
            self.class_counts[label] += 1
            for tok in toks:
                self.token_counts[label][tok] += 1
                self.total_tokens[label] += 1
                self.vocab.add(tok)

        self._trained = sum(self.class_counts.values()) > 0 and len(self.vocab) > 0

    def predict(self, text: str) -> Prediction:
        if not self._trained:
            return Prediction(category="Lain-lain", confidence=0.0, probs={"Lain-lain": 1.0})

        toks = _tokenize(text)
        if not toks:
            return Prediction(category="Lain-lain", confidence=0.0, probs={"Lain-lain": 1.0})

        alpha = 1.0
        vocab_size = max(1, len(self.vocab))
        total_docs = max(1, sum(self.class_counts.values()))

        log_probs = {}
        for label in self.labels:
            prior = (self.class_counts[label] + alpha) / (total_docs + alpha * len(self.labels))
            lp = math.log(prior)
            denom = self.total_tokens[label] + alpha * vocab_size
            for tok in toks:
                num = self.token_counts[label][tok] + alpha
                lp += math.log(num / denom)
            log_probs[label] = lp

        # softmax
        max_lp = max(log_probs.values())
        exps = {k: math.exp(v - max_lp) for k, v in log_probs.items()}
        z = sum(exps.values()) or 1.0
        probs = {k: exps[k] / z for k in exps}
        category = max(probs, key=probs.get)
        confidence = float(probs.get(category, 0.0))

        return Prediction(category=category, confidence=confidence, probs=probs)

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {
            "labels": self.labels,
            "class_counts": dict(self.class_counts),
            "token_counts": {k: dict(v) for k, v in self.token_counts.items()},
            "total_tokens": dict(self.total_tokens),
            "vocab": sorted(self.vocab),
            "trained": self._trained,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

    @classmethod
    def load(cls, path: str):
        inst = cls()
        if not os.path.exists(path):
            return inst
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        inst.labels = payload.get("labels") or list(DEFAULT_CATEGORIES)
        inst.class_counts = Counter(payload.get("class_counts", {}))
        inst.token_counts = defaultdict(Counter, {k: Counter(v) for k, v in payload.get("token_counts", {}).items()})
        inst.total_tokens = Counter(payload.get("total_tokens", {}))
        inst.vocab = set(payload.get("vocab", []))
        inst._trained = bool(payload.get("trained", False))
        return inst


def split_activity_detail(text: str, category: str = "") -> Tuple[str, str]:
    """
    Split main activity title and additional detail.
    Example: "saya makan di warteg" -> ("Makan", "di warteg")
    """
    raw = (text or "").strip()
    if not raw:
        return "Transaksi", ""

    t = raw.lower()
    t = re.sub(r"\b(saya|aku|gw|gua|lagi|tadi|barusan|nih|dong)\b", "", t)
    t = re.sub(r"\s+", " ", t).strip()

    # common verb patterns
    patterns = [
        (r"\bmakan\b", "Makan"),
        (r"\bminum\b", "Minum"),
        (r"\bbeli\b", "Beli"),
        (r"\bbelanja\b", "Belanja"),
        (r"\bnaik\b", "Transport"),
        (r"\bnonton\b", "Hiburan"),
        (r"\bbayar\b", "Bayar"),
        (r"\bisi\s+bensin\b", "Isi Bensin"),
    ]

    for p, title in patterns:
        m = re.search(p, t)
        if m:
            tail = t[m.end():].strip()
            if tail:
                if not tail.startswith(("di ", "ke ", "untuk ")):
                    tail = "di " + tail
            return title, tail

    # fallback by category
    if category == "Makanan":
        return "Makan", t
    if category == "Transportasi":
        return "Transport", t
    if category == "Belanja":
        return "Belanja", t
    if category == "Lifestyle":
        return "Hiburan", t

    # generic fallback
    toks = _tokenize(t)
    if toks:
        return toks[0].capitalize(), " ".join(toks[1:])
    return "Transaksi", ""
