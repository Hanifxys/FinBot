import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class NLPExternalConfig:
    slang_map: Dict[str, str]
    category_keywords: Dict[str, List[str]]


class NLPConfigLoader:
    """
    Loads NLP slang/category config from JSON and supports lightweight hot reload
    based on mtime checks.
    """

    def __init__(self, path: Optional[str] = None):
        self.path = path or os.getenv("NLP_CONFIG_PATH", "config/nlp_config.json")
        self._last_mtime: float = 0.0
        self._loaded: Optional[NLPExternalConfig] = None

    def _validate(self, raw: Dict[str, Any]) -> NLPExternalConfig:
        if not isinstance(raw, dict):
            raise ValueError("Config must be an object")

        slang_map = raw.get("slang_map", {})
        category_keywords = raw.get("category_keywords", {})

        if not isinstance(slang_map, dict):
            raise ValueError("slang_map must be object")
        if not isinstance(category_keywords, dict):
            raise ValueError("category_keywords must be object")

        clean_slang: Dict[str, str] = {}
        for k, v in slang_map.items():
            if isinstance(k, str) and isinstance(v, str) and k.strip():
                clean_slang[k.strip().lower()] = v.strip().lower()

        clean_categories: Dict[str, List[str]] = {}
        for cat, kws in category_keywords.items():
            if not isinstance(cat, str) or not cat.strip() or not isinstance(kws, list):
                continue
            clean = [str(x).strip().lower() for x in kws if isinstance(x, str) and str(x).strip()]
            if clean:
                clean_categories[cat.strip()] = clean

        return NLPExternalConfig(slang_map=clean_slang, category_keywords=clean_categories)

    def load(self, force: bool = False) -> Optional[NLPExternalConfig]:
        if not os.path.exists(self.path):
            return self._loaded

        try:
            mtime = os.path.getmtime(self.path)
            if not force and self._loaded and mtime <= self._last_mtime:
                return self._loaded

            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            cfg = self._validate(raw)
            self._loaded = cfg
            self._last_mtime = mtime
            logger.info("NLP config loaded from %s", self.path)
            return cfg
        except Exception as exc:
            logger.warning("Failed to load NLP config from %s: %s", self.path, exc)
            return self._loaded


DEFAULT_NLP_CONFIG_SCHEMA = {
    "type": "object",
    "required": ["slang_map", "category_keywords"],
    "properties": {
        "version": {"type": "string"},
        "updated_at": {"type": "string"},
        "locale": {"type": "string"},
        "slang_map": {"type": "object", "additionalProperties": {"type": "string"}},
        "category_keywords": {
            "type": "object",
            "additionalProperties": {
                "type": "array",
                "items": {"type": "string"}
            }
        }
    },
    "additionalProperties": True,
}
