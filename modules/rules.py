from datetime import datetime
from typing import Dict, List, Any, Callable
import operator


class RuleEngine:
    """
    Production-Safe Rule Engine
    - No eval()
    - Safe operator mapping
    - Priority-based evaluation
    - Explainable results
    """

    OPERATORS = {
        "==": operator.eq,
        "!=": operator.ne,
        ">": operator.gt,
        "<": operator.lt,
        ">=": operator.ge,
        "<=": operator.le,
        "in": lambda a, b: a in b,
    }

    def __init__(self):
        self.rules = [
            {
                "field": "category",
                "operator": "==",
                "value": "Makanan",
                "extra_condition": {
                    "field": "amount",
                    "operator": ">",
                    "value": 50000
                },
                "tag": "boros",
                "priority": 1
            },
            {
                "field": "hour",
                "operator": ">=",
                "value": 22,
                "tag": "impulsive",
                "priority": 2
            }
        ]

    # ----------------------------------
    # MAIN EVALUATION
    # ----------------------------------

    def evaluate(self, transaction_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Returns list of matched rules with explanation.
        """

        results = []

        context = self._build_context(transaction_data)

        for rule in sorted(self.rules, key=lambda r: r.get("priority", 999)):
            if self._match_rule(rule, context):
                results.append({
                    "tag": rule["tag"],
                    "priority": rule.get("priority", 999),
                    "explanation": self._build_explanation(rule, context)
                })

        return results

    # ----------------------------------
    # RULE MATCHING
    # ----------------------------------

    def _match_rule(self, rule: Dict, context: Dict) -> bool:
        field = rule["field"]
        op = rule["operator"]
        value = rule["value"]

        if field not in context:
            return False

        if op not in self.OPERATORS:
            return False

        primary_check = self.OPERATORS[op](context[field], value)

        if not primary_check:
            return False

        # Optional secondary condition
        extra = rule.get("extra_condition")
        if extra:
            f = extra["field"]
            o = extra["operator"]
            v = extra["value"]

            if f not in context or o not in self.OPERATORS:
                return False

            return self.OPERATORS[o](context[f], v)

        return True

    # ----------------------------------
    # CONTEXT BUILDER
    # ----------------------------------

    def _build_context(self, transaction_data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "amount": transaction_data.get("amount", 0),
            "category": transaction_data.get("category", ""),
            "hour": transaction_data.get("hour", datetime.now().hour),
            "weekday": transaction_data.get("weekday", datetime.now().weekday()),
            "merchant": transaction_data.get("merchant", "")
        }

    # ----------------------------------
    # EXPLAINABILITY
    # ----------------------------------

    def _build_explanation(self, rule: Dict, context: Dict) -> str:
        explanation = f"Matched rule: {rule['field']} {rule['operator']} {rule['value']}"

        if rule.get("extra_condition"):
            ec = rule["extra_condition"]
            explanation += f" AND {ec['field']} {ec['operator']} {ec['value']}"

        return explanation