"""Normalisation d'URL, regroupement en événements et détection des reprises (D18).

Fonctions pures, testées hors ligne.
- doublon  : même média, même article (URL différente ou titre quasi identique) → on n'insère pas.
- reprise  : autre média, contenu quasi identique (même dépêche) → inséré, mais ne compte pas comme
             source indépendante pour la corroboration.
- événement: autre média, même fait, rédaction différente → source indépendante.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .config import sans_accents

PARAMS_TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|cmpid|ito|xtor|at_)", re.I)

MOTS_VIDES = set(
    """
    the a an and or of to in on for with at by from as is are was were be been its it this that these those
    after over into new says said will could would has have had not but more than up out about
    le la les un une des du de d l et ou en au aux pour par sur dans avec sans est sont a ont qui que
    se ce cette ces son sa ses leur leurs plus apres selon
    """.split()
)

SEUIL_EVENEMENT = 0.45   # Jaccard sur les titres : même fait
SEUIL_DOUBLON = 0.85     # titres quasi identiques
SEUIL_REPRISE = 0.70     # Jaccard sur titre + extrait : même dépêche reprise


def normaliser_url(url: str) -> str:
    p = urlsplit(url.strip())
    hote = p.netloc.lower()
    if hote.startswith("www."):
        hote = hote[4:]
    if hote.startswith("m."):
        hote = hote[2:]
    params = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=False) if not PARAMS_TRACKING.match(k)]
    chemin = p.path.rstrip("/") or "/"
    return urlunsplit(("https", hote, chemin, urlencode(sorted(params)), ""))


def domaine_de(url: str) -> str:
    hote = urlsplit(normaliser_url(url)).netloc
    morceaux = hote.split(".")
    # Domaine enregistrable approximatif : gère les cas courants (co.uk, gouv.fr, europa.eu…).
    if len(morceaux) >= 3 and morceaux[-2] in {"co", "com", "gouv", "europa", "gov", "org", "ac"}:
        return ".".join(morceaux[-3:])
    return ".".join(morceaux[-2:])


def jetons(texte: str | None) -> set[str]:
    if not texte:
        return set()
    t = sans_accents(texte.lower())
    return {m for m in re.findall(r"[a-z0-9][a-z0-9\-]+", t) if len(m) >= 3 and m not in MOTS_VIDES}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class Rapprochement:
    doublon: bool = False
    evenement_id: int | None = None
    reprise_de: int | None = None


def rapprocher(item: dict, pool: list[dict]) -> Rapprochement:
    """Compare un article candidat aux signaux récents.

    `item` : {titre, extrait, domaine}
    `pool` : [{id, evenement_id, titre, extrait, domaine}] — signaux récents (base + déjà insérés dans ce run).
    """
    jt = jetons(item["titre"])
    jc = jt | jetons(item.get("extrait"))
    meilleur, meilleur_score = None, 0.0
    for s in pool:
        st = jetons(s["titre"])
        score_titre = jaccard(jt, st)
        if s["domaine"] == item["domaine"] and score_titre >= SEUIL_DOUBLON:
            return Rapprochement(doublon=True)
        if score_titre > meilleur_score:
            meilleur, meilleur_score = s, score_titre

    if meilleur is None or meilleur_score < SEUIL_EVENEMENT:
        return Rapprochement()

    r = Rapprochement(evenement_id=meilleur["evenement_id"])
    if meilleur["domaine"] != item["domaine"]:
        score_contenu = jaccard(jc, jetons(meilleur["titre"]) | jetons(meilleur.get("extrait")))
        if score_contenu >= SEUIL_REPRISE:
            # On remonte à l'original pour ne jamais chaîner les reprises.
            r.reprise_de = meilleur.get("reprise_de") or meilleur["id"]
    return r
