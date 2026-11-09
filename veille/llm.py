"""Appels à l'API Claude, avec plafond d'appels par exécution (D29)."""

from __future__ import annotations

import json
import re


class BudgetEpuise(RuntimeError):
    pass


class Budget:
    def __init__(self, max_appels: int):
        self.max_appels = max_appels
        self.appels = 0

    def consommer(self) -> None:
        if self.appels >= self.max_appels:
            raise BudgetEpuise(f"Plafond de {self.max_appels} appels LLM atteint pour cette exécution")
        self.appels += 1

    @property
    def restant(self) -> int:
        return self.max_appels - self.appels


class ClientLLM:
    def __init__(self, api_key: str, budget: Budget):
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)
        self.budget = budget

    def appeler(self, modele: str, systeme: str, message: str, max_tokens: int = 4096) -> str:
        self.budget.consommer()
        reponse = self._client.messages.create(
            model=modele,
            system=systeme,
            messages=[{"role": "user", "content": message}],
            max_tokens=max_tokens,
        )
        return "".join(b.text for b in reponse.content if getattr(b, "type", "") == "text").strip()


def extraire_json(texte: str):
    """Extrait le premier bloc JSON (objet ou tableau) d'une réponse de modèle."""
    bloc = re.search(r"```(?:json)?\s*(.*?)```", texte, re.S)
    if bloc:
        texte = bloc.group(1)
    debut = min((i for i in (texte.find("["), texte.find("{")) if i != -1), default=-1)
    if debut == -1:
        raise ValueError("Aucun JSON dans la réponse")
    fin = max(texte.rfind("]"), texte.rfind("}"))
    return json.loads(texte[debut : fin + 1])
