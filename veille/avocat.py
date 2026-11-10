"""Avocat du diable (D23) : pour chaque hypothèse analysée, « qu'est-ce qui la rendrait fausse ? »,
puis des requêtes courtes pour aller chercher activement ces contre-preuves (thèse p. 285-290).
"""

from __future__ import annotations

import json

SYSTEME = """Tu joues l'avocat du diable pour un analyste de veille stratégique ({domaine}).
Ton seul objectif : attaquer chaque hypothèse pour éviter le biais de confirmation.

Pour CHAQUE hypothèse fournie :
1. "falsificateur" : en une ou deux phrases, le fait observable qui la rendrait fausse ou nettement moins
   probable. Il doit être concret (un acteur, une décision, un chiffre, une date), pas une généralité.
2. "angle_mort" : ce que les preuves déjà réunies cette semaine pourraient masquer
   (source unique, même type d'acteur, effet d'annonce non suivi d'effet…). Une phrase.
3. "requetes" : 1 ou 2 requêtes de recherche d'actualité pour trouver ce falsificateur.
   Contraintes : 3 à 6 mots, en anglais sauf sujet strictement français, sans opérateur (pas de OR,
   pas de guillemets, pas de site:), sans date.

Ne juge pas l'hypothèse. Ne conclus pas. N'invente aucun fait : le falsificateur est ce qu'il FAUDRAIT observer.

Réponds UNIQUEMENT avec un tableau JSON :
[{{"hypothese": "H2-A", "falsificateur": "...", "angle_mort": "...", "requetes": ["...", "..."]}}]
"""


def construire_message(hypotheses: list[dict], resume_preuves: dict[str, dict]) -> str:
    blocs = []
    for h in hypotheses:
        p = resume_preuves.get(h["id"], {})
        blocs.append(
            {
                "id": h["id"],
                "type": h["type"],
                "enonce": h["enonce"],
                "confiance_actuelle": h.get("confiance"),
                "preuves_de_la_semaine": {
                    "soutient": p.get("soutient", [])[:5],
                    "contredit": p.get("contredit", [])[:5],
                },
            }
        )
    return "Hypothèses à attaquer :\n" + json.dumps(blocs, ensure_ascii=False, indent=1)


def valider(brut, ids_hypotheses: set[str], max_requetes: int) -> dict[str, dict]:
    if not isinstance(brut, list):
        raise ValueError("La réponse de l'avocat du diable n'est pas un tableau JSON")
    sortie: dict[str, dict] = {}
    for r in brut:
        if not isinstance(r, dict) or r.get("hypothese") not in ids_hypotheses or r["hypothese"] in sortie:
            continue
        requetes = []
        for q in (r.get("requetes") or [])[:2]:
            q = " ".join(str(q).replace('"', " ").split())
            mots = [m for m in q.split(" ") if m.upper() != "OR" and not m.lower().startswith("site:")]
            if 2 <= len(mots):
                requetes.append(" ".join(mots[:6]))
        sortie[r["hypothese"]] = {
            "falsificateur": str(r.get("falsificateur") or "").strip()[:500],
            "angle_mort": str(r.get("angle_mort") or "").strip()[:300],
            "requetes": requetes,
        }
    # Plafond global de requêtes, réparti en tourniquet pour que chaque hypothèse soit attaquée.
    total, rang = 0, 0
    gardees = {h: [] for h in sortie}
    while total < max_requetes and any(len(v["requetes"]) > rang for v in sortie.values()):
        for h, v in sortie.items():
            if rang < len(v["requetes"]) and total < max_requetes:
                gardees[h].append(v["requetes"][rang])
                total += 1
        rang += 1
    for h in sortie:
        sortie[h]["requetes"] = gardees[h]
    return sortie
