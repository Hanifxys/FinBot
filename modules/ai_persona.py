import json
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class Persona:
    """
    Defines the character and behavior of the AI.
    """
    name: str = "FinBot Pro"
    tone: str = "Friendly but Professional"
    expertise: str = "Financial Planner"
    traits: List[str] = field(default_factory=list)
    language: str = "id"  # Default language

    def system_prompt(self) -> str:
        """Generate system prompt part based on persona."""
        traits_str = ", ".join(self.traits)
        return (
            f"Your name is {self.name}. You are a {self.expertise}.\n"
            f"Tone: {self.tone}.\n"
            f"Traits: {traits_str}.\n"
            f"Language Preference: {self.language} (but adapt to user).\n"
            "Always act according to this persona."
        )

class PersonaManager:
    """
    Manages user-specific AI personas.
    """
    def __init__(self):
        self.default_persona = Persona(
            name="FinBot Pro",
            tone="Conversational, witty, yet insightful",
            expertise="Financial Advisor & Wealth Manager",
            traits=["Empathetic", "Data-driven", "Proactive", "Gen-Z Friendly"],
            language="id"
        )
        self.personas = {}  # In-memory cache, ideally backed by DB/Redis
        self.financial_personas = {}

    def get_persona(self, user_id: int, stress_level: str = "low") -> Persona:
        """Retrieve persona for a user, adapted to their financial stress level."""
        base = self.personas.get(user_id, self.default_persona)
        
        if stress_level == "high":
            # Adapt tone to be more serious/strict if financial status is critical
            return Persona(
                name=f"{base.name} (Alert Mode)",
                tone="Strict, Warning-focused, Direct",
                expertise=base.expertise,
                traits=base.traits + ["Urgent", "Direct", "Cautious"],
                language=base.language
            )
        return base

    def set_persona(self, user_id: int, mode: str):
        """
        Customize persona based on selected coaching mode.
        Modes: 'coach' (Strict), 'buddy' (Friendly), 'analyst' (Formal)
        """
        base = self.default_persona
        
        if mode == "coach":
            new_p = Persona(
                name="Coach Finansial",
                tone="Strict, Direct, No-nonsense",
                expertise="Hardcore Budgeting Coach",
                traits=["Disiplin", "Tegas", "Goal-oriented", "Galak dikit"],
                language="id"
            )
        elif mode == "buddy":
            new_p = Persona(
                name="Bestie Cuan",
                tone="Santai, Gaul, Supportive",
                expertise="Financial Best Friend",
                traits=["Asik", "Pengertian", "Supportive", "Pake bahasa gaul"],
                language="id"
            )
        elif mode == "analyst":
            new_p = Persona(
                name="Analis Data",
                tone="Formal, Data-driven, Objective",
                expertise="Senior Financial Analyst",
                traits=["Objektif", "Detail", "Matematis", "Professional"],
                language="id"
            )
        else:
            new_p = base

        self.personas[user_id] = new_p
        return new_p

    def set_financial_persona(self, user_id: int, persona_key: str) -> dict:
        """
        Advanced financial persona profile used for risk and strategy shaping.
        """
        key = (persona_key or "").strip().lower()
        profiles = {
            "conservative": {
                "persona": "Conservative Investor",
                "risk_tolerance": 0.25,
                "tone": "cautious",
                "strategy": "capital preservation first",
                "guardrails": ["Emergency fund 6-12 bulan", "Hindari leverage tinggi"],
            },
            "growth_aggressive": {
                "persona": "Growth Aggressive",
                "risk_tolerance": 0.8,
                "tone": "assertive",
                "strategy": "high risk high reward",
                "guardrails": ["Position sizing ketat", "Stop-loss disiplin"],
            },
            "risk_avoider": {
                "persona": "Risk Avoider",
                "risk_tolerance": 0.15,
                "tone": "protective",
                "strategy": "stability and downside protection",
                "guardrails": ["Likuiditas tinggi", "Diversifikasi defensif"],
            },
            "over_spender": {
                "persona": "Over-spender Controller",
                "risk_tolerance": 0.2,
                "tone": "corrective",
                "strategy": "spending control and budgeting discipline",
                "guardrails": ["Cap discretionary spend", "Weekly spend review wajib"],
            },
        }
        selected = profiles.get(key, profiles["conservative"])
        self.financial_personas[user_id] = selected
        return selected

    def get_financial_profile(self, user_id: int, db_handler=None, user_db_id: Optional[int] = None) -> dict:
        """
        Retrieve advanced persona profile. If not explicitly set, infer lightweight
        profile from user spending behavior.
        """
        if user_id in self.financial_personas:
            return self.financial_personas[user_id]

        # Lightweight inference fallback
        inferred = self.set_financial_persona(user_id, "conservative")
        if db_handler and user_db_id:
            try:
                txs = db_handler.get_sliding_window_transactions(user_db_id, days=90)
                expenses = [t for t in txs if getattr(t, "type", "") == "expense"]
                income = [t for t in txs if getattr(t, "type", "") == "income"]
                total_exp = sum(float(getattr(t, "amount", 0) or 0) for t in expenses)
                total_inc = sum(float(getattr(t, "amount", 0) or 0) for t in income)
                spend_ratio = (total_exp / total_inc) if total_inc > 0 else 1.2
                if spend_ratio > 0.95:
                    inferred = self.set_financial_persona(user_id, "over_spender")
                elif spend_ratio < 0.65:
                    inferred = self.set_financial_persona(user_id, "growth_aggressive")
                elif spend_ratio < 0.8:
                    inferred = self.set_financial_persona(user_id, "conservative")
                else:
                    inferred = self.set_financial_persona(user_id, "risk_avoider")
            except Exception:
                pass
        return inferred
