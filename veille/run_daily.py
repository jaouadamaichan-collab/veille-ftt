"""Exécution quotidienne : collecte → dédoublonnage/événements → pré-filtre → tri Haiku → rattachements proposés.

Usage : python -m veille.run_daily
Aucune écriture dans le dépôt Git : tout va dans Supabase.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import date, datetime, timezone

from . import config
from .collect import ErreurSerper, ErreurSource, collecter_rss, fenetre, rechercher_ddg, rechercher_serper, requetes_du_jour
from .db import Base
from .dedup import normaliser_url, rapprocher
from .llm import Budget, BudgetEpuise, ClientLLM, extraire_json
from .triage import construire_message, construire_systeme, valider_resultats


def log(message: str) -> None:
    """Journal d'avancement visible en direct dans GitHub Actions."""
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {message}", flush=True)


def collecter(db: Base, p: config.Parametres, stats: dict, erreurs: list[str], indicateurs: list[dict]) -> list[dict]:
    sources = db.sources_actives()
    depuis = fenetre(p.jours_fenetre)
    items: list[dict] = []

    for s in (s for s in sources if s["type"] == "rss"):
        try:
            items += collecter_rss(s, depuis)
            db.sante_source(s, True)
        except ErreurSource as ex:
            db.sante_source(s, False, str(ex))
            erreurs.append(f"RSS {s['id']} : {ex}")

    log(f"RSS : {len(items)} article(s) récents")

    plan = requetes_du_jour([s for s in sources if s["type"] == "serper"], indicateurs, date.today(), p.max_requetes_serper)
    items += rechercher(plan, p, stats, erreurs)
    stats["nb_collectes"] = len(items)
    return items


REFUS_SERPER = (400, 401, 402, 403, 429)  # crédits épuisés, clé invalide, quota : inutile d'insister


def rechercher(plan: list[dict], p: config.Parametres, stats: dict, erreurs: list[str]) -> list[dict]:
    """Serper en principal, DuckDuckGo en secours (D16 + option 3 du 09/11/2026).

    - Une requête Serper qui échoue est retentée sur DuckDuckGo.
    - Un refus de compte Serper (crédits, clé, quota) fait basculer tout le reste du passage sur DuckDuckGo.
    - DuckDuckGo est interrompu après 3 échecs consécutifs (limitation de débit probable).
    """
    items: list[dict] = []
    serper_actif = bool(p.serper_api_key)
    if not serper_actif:
        erreurs.append("SERPER_API_KEY absente : recherches sur DuckDuckGo uniquement")
    nb_ddg, echecs_ddg, ddg_actif = 0, 0, True

    for n, r in enumerate(plan):
        if serper_actif:
            try:
                items += rechercher_serper(p.serper_api_key, r["requete"], r["langue"], r["source_id"], r["origine"])
                stats["nb_requetes_serper"] += 1
                continue
            except ErreurSerper as ex:
                if ex.statut in REFUS_SERPER:
                    serper_actif = False
                    erreurs.append(f"Serper refuse le service ({ex}) : bascule sur DuckDuckGo pour la suite du passage")
                    log(f"Serper refuse (HTTP {ex.statut}) → bascule DuckDuckGo")
                else:
                    erreurs.append(f"Serper « {r['requete'][:40]} » : {ex} → secours DuckDuckGo")
            except ErreurSource as ex:
                erreurs.append(f"Serper « {r['requete'][:40]} » : {ex} → secours DuckDuckGo")

        if not ddg_actif:
            continue
        if nb_ddg or echecs_ddg:
            time.sleep(p.pause_ddg)  # DuckDuckGo limite vite les rafales
        try:
            trouves = rechercher_ddg(r["requete"], r["langue"], r["source_id"], r["origine"])
            items += trouves
            nb_ddg += 1
            pertinents = sum(config.passe_prefiltre(t["titre"], t["extrait"]) for t in trouves)
            exemple = f" · ex. « {trouves[0]['titre'][:70]} » ({trouves[0]['domaine']})" if trouves else ""
            log(f"  DDG « {r['requete'][:50]} » : {len(trouves)} résultat(s), {pertinents} dans le domaine{exemple}")
            echecs_ddg = 0
        except ErreurSource as ex:
            echecs_ddg += 1
            erreurs.append(f"DuckDuckGo « {r['requete'][:40]} » : {ex}")
            if echecs_ddg >= 3:
                ddg_actif = False
                erreurs.append(f"DuckDuckGo interrompu après 3 échecs consécutifs ({len(plan) - n - 1} requête(s) non tentée(s))")

    log(f"Recherches : {len(plan)} prévue(s) · Serper {stats['nb_requetes_serper']} · DuckDuckGo {nb_ddg}")
    stats["_nb_requetes_ddg"] = nb_ddg
    return items


