import logging
import math
import os
import re
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, List, Optional, Sequence, Tuple

from modules.amounts import parse_primary_amount_id

logger = logging.getLogger(__name__)

try:
    import torch
    from transformers import AutoModel, AutoTokenizer, pipeline

    TRANSFORMERS_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only when deps are missing
    torch = None
    AutoModel = None
    AutoTokenizer = None
    pipeline = None
    TRANSFORMERS_AVAILABLE = False


@dataclass
class TransformerNLPConfig:
    enabled: bool = os.getenv("NLP_ENABLE_TRANSFORMERS", "true").lower() in ("1", "true", "yes", "on")
    intent_model: str = os.getenv("NLP_INTENT_MODEL", "joeddav/xlm-roberta-large-xnli")
    ner_model: str = os.getenv("NLP_NER_MODEL", "Davlan/xlm-roberta-base-ner-hrl")
    attention_model: str = os.getenv(
        "NLP_ATTENTION_MODEL",
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    )
    max_length: int = int(os.getenv("NLP_TRANSFORMER_MAX_LENGTH", "192"))
    max_context_turns: int = int(os.getenv("NLP_MAX_CONTEXT_TURNS", "3"))
    intent_threshold: float = float(os.getenv("NLP_INTENT_THRESHOLD", "0.68"))
    category_threshold: float = float(os.getenv("NLP_CATEGORY_THRESHOLD", "0.55"))
    enable_attention: bool = os.getenv("NLP_ENABLE_ATTENTION", "true").lower() in ("1", "true", "yes", "on")
    quantize_cpu: bool = os.getenv("NLP_QUANTIZE_CPU", "true").lower() in ("1", "true", "yes", "on")
    cache_size: int = int(os.getenv("NLP_TRANSFORMER_CACHE_SIZE", "1024"))


