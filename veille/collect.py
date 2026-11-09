"""Collecte : flux RSS et recherches Serper (sources fixes + requêtes des indicateurs, en rotation)."""

from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta, timezone

import requests

from .dedup import domaine_de

UA = {"User-Agent": "veille-ftt/1.0 (+veille strategique personnelle)"}
TIMEOUT = 20
SERPER_URL = "https://google.serper.dev/news"
SEUIL_DESACTIVATION = 5  # échecs consécutifs avant désactivation automatique d'une source


class ErreurSource(RuntimeError):
    pass


class ErreurSerper(ErreurSource):
    def __init__(self, statut: int, corps: str):
        self.statut, self.corps = statut, corps
        super().__init__(f"Serper HTTP {statut} : {corps or '(réponse vide)'}")


def nettoyer(texte: str | None, longueur: int = 600) -> str:
    if not texte:
        return ""
    t = re.sub(r"<[^>]+>", " ", texte)
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:longueur]


def _date_entree(e) -> datetime | None:
    for cle in ("published_parsed", "updated_parsed"):
        v = e.get(cle)
        if v:
            return datetime(*v[:6], tzinfo=timezone.utc)
    return None


def collecter_rss(source: dict, depuis: datetime) -> list[dict]:
    import feedparser

    try:
        rep = requests.get(source["url"], headers=UA, timeout=TIMEOUT)
        rep.raise_for_status()
    except requests.RequestException as ex:
        raise ErreurSource(f"HTTP : {ex}") from ex

    flux = feedparser.parse(rep.content)
    if flux.bozo and not flux.entries:
        raise ErreurSource(f"Flux illisible : {flux.bozo_exception}")
    if not flux.entries:
        raise ErreurSource("Flux vide")

    items = []
    for e in flux.entries:
        lien = e.get("link")
        titre = nettoyer(e.get("title"), 300)
        if not lien or not titre:
            continue
        publie = _date_entree(e)
        if publie and publie < depuis:
            continue
        items.append(
            {
                "url": lien,
                "titre": titre,
                "extrait": nettoyer(e.get("summary") or e.get("description")),
                "source_id": source["id"],
                "origine": "rss",
                "domaine": domaine_de(lien),
                "langue": source.get("langue"),
                "publie_le": publie.isoformat() if publie else None,
            }
        )
    return items


def rechercher_serper(api_key: str, requete: str, langue: str, source_id: str, origine: str) -> list[dict]:
    corps = {
        "q": requete,
        "num": 10,
        "tbs": "qdr:w",  # 7 derniers jours ; les requêtes tournent sur 3 jours, le recouvrement est dédoublonné
        "gl": "fr" if langue == "fr" else "us",
        "hl": langue,
    }
    try:
        rep = requests.post(SERPER_URL, json=corps, headers={"X-API-KEY": api_key}, timeout=TIMEOUT)
    except requests.RequestException as ex:
        raise ErreurSource(f"Serper : {ex}") from ex
    if rep.status_code != 200:
        # Le corps de la réponse explique la cause (crédits épuisés, clé invalide, paramètre refusé…).
        raise ErreurSerper(rep.status_code, rep.text.strip()[:200])

    items = []
    for n in rep.json().get("news", []):
        lien, titre = n.get("link"), nettoyer(n.get("title"), 300)
        if not lien or not titre:
            continue
        items.append(
            {
                "url": lien,
                "titre": titre,
                "extrait": nettoyer(n.get("snippet")),
                "source_id": source_id,
                "origine": origine,
                "domaine": domaine_de(lien),
                "langue": langue,
                "publie_le": None,  # Serper donne des dates relatives (« 2 days ago ») : non fiables
            }
        )
    return items


MOTS_MAX_DDG = 5


def simplifier_pour_ddg(requete: str) -> tuple[str, str]:
    """Adapte une requête écrite pour Serper/Google au moteur DuckDuckGo, qui gère mal OR,
    les parenthèses et les requêtes longues, et ignore site: dans son onglet Actualités.

    Retourne (mode, requete) : mode « text » (recherche web, respecte site:) ou « news ».
    """
    sites = re.findall(r"site:([^\s()]+)", requete)
    sans_site = re.sub(r"site:[^\s()]+", " ", requete)
    groupe = re.search(r"\(([^)]*)\)", sans_site)
    if groupe:
        dedans = [a.strip() for a in re.split(r"\s+OR\s+", groupe.group(1)) if a.strip()]
        dehors = (sans_site[: groupe.start()] + " " + sans_site[groupe.end() :]).strip()
        coeur = " ".join(filter(None, [dedans[0] if dedans else "", re.split(r"\s+OR\s+", dehors)[0] if dehors else ""]))
    else:
        coeur = re.split(r"\s+OR\s+", sans_site.strip())[0]
    mots = re.sub(r"\s+", " ", coeur.replace('"', "")).strip().split(" ")
    mots = [m for m in mots if m and m != "OR"][:MOTS_MAX_DDG]
    if sites:
        return "text", " ".join([f"site:{sites[0]}", *mots[:3]])
    return "news", " ".join(mots)


def rechercher_ddg(requete: str, langue: str, source_id: str, origine: str) -> list[dict]:
    """Secours gratuit (bibliothèque ddgs). Moins complet que Serper : la requête est simplifiée,
    et le service peut être limité en débit depuis les serveurs GitHub."""
    mode, q = simplifier_pour_ddg(requete)
    try:
        from ddgs import DDGS

        moteur = DDGS()
        recherche = moteur.text if mode == "text" else moteur.news
        resultats = recherche(q, region="fr-fr" if langue == "fr" else "us-en", timelimit="w", max_results=10)
    except Exception as ex:  # ddgs lève ses propres exceptions (limite de débit, délai, aucun résultat…)
        if "no results" in str(ex).lower():
            return []
        raise ErreurSource(f"DuckDuckGo : {type(ex).__name__} : {str(ex)[:150]}") from ex

    items = []
    for n in resultats or []:
        lien, titre = n.get("url") or n.get("href"), nettoyer(n.get("title"), 300)
        if not lien or not titre:
            continue
        publie = None
        try:
            publie = datetime.fromisoformat(str(n.get("date"))).astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError):
            pass
        items.append(
            {
                "url": lien,
                "titre": titre,
                "extrait": nettoyer(n.get("body")),
                "source_id": source_id,
                "origine": origine,
                "domaine": domaine_de(lien),
                "langue": langue,
                "publie_le": publie,
            }
        )
    return items


def requetes_du_jour(
    sources_serper: list[dict], indicateurs: list[dict], jour: date, maximum: int, periode: int = 3
) -> list[dict]:
    """Rotation : chaque requête passe une fois tous les `periode` jours.
    Les sources fixes passent avant les indicateurs ; le tout est plafonné à `maximum` (D29)."""
    rang = jour.toordinal() % periode
    plan = []
    fixes = sorted((s for s in sources_serper if s.get("requete")), key=lambda s: s["id"])
    for n, s in enumerate(fixes):
        if n % periode == rang:
            plan.append({"requete": s["requete"], "langue": s.get("langue", "en"), "source_id": s["id"], "origine": "serper"})
    for n, i in enumerate(sorted(indicateurs, key=lambda i: i["id"])):
        if i.get("requete") and n % periode == rang:
            plan.append(
                {
                    "requete": i["requete"],
                    "langue": "en",
                    "source_id": "serper_indicateurs",
                    "origine": f"indicateur:{i['id']}",
                }
            )
    return plan[:maximum]


def fenetre(jours: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=jours)
