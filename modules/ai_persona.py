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

    def get_persona(self, user_id: int) -> Persona:
        """Retrieve persona for a user (or default)."""
        return self.personas.get(user_id, self.default_persona)

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
