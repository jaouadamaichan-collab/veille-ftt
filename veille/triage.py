"""Tri quotidien des signaux par Haiku : pertinence, échiquier, questions, rattachement aux hypothèses.

Rôle de l'agent ici : « puzzle » (thèse p. 302-304). Il range et relie ; il ne conclut pas.
Les rattachements produits sont des *propositions* (statut 'propose') que l'humain statue dans le cockpit.
"""

from __future__ import annotations

import json

from .config import ECHIQUIERS

SYSTEME = """Tu es l'assistant de tri d'un analyste de veille stratégique.
Domaine : {domaine}.
Finalité de l'analyste : {finalite}

Ton rôle est limité au TRI : tu ranges et relies les articles. Tu ne tires aucune conclusion
et tu ne juges pas si une hypothèse est vraie. L'analyste humain tranche.

## Questions clés
{questions}

## Hypothèses en cours (avec leurs indicateurs observables)
{hypotheses}

## Échiquiers (grille d'Harbulot)
- concurrentiel : armateurs, chantiers, motoristes, énergéticiens, ports en tant qu'opérateurs, classification, prestataires
- institutionnel : UE, OMI, États, régulateurs
- societe_civile : ONG, coalitions, chercheurs, syndicats, opinion, chargeurs
Choisis l'échiquier de l'ACTEUR PRINCIPAL dont l'article rapporte une action ou une position.

## Règles
1. "pertinent" = l'article apporte un FAIT nouveau utile à au moins une question clé. Un article
   générique, publicitaire ou purement d'opinion sans fait nouveau n'est pas pertinent.
2. "score" de 0 à 10 = utilité pour l'analyste. 8+ seulement si le fait peut faire bouger une hypothèse.
3. Un "lien" vers une hypothèse n'est créé que si l'article contient un fait précis qui la SOUTIENT
   ou la CONTREDIT. Cite ce fait dans "justification" (une phrase, avec chiffres ou acteurs si présents).
   Si le fait correspond à un indicateur listé, renseigne son identifiant, sinon null.
   Cherche autant les faits qui CONTREDISENT que ceux qui soutiennent.
4. N'invente rien : tout ce que tu écris doit figurer dans le titre ou l'extrait fourni.
5. "resume" : une phrase en français, factuelle.

## Format de sortie
Réponds UNIQUEMENT avec un tableau JSON, un objet par article, dans cet ordre :
[{{"i": 0, "pertinent": true, "score": 7, "echiquier": "institutionnel", "questions": ["Q2"],
   "liens": [{{"hypothese": "H2-B", "indicateur": "H2-B-1", "relation": "soutient", "justification": "..."}}],
   "resume": "..."}}]
"""


def construire_systeme(domaine: dict, hypotheses: list[dict], indicateurs_par_h: dict[str, list[dict]]) -> str:
    questions = "\n".join(f"- {q['id']} : {q['intitule']}" for q in domaine["questions"])
    blocs = []
    for h in hypotheses:
        etiquette = "contre-hypothèse" if h["type"] == "contre" else "hypothèse"
        question = h.get("question_id") or h.get("question")
        statut = f", statut {h['statut']}" if h.get("statut") else ""
        lignes = [f"- {h['id']} ({question}, {etiquette}{statut}) : {' '.join(h['enonce'].split())}"]
        for i in indicateurs_par_h.get(h["id"], []):
            lignes.append(f"    · {i['id']} [{i['sens']}] {i['description']}")
        blocs.append("\n".join(lignes))
    return SYSTEME.format(
        domaine=domaine["domaine"],
        finalite=" ".join(domaine["finalite"].split()),
        questions=questions,
        hypotheses="\n".join(blocs),
    )


def construire_message(lot: list[dict]) -> str:
    articles = [
        {
            "i": n,
            "titre": s["titre"],
            "extrait": (s.get("extrait") or "")[:600],
            "media": s.get("domaine"),
            "date": str(s.get("publie_le") or s.get("collecte_le") or "")[:10],
        }
        for n, s in enumerate(lot)
    ]
    return "Articles à trier :\n" + json.dumps(articles, ensure_ascii=False, indent=1)


def valider_resultats(
    brut,
    lot: list[dict],
    ids_questions: set[str],
    indicateurs_par_h: dict[str, list[dict]],
) -> list[dict]:
    """Garde-fou : ne conserve que des valeurs connues. Retourne un résultat par article du lot
    (les articles absents de la réponse sont marqués non triés pour être repris au prochain passage)."""
    if not isinstance(brut, list):
        raise ValueError("La réponse de tri n'est pas un tableau JSON")

    par_index: dict[int, dict] = {}
    for r in brut:
        if isinstance(r, dict) and isinstance(r.get("i"), int) and 0 <= r["i"] < len(lot):
            par_index[r["i"]] = r

    sortie = []
    for n, signal in enumerate(lot):
        r = par_index.get(n)
        if r is None:
            sortie.append({"signal_id": signal["id"], "trie": False})
            continue

        pertinent = bool(r.get("pertinent"))
        try:
            score = max(0, min(10, int(r.get("score", 0))))
        except (TypeError, ValueError):
            score = 0
        echiquier = r.get("echiquier")
        if echiquier not in ECHIQUIERS:
            echiquier = signal.get("echiquier_source")
        questions = [q for q in (r.get("questions") or []) if q in ids_questions]

        liens = []
        vus = set()
        for l in (r.get("liens") or []) if pertinent else []:
            if not isinstance(l, dict):
                continue
            h = l.get("hypothese")
            if h not in indicateurs_par_h or h in vus:
                continue
            if l.get("relation") not in ("soutient", "contredit"):
                continue
            ind = l.get("indicateur")
            if ind not in {i["id"] for i in indicateurs_par_h[h]}:
                ind = None
            justification = str(l.get("justification") or "").strip()
            if not justification:
                continue
            vus.add(h)
            liens.append(
                {
                    "signal_id": signal["id"],
                    "hypothese_id": h,
                    "indicateur_id": ind,
                    "relation": l["relation"],
                    "justification": justification[:500],
                }
            )

        sortie.append(
            {
                "signal_id": signal["id"],
                "trie": True,
                "pertinent": pertinent,
                "score": score if pertinent else min(score, 3),
                "echiquier": echiquier,
                "questions": questions,
                "resume": str(r.get("resume") or "")[:400],
                "hors_radar": pertinent and not liens,
                "liens": liens,
                "triage_brut": r,
            }
        )
    return sortie
