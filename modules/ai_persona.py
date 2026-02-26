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

    def set_persona(self, user_id: int, **kwargs):
        """Customize persona for a user."""
        current = self.get_persona(user_id)
        # Create new instance with updates
        new_persona = Persona(
            name=kwargs.get("name", current.name),
            tone=kwargs.get("tone", current.tone),
            expertise=kwargs.get("expertise", current.expertise),
            traits=kwargs.get("traits", current.traits),
            language=kwargs.get("language", current.language)
        )
        self.personas[user_id] = new_persona
