"""Chargement et validation de la configuration (YAML) et des paramètres d'exécution (variables d'environnement)."""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parent.parent
DOSSIER_CONFIG = RACINE / "config"

ECHIQUIERS = ("concurrentiel", "institutionnel", "societe_civile")
FIABILITES = ("fiable", "a_confirmer", "douteuse")
VRAISEMBLANCE = ("probable", "plausible", "peu probable")


def _lire(nom: str) -> dict:
    with open(DOSSIER_CONFIG / nom, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache
def domaine() -> dict:
    return _lire("domaine.yaml")


@lru_cache
def hypotheses() -> list[dict]:
    return _lire("hypotheses_initiales.yaml")["hypotheses"]


@lru_cache
def sources() -> list[dict]:
    return _lire("sources.yaml")["sources"]


# ───────────── Paramètres d'exécution ─────────────

@dataclass(frozen=True)
class Parametres:
    anthropic_api_key: str
    serper_api_key: str
    supabase_url: str
    supabase_key: str
    modele_tri: str
    modele_analyse: str
    max_appels_llm: int
    max_requetes_serper: int
    taille_lot_tri: int
    jours_fenetre: int
    pause_ddg: float


def parametres() -> Parametres:
    e = os.environ.get
    return Parametres(
        anthropic_api_key=e("ANTHROPIC_API_KEY", ""),
        serper_api_key=e("SERPER_API_KEY", ""),
        supabase_url=e("SUPABASE_URL", ""),
        supabase_key=e("SUPABASE_SERVICE_KEY", ""),
        modele_tri=e("MODELE_TRI", "claude-haiku-4-5-20251001"),
        modele_analyse=e("MODELE_ANALYSE", "claude-sonnet-5"),
        max_appels_llm=int(e("MAX_APPELS_LLM", "40")),
        max_requetes_serper=int(e("MAX_REQUETES_SERPER", "20")),
        taille_lot_tri=int(e("TAILLE_LOT_TRI", "10")),
        jours_fenetre=int(e("JOURS_FENETRE", "7")),
        pause_ddg=float(e("PAUSE_DDG", "2")),
    )


# ───────────── Pré-filtre par mots-clés ─────────────

def sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn")


@lru_cache
def _motif_prefiltre() -> re.Pattern:
    morceaux = []
    for mot in domaine()["mots_cles_prefiltre"]:
        m = re.escape(sans_accents(mot.lower()))
        # Mots courts (ets, imo, lng, omi…) : mot entier, sinon « assets » ou « économie » passeraient.
        morceaux.append(rf"\b{m}\b" if len(mot) <= 4 else rf"\b{m}")
    return re.compile("|".join(morceaux))


def passe_prefiltre(titre: str, extrait: str | None) -> bool:
    texte = sans_accents(f"{titre} {extrait or ''}".lower())
    return bool(_motif_prefiltre().search(texte))


# ───────────── Validation de cohérence ─────────────

def valider() -> list[str]:
    """Retourne la liste des incohérences de configuration (vide si tout va bien)."""
    erreurs: list[str] = []
    d = domaine()
    ids_questions = {q["id"] for q in d["questions"]}

    if tuple(d["vraisemblance"]) != VRAISEMBLANCE:
        erreurs.append("domaine.yaml : le vocabulaire de vraisemblance doit être exactement " + str(VRAISEMBLANCE))

    ids_h: set[str] = set()
    ids_i: set[str] = set()
    par_question: dict[str, list[dict]] = {q: [] for q in ids_questions}
    for h in hypotheses():
        if h["id"] in ids_h:
            erreurs.append(f"Hypothèse en double : {h['id']}")
        ids_h.add(h["id"])
        if h["question"] not in ids_questions:
            erreurs.append(f"{h['id']} : question inconnue {h['question']}")
        else:
            par_question[h["question"]].append(h)
        if h["type"] not in ("hypothese", "contre"):
            erreurs.append(f"{h['id']} : type invalide {h['type']}")
        if h.get("confiance") not in VRAISEMBLANCE:
            erreurs.append(f"{h['id']} : confiance hors vocabulaire ({h.get('confiance')})")
        sens = {i["sens"] for i in h["indicateurs"]}
        if sens != {"confirme", "infirme"}:
            erreurs.append(f"{h['id']} : il faut au moins un indicateur qui confirme ET un qui infirme")
        for i in h["indicateurs"]:
            if i["id"] in ids_i:
                erreurs.append(f"Indicateur en double : {i['id']}")
            ids_i.add(i["id"])
            if not i["id"].startswith(h["id"] + "-"):
                erreurs.append(f"{i['id']} : l'identifiant doit commencer par {h['id']}-")
            if not i.get("requete"):
                erreurs.append(f"{i['id']} : requête de recherche manquante")

    for q, hs in par_question.items():
        nb_h = sum(1 for h in hs if h["type"] == "hypothese")
        nb_c = sum(1 for h in hs if h["type"] == "contre")
        if nb_h < 2 or nb_c < 1:
            erreurs.append(f"{q} : il faut au moins 2 hypothèses et 1 contre-hypothèse (trouvé {nb_h} + {nb_c})")

    ids_s: set[str] = set()
    for s in sources():
        if s["id"] in ids_s:
            erreurs.append(f"Source en double : {s['id']}")
        ids_s.add(s["id"])
        if s["echiquier"] not in ECHIQUIERS:
            erreurs.append(f"{s['id']} : échiquier invalide {s['echiquier']}")
        if s["fiabilite"] not in FIABILITES:
            erreurs.append(f"{s['id']} : fiabilité invalide {s['fiabilite']}")
        if s["type"] == "rss" and not s.get("url"):
            erreurs.append(f"{s['id']} : flux RSS sans url")
    if "serper_indicateurs" not in ids_s:
        erreurs.append("sources.yaml : la source 'serper_indicateurs' est requise")

    couverts = {s["echiquier"] for s in sources()}
    for e in ECHIQUIERS:
        if e not in couverts:
            erreurs.append(f"Aucune source pour l'échiquier {e}")
    return erreurs