class TransformerNLPBackend:
    """Multilingual transformer backend for intent/category/entity inference."""

    _ID_HINTS = {"saya", "aku", "gua", "gw", "nih", "dong", "makan", "bayar", "beli", "uang"}
    _EN_HINTS = {"i", "you", "spent", "spending", "expense", "income", "budget", "report", "help"}

    def __init__(self, config: Optional[TransformerNLPConfig] = None):
        self.config = config or TransformerNLPConfig()
        self.enabled = bool(self.config.enabled and TRANSFORMERS_AVAILABLE)
        self.device = 0 if (self.enabled and torch and torch.cuda.is_available()) else -1

        self._zero_shot = None
        self._ner = None
        self._attention_model = None
        self._attention_tokenizer = None
        self._lock = Lock()

        self._intent_cache: Dict[Tuple[str, Tuple[str, ...]], Dict[str, Any]] = {}
        self._category_cache: Dict[Tuple[str, Tuple[str, ...]], Tuple[str, float]] = {}

    @property
    def is_ready(self) -> bool:
        return self.enabled

    def _load_zero_shot(self):
        if self._zero_shot is not None:
            return self._zero_shot
        if not self.enabled:
            return None

        with self._lock:
            if self._zero_shot is None:
                try:
                    self._zero_shot = pipeline(
                        "zero-shot-classification",
                        model=self.config.intent_model,
                        tokenizer=self.config.intent_model,
                        device=self.device,
                    )
                except Exception as exc:
                    logger.error("Transformer zero-shot init failed: %s", exc)
                    self._zero_shot = None
        return self._zero_shot

    def _load_ner(self):
        if self._ner is not None:
            return self._ner
        if not self.enabled:
            return None

        with self._lock:
            if self._ner is None:
                try:
                    self._ner = pipeline(
                        "token-classification",
                        model=self.config.ner_model,
                        tokenizer=self.config.ner_model,
                        aggregation_strategy="simple",
                        device=self.device,
                    )
                except Exception as exc:
                    logger.error("Transformer NER init failed: %s", exc)
                    self._ner = None
        return self._ner

    def _load_attention_stack(self):
        if self._attention_model is not None and self._attention_tokenizer is not None:
            return self._attention_model, self._attention_tokenizer
        if not self.enabled or not self.config.enable_attention:
            return None, None

        with self._lock:
            if self._attention_model is None or self._attention_tokenizer is None:
                try:
                    tokenizer = AutoTokenizer.from_pretrained(self.config.attention_model, use_fast=True)
                    model = AutoModel.from_pretrained(self.config.attention_model)
                    model.eval()

                    if self.device >= 0:
                        model = model.to("cuda")
                    elif self.config.quantize_cpu and torch is not None:
                        try:
                            model = torch.quantization.quantize_dynamic(
                                model, {torch.nn.Linear}, dtype=torch.qint8
                            )
                        except Exception:
                            # Quantization is best-effort only.
                            pass

                    self._attention_tokenizer = tokenizer
                    self._attention_model = model
                except Exception as exc:
                    logger.error("Transformer attention stack init failed: %s", exc)
                    self._attention_model = None
                    self._attention_tokenizer = None

        return self._attention_model, self._attention_tokenizer

    def _cache_set(self, cache: Dict[Any, Any], key: Any, value: Any):
        if len(cache) >= max(8, self.config.cache_size):
            # Drop oldest inserted item (deterministic FIFO in py>=3.7).
            cache.pop(next(iter(cache)))
        cache[key] = value

    def detect_language(self, text: str) -> str:
        text_l = (text or "").lower()
        tokens = set(re.findall(r"\b\w+\b", text_l))

        id_score = len(tokens.intersection(self._ID_HINTS))
        en_score = len(tokens.intersection(self._EN_HINTS))

        if id_score == 0 and en_score == 0:
            return "unknown"
        return "id" if id_score >= en_score else "en"

    def _build_contextual_text(self, text: str, context_messages: Optional[Sequence[str]]) -> str:
        if not context_messages:
            return text
        tail = [m.strip() for m in context_messages if m and m.strip()][-self.config.max_context_turns :]
        if not tail:
            return text
        return " [CTX] " + " </s> ".join(tail) + f" [QUERY] {text}"

    def classify_intent(
        self,
        text: str,
        intent_descriptions: Dict[str, str],
        context_messages: Optional[Sequence[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        pipe = self._load_zero_shot()
        if not pipe or not text or not intent_descriptions:
            return None

        model_input = self._build_contextual_text(text, context_messages)
        labels = tuple(intent_descriptions.keys())
        key = (model_input, labels)
        if key in self._intent_cache:
            return self._intent_cache[key]

        try:
            out = pipe(
                model_input,
                list(labels),
                multi_label=False,
                hypothesis_template="Intent pesan pengguna adalah {}.",
            )
            top_label = out["labels"][0]
            top_score = float(out["scores"][0])
            if top_score < self.config.intent_threshold:
                return None

            result = {
                "intent": top_label,
                "confidence": top_score,
                "source": "transformer_zero_shot",
                "language": self.detect_language(model_input),
            }
            if self.config.enable_attention:
                attn = self.attention_summary(model_input)
                if attn:
                    result["attention"] = attn

            self._cache_set(self._intent_cache, key, result)
            return result
        except Exception as exc:
            logger.error("Transformer intent classification failed: %s", exc)
            return None

    def classify_category(self, text: str, categories: Sequence[str]) -> Tuple[str, float]:
        pipe = self._load_zero_shot()
        if not pipe or not text or not categories:
            return "Lain-lain", 0.0

        labels = tuple(categories)
        key = (text, labels)
        if key in self._category_cache:
            return self._category_cache[key]

        try:
            out = pipe(
                text,
                list(labels),
                multi_label=False,
                hypothesis_template="Kategori finansial untuk transaksi ini adalah {}.",
            )
            guess = out["labels"][0]
            conf = float(out["scores"][0])
            if conf < self.config.category_threshold:
                guess = "Lain-lain"
            value = (guess, conf)
            self._cache_set(self._category_cache, key, value)
            return value
        except Exception as exc:
            logger.error("Transformer category classification failed: %s", exc)
            return "Lain-lain", 0.0

    @staticmethod
    def _clean_entity_word(word: str) -> str:
        if not word:
            return ""
        cleaned = word.replace("##", "").replace("▁", " ").strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = cleaned.strip(" ,.-")
        return cleaned

    def extract_entities(self, text: str, categories: Optional[Sequence[str]] = None) -> Optional[Dict[str, Any]]:
        if not text:
            return None

        amount = parse_primary_amount_id(text)
        merchant = None
        ner_pipe = self._load_ner()
        if ner_pipe:
            try:
                ents = ner_pipe(text)
                candidates = []
                for ent in ents:
                    group = (ent.get("entity_group") or "").upper()
                    word = self._clean_entity_word(ent.get("word", ""))
                    score = float(ent.get("score", 0.0))
                    if group in {"ORG", "PER", "MISC", "LOC"} and len(word) >= 3:
                        candidates.append((word, score))
                if candidates:
                    # Prioritize confidence and token length to avoid short noisy entities.
                    candidates.sort(key=lambda x: (x[1], len(x[0])), reverse=True)
                    merchant = candidates[0][0]
            except Exception as exc:
                logger.error("Transformer entity extraction failed: %s", exc)

        category = "Lain-lain"
        cat_conf = 0.0
        if categories:
            category, cat_conf = self.classify_category(text, categories)

        if amount is None and not merchant and category == "Lain-lain":
            return None

        confidence = min(
            0.98,
            (0.5 if amount else 0.0) + (0.25 if merchant else 0.0) + (0.25 * cat_conf),
        )
        return {
            "amount": float(amount) if amount is not None else None,
            "merchant": merchant or "Transaksi",
            "category": category,
            "confidence": confidence,
            "is_partial": amount is None or category == "Lain-lain" or (merchant or "Transaksi") == "Transaksi",
            "source": "transformer_ner",
        }

    def attention_summary(self, text: str, top_k: int = 6) -> Optional[Dict[str, Any]]:
        model, tokenizer = self._load_attention_stack()
        if not model or not tokenizer or not text:
            return None

        try:
            encoded = tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                max_length=self.config.max_length,
            )
            if self.device >= 0:
                encoded = {k: v.to("cuda") for k, v in encoded.items()}

            with torch.no_grad():
                out = model(**encoded, output_attentions=True)

            if not out.attentions:
                return None

            # Last layer, averaged across heads => [seq, seq]
            att = out.attentions[-1].mean(dim=1)[0]
            cls_att = att[0].detach().float().cpu().tolist()
            token_ids = encoded["input_ids"][0].detach().cpu().tolist()
            tokens = tokenizer.convert_ids_to_tokens(token_ids)

            scored = []
            for idx, tok in enumerate(tokens):
                if tok in tokenizer.all_special_tokens:
                    continue
                score = float(cls_att[idx]) if idx < len(cls_att) else 0.0
                scored.append((tok, max(score, 0.0)))

            if not scored:
                return None

            total = sum(s for _, s in scored) or 1.0
            probs = [s / total for _, s in scored]
            entropy = -sum(p * math.log(max(p, 1e-12)) for p in probs)
            entropy_norm = entropy / math.log(max(len(probs), 2))

            scored.sort(key=lambda x: x[1], reverse=True)
            return {
                "top_tokens": [{"token": t, "score": round(s, 4)} for t, s in scored[:top_k]],
                "attention_entropy": round(float(entropy_norm), 4),
            }
        except Exception as exc:
            logger.error("Transformer attention summary failed: %s", exc)
            return None

    @staticmethod
    def _percentile(values: List[float], pct: float) -> float:
        if not values:
            return 0.0
        idx = int(round((pct / 100.0) * (len(values) - 1)))
        idx = max(0, min(idx, len(values) - 1))
        return values[idx]

    def benchmark_intent_latency(
        self,
        texts: Sequence[str],
        intent_descriptions: Dict[str, str],
        rounds: int = 1,
    ) -> Dict[str, float]:
        if not texts:
            return {"samples": 0, "p50_ms": 0.0, "p95_ms": 0.0, "throughput_qps": 0.0}

        timings: List[float] = []
        start_total = time.perf_counter()
        for _ in range(max(1, rounds)):
            for text in texts:
                t0 = time.perf_counter()
                self.classify_intent(text, intent_descriptions)
                timings.append((time.perf_counter() - t0) * 1000.0)

        elapsed = max(time.perf_counter() - start_total, 1e-9)
        timings.sort()
        return {
            "samples": float(len(timings)),
            "p50_ms": round(self._percentile(timings, 50.0), 2),
            "p90_ms": round(self._percentile(timings, 90.0), 2),
            "p95_ms": round(self._percentile(timings, 95.0), 2),
            "throughput_qps": round(len(timings) / elapsed, 2),
        }
