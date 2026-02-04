from datetime import datetime

class RuleEngine:
    def __init__(self):
        # Default rules as per user request
        self.rules = [
            {"condition": "category == 'Makanan' and amount > 50000", "tag": "boros"},
            {"condition": "hour >= 22", "tag": "impulsive"}
        ]

    def evaluate(self, transaction_data):
        """
        transaction_data: dict with amount, category, hour, etc.
        Returns list of tags.
        """
        tags = []
        amount = transaction_data.get('amount', 0)
        category = transaction_data.get('category', '')
        hour = transaction_data.get('hour', datetime.now().hour)
        
        for rule in self.rules:
            try:
                # Simple eval for demonstration, in production use a safer parser
                if eval(rule['condition'], {}, {"category": category, "amount": amount, "hour": hour}):
                    tags.append(rule['tag'])
            except:
                continue
        return tags