def inserer(db: Base, p: config.Parametres, items: list[dict], stats: dict) -> None:
    # Dédoublonnage par URL (base + lot courant)
    uniques: dict[str, dict] = {}
    for it in items:
        uniques.setdefault(normaliser_url(it["url"]), it)
    connues = db.urls_connues(list(uniques))
    pool = db.signaux_recents(fenetre(p.jours_fenetre).isoformat())

    for url_norm, it in uniques.items():
        if url_norm in connues:
            continue
        r = rapprocher(it, pool)
        if r.doublon:
            continue
        evenement_id = r.evenement_id
        if evenement_id is None:
            evenement_id = db.creer_evenement(it["titre"])
        else:
            db.evenement_vu(evenement_id)
        ligne = {**it, "url_norm": url_norm, "evenement_id": evenement_id, "reprise_de": r.reprise_de}
        signal_id = db.inserer_signal(ligne)
        pool.append({"id": signal_id, "evenement_id": evenement_id, "reprise_de": r.reprise_de, "titre": it["titre"], "extrait": it["extrait"], "domaine": it["domaine"]})
        stats["nb_nouveaux"] += 1
    log(f"Insertion : {stats['nb_nouveaux']} nouveau(x) signal(aux) sur {len(uniques)} URL(s) uniques ({len(connues)} déjà connue(s))")


def trier(db: Base, p: config.Parametres, hypotheses: list[dict], indicateurs: list[dict], stats: dict, erreurs: list[str]) -> None:
    if not p.anthropic_api_key:
        erreurs.append("ANTHROPIC_API_KEY absente : tri ignoré")
        return

    a_trier = db.signaux_a_trier(p.max_appels_llm * p.taille_lot_tri * 2)
    echiquier_source = {s["id"]: s["echiquier"] for s in db.t("sources").select("id, echiquier").execute().data}

    # Pré-filtre sans IA
    candidats = []
    for s in a_trier:
        if config.passe_prefiltre(s["titre"], s.get("extrait")):
            s["echiquier_source"] = echiquier_source.get(s["source_id"])
            candidats.append(s)
        else:
            db.enregistrer_tri({"signal_id": s["id"], "trie": True, "pertinent": False, "score": 0, "triage_brut": {"prefiltre": "ecarte"}})
            stats["nb_tries"] += 1

    log(f"Pré-filtre : {len(candidats)} candidat(s) au tri IA, {len(a_trier) - len(candidats)} écarté(s)")
    if not candidats:
        return

    indicateurs_par_h: dict[str, list[dict]] = {h["id"]: [] for h in hypotheses}
    for i in indicateurs:
        indicateurs_par_h.setdefault(i["hypothese_id"], []).append(i)
    systeme = construire_systeme(config.domaine(), hypotheses, indicateurs_par_h)
    ids_questions = {q["id"] for q in config.domaine()["questions"]}

    client = ClientLLM(p.anthropic_api_key, Budget(p.max_appels_llm))
    signalees: set[str] = set()
    for k in range(0, len(candidats), p.taille_lot_tri):
        lot = candidats[k : k + p.taille_lot_tri]
        try:
            texte = client.appeler(p.modele_tri, systeme, construire_message(lot), max_tokens=4096)
            resultats = valider_resultats(extraire_json(texte), lot, ids_questions, indicateurs_par_h)
        except BudgetEpuise as ex:
            erreurs.append(str(ex) + f" — {len(candidats) - k} signal(aux) reportés au prochain passage")
            break
        except Exception as ex:  # réponse illisible, erreur API… : le lot sera repris demain
            erreurs.append(f"Tri du lot {k // p.taille_lot_tri} : {str(ex)[:200]}")
            continue
        for r in resultats:
            if not r["trie"]:
                continue
            db.enregistrer_tri(r)
            db.inserer_liens(r["liens"])
            signalees |= {l["hypothese_id"] for l in r["liens"]}
            stats["nb_tries"] += 1
        log(f"Tri : lot {k // p.taille_lot_tri + 1}/{-(-len(candidats) // p.taille_lot_tri)} traité")
    stats["nb_appels_llm"] = client.budget.appels
    db.hypotheses_signalees(signalees)


def resume_actions(stats: dict, erreurs: list[str]) -> None:
    lignes = [
        "## Veille quotidienne",
        "",
        f"- Articles collectés : {stats['nb_collectes']}",
        f"- Nouveaux signaux : {stats['nb_nouveaux']}",
        f"- Signaux triés : {stats['nb_tries']}",
        f"- Appels LLM : {stats['nb_appels_llm']} · Requêtes Serper : {stats['nb_requetes_serper']} · DuckDuckGo : {stats.get('_nb_requetes_ddg', 0)}",
    ]
    if erreurs:
        lignes += ["", "### Incidents", *[f"- {e}" for e in erreurs]]
    texte = "\n".join(lignes)
    print(texte)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(texte + "\n")


def main() -> int:
    p = config.parametres()
    db = Base(p.supabase_url, p.supabase_key)
    run_id = db.debut_run("daily")
    stats = {"nb_collectes": 0, "nb_nouveaux": 0, "nb_tries": 0, "nb_appels_llm": 0, "nb_requetes_serper": 0}
    erreurs: list[str] = []
    statut = "ok"
    try:
        hypotheses = db.hypotheses_ouvertes()
        indicateurs = db.indicateurs_actifs([h["id"] for h in hypotheses])
        items = collecter(db, p, stats, erreurs, indicateurs)
        inserer(db, p, items, stats)
        trier(db, p, hypotheses, indicateurs, stats, erreurs)
        if erreurs:
            statut = "partiel"
    except Exception as ex:
        statut = "erreur"
        erreurs.append(f"Arrêt : {type(ex).__name__} : {str(ex)[:300]}")
        raise
    finally:
        db.fin_run(run_id, statut, {k: v for k, v in stats.items() if not k.startswith('_')}, erreurs)
        resume_actions(stats, erreurs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
