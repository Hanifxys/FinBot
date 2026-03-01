from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HandlerDeps:
    db: Any
    nlp: Any
    premium_ai: Any
    budget_mgr: Any
    analyzer: Any
    ux_analytics: Any
