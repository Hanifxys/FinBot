import re
from dataclasses import dataclass
from typing import List, Optional


# =========================
# CONFIG
# =========================

_SLANG = {
    "gope": 500,
    "goceng": 5000,
    "ceban": 10000,
    "gocap": 50000,
    "cepe": 100000,
    "cepek": 100000,
    "sejuta": 1_000_000,
}

_MULTIPLIER = {
    "k": 1_000,
    "rb": 1_000,
    "ribu": 1_000,
    "jt": 1_000_000,
    "juta": 1_000_000,
}

_NEGATIVE_WORDS = {"utang", "hutang", "minus"}
_PAYMENT_WORDS = {"bayar", "transfer", "kirim"}
_CHANGE_WORDS = {"kembali", "kembalian"}


# =========================
# DATA MODEL
# =========================

@dataclass
class MoneyParseResult:
    amounts: List[float]
    primary: Optional[float]
    change: Optional[float]
    is_negative: bool
    intent: str  # expense | income | payment | unknown


# =========================
# CORE LOGIC
# =========================

def _clean(text: str) -> str:
    t = (text or "").lower()
    t = t.replace("rp", " ").replace("idr", " ")
    # Fix common typos like 'o' instead of '0' in numeric context
    t = re.sub(r"(\d)[oO](\d)", r"\1 0 \2", t) # '1o0' -> '1 0 0'
    t = re.sub(r"(\d)[oO]\b", r"\1 0", t)      # '2o' -> '20'
    t = re.sub(r"\b[oO](\d)", r"0 \1", t)      # 'o5' -> '0 5'
    t = re.sub(r"[^\w\s.,-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _parse_number(num: str) -> float:
    # Handle 'o' typos if they survived clean (case where it's just 'o')
    num = num.lower().replace('o', '0')
    if "." in num and "," not in num:
        num = num.replace(".", "")
    else:
        num = num.replace(",", ".")
    return float(num)


def _extract_numeric_segments(text: str) -> List[float]:
    amounts = []

    # slang
    for word, val in _SLANG.items():
        if re.search(rf"\b{word}\b", text):
            amounts.append(float(val))

    pattern = r"(-?\d+(?:[.,]\d+)?)\s*(k|rb|ribu|jt|juta)?"
    matches = list(re.finditer(pattern, text))

    i = 0
    while i < len(matches):
        m = matches[i]
        base_str = m.group(1)
        unit = m.group(2)
        base = _parse_number(base_str)

        value = base
        if unit:
            value *= _MULTIPLIER[unit]
        else:
            # Naked numbers logic: if 10 <= base <= 999 and it's likely a thousand shorthand
            # Avoid single digits like '3' in 'bagi 3 orang'
            if 10 <= base <= 999 and not any(w in text.lower() for w in ["bagi", "orang", "person"]):
                value *= 1000

        # kombinasi 2 juta 500 ribu
        if unit in ("jt", "juta") and i + 1 < len(matches):
            nxt = matches[i + 1]
            nxt_unit = nxt.group(2)
            if nxt_unit in ("rb", "ribu", "k"):
                nxt_base = _parse_number(nxt.group(1))
                value += nxt_base * _MULTIPLIER[nxt_unit]
                i += 1

        amounts.append(value)
        i += 1

    return [a for a in amounts if a != 0]


def _detect_intent(text: str) -> str:
    if any(w in text for w in _PAYMENT_WORDS):
        return "payment"
    if any(w in text for w in _NEGATIVE_WORDS):
        return "expense"
    return "unknown"


# =========================
# PUBLIC FUNCTION
# =========================

def parse_amount_id(text: str) -> Optional[MoneyParseResult]:
    t = _clean(text)
    amounts = _extract_numeric_segments(t)

    if not amounts:
        return None

    is_negative = any(w in t for w in _NEGATIVE_WORDS)
    intent = _detect_intent(t)

    primary = max(amounts)
    change = None

    # change detection
    if any(w in t for w in _CHANGE_WORDS) and len(amounts) >= 2:
        change = max(amounts) - min(amounts)
        primary = change

    if is_negative:
        primary = -abs(primary)

    return MoneyParseResult(
        amounts=amounts,
        primary=primary,
        change=change,
        is_negative=is_negative,
        intent=intent,
    )


def parse_primary_amount_id(text: str) -> Optional[float]:
    res = parse_amount_id(text)
    if not res or res.primary is None:
        return None
    try:
        return float(abs(res.primary))
    except Exception:
        return None
