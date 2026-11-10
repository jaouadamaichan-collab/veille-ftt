"""Analyse hebdomadaire (lot 2), chaque lundi :

1. avocat du diable : falsificateurs + requêtes de contre-preuves (modèle d'analyse) ;
2. collecte et tri de ces contre-preuves (mêmes garde-fous que le passage quotidien) ;
3. dossier de la semaine, calculé en code (corroboration, échiquiers, hors radar, archivage) ;
4. brief F-T-T (modèle d'analyse), contrôlé en code puis enregistré en brouillon ;
5. envoi par mail avec le lien du cockpit, où l'analyste tranche.

Usage : python -m veille.run_weekly
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

from . import analyse, avocat, brief, config
from .db import Base
from .llm import Budget, ClientLLM, extraire_json
from .run_daily import inserer, log, rechercher, trier

MAX_REQUETES_AVOCAT = 12


def lundi(jour: date) -> date:
    return jour - timedelta(days=jour.weekday())


def charger(db: Base, depuis_7j: str, depuis_14j: str):
    signaux = db.signaux_depuis(depuis_7j)
    liens = db.liens_des_signaux([s["id"] for s in signaux])
    signaux_14j = db.signaux_depuis(depuis_14j)
    return signaux, liens, signaux_14j


def resume_preuves(hypotheses: list[dict], signaux: list[dict], liens: list[dict]) -> dict[str, dict]:
    titres = {s["id"]: f"{s['titre']} ({s.get('domaine')})" for s in signaux}
    sortie: dict[str, dict] = {h["id"]: {"soutient": [], "contredit": []} for h in hypotheses}
    for l in liens:
        if l["statut"] != "rejete" and l["hypothese_id"] in sortie and l["signal_id"] in titres:
            sortie[l["hypothese_id"]][l["relation"]].append(titres[l["signal_id"]])
    return sortie


def passer_avocat(client: ClientLLM, p, hypotheses, signaux, liens, erreurs) -> dict[str, dict]:
    analysees = [h for h in hypotheses if h["statut"] in analyse.STATUTS_ANALYSES]
    if not analysees:
        return {}
    try:
        texte = client.appeler(
            p.modele_analyse,
            avocat.SYSTEME.format(domaine=config.domaine()["domaine"]),
            avocat.construire_message(analysees, resume_preuves(analysees, signaux, liens)),
            max_tokens=4000,
        )
        resultat = avocat.valider(extraire_json(texte), {h["id"] for h in analysees}, MAX_REQUETES_AVOCAT)
    except Exception as ex:
        erreurs.append(f"Avocat du diable indisponible : {type(ex).__name__} : {str(ex)[:200]}")
        return {}
    log(f"Avocat du diable : {len(resultat)} hypothèse(s) attaquée(s), {sum(len(v['requetes']) for v in resultat.values())} requête(s)")
    return resultat


def chercher_contre_preuves(db, p, resultat_avocat, hypotheses, indicateurs, stats, erreurs) -> None:
    plan = [
        {"requete": q, "langue": "en", "source_id": "serper_indicateurs", "origine": f"avocat:{hid}"}
        for hid, v in resultat_avocat.items()
        for q in v["requetes"]
    ]
    if not plan:
        return
    items = rechercher(plan, p, stats, erreurs)
    inserer(db, p, items, stats)
    trier(db, p, hypotheses, indicateurs, stats, erreurs)


RAPPEL_FORMAT = (
    "\n\nRAPPEL : ta réponse précédente n'était pas un objet JSON exploitable. "
    "Réponds UNIQUEMENT avec l'objet JSON demandé, sans texte avant ni après, sans bloc de code."
)


def generer_brief(client, p, dossier: dict, erreurs: list[str]) -> dict:
    """Rédaction du brief ; une seconde tentative avec rappel du format si la réponse est inexploitable."""
    systeme = brief.construire_systeme(config.domaine())
    message = brief.construire_message(dossier)
    for tentative in (1, 2):
        texte = client.appeler(p.modele_analyse, systeme, message + (RAPPEL_FORMAT if tentative == 2 else ""), max_tokens=12000)
        try:
            return brief.valider(extraire_json(texte), dossier)
        except (ValueError, json.JSONDecodeError) as ex:
            diag = getattr(client, "dernier", {}) or {}
            detail = (
                f"Brief, tentative {tentative} inexploitable ({ex}) — arrêt : {diag.get('stop_reason')}, "
                f"blocs : {diag.get('blocs')}, jetons produits : {diag.get('tokens_sortie')}, "
                f"début : « {diag.get('debut', texte[:300])} » … fin : « {diag.get('fin', texte[-200:])} »"
            )
            erreurs.append(detail)
            log(detail)
    raise ValueError("Brief inexploitable après deux tentatives (voir les incidents)")


def publier_resume(texte: str) -> None:
    print(texte)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(texte + "\n")


def executer(db: Base, p: config.Parametres, client: ClientLLM, aujourd_hui: date, envoyer_mail=None, erreurs: list[str] | None = None) -> dict:
    """Cœur du passage hebdomadaire, injectable pour les tests. Retourne un bilan."""
    stats = {"nb_collectes": 0, "nb_nouveaux": 0, "nb_tries": 0, "nb_appels_llm": 0, "nb_requetes_serper": 0}
    erreurs = [] if erreurs is None else erreurs
    maintenant = datetime.now(timezone.utc)
    semaine = lundi(aujourd_hui).isoformat()
    depuis_7j = (maintenant - timedelta(days=7)).isoformat()
    depuis_14j = (maintenant - timedelta(days=14)).isoformat()

    hypotheses = db.t("hypotheses").select("*").order("id").execute().data
    ouvertes = [h for h in hypotheses if h["statut"] != "archivee"]
    indicateurs = db.indicateurs_actifs([h["id"] for h in ouvertes])

    signaux, liens, _ = charger(db, depuis_7j, depuis_14j)
    log(f"Semaine du {semaine} : {len(signaux)} signal(aux) pertinent(s), {len(liens)} lien(s)")

    resultat_avocat = passer_avocat(client, p, hypotheses, signaux, liens, erreurs)
    chercher_contre_preuves(db, p, resultat_avocat, ouvertes, indicateurs, stats, erreurs)

    signaux, liens, signaux_14j = charger(db, depuis_7j, depuis_14j)
    dossier = analyse.construire_dossier(
        hypotheses, indicateurs, signaux, liens, db.toutes_sources(), signaux_14j,
        resultat_avocat, config.domaine()["questions"], semaine, maintenant,
    )
    log(f"Dossier : {len(dossier['signaux'])} signal(aux), {len(dossier['hypotheses'])} hypothèse(s) analysée(s)")

    if not dossier["hypotheses"]:
        erreurs.append("Aucune hypothèse active : brief non généré (valider les hypothèses dans le cockpit)")
        return {"stats": stats, "erreurs": erreurs, "brief": None}

    contenu = generer_brief(client, p, dossier, erreurs)
    contenu["avocat_du_diable"] = resultat_avocat
    contenu["signaux"] = {s["id"]: {k: s[k] for k in ("titre", "media", "url", "echiquier", "date")} for s in dossier["signaux"]}
    url_cockpit = os.environ.get("COCKPIT_URL", "")
    markdown = brief.en_markdown(contenu, dossier, url_cockpit)
    c = contenu["controle"]
    log(f"Brief : {len(contenu['mouvements'])} mouvement(s) · contrôle {c}")

    if not db.enregistrer_brief(semaine, contenu, markdown):
        erreurs.append(f"Le brief du {semaine} est déjà validé : il n'a pas été remplacé")
    elif envoyer_mail:
        try:
            envoyer_mail(f"Brief de veille — semaine du {brief.date_longue(semaine)}", markdown)
            log("Mail envoyé")
        except Exception as ex:
            erreurs.append(f"Envoi du mail impossible : {type(ex).__name__} : {str(ex)[:200]}")
    else:
        erreurs.append("Identifiants Gmail absents : brief enregistré mais non envoyé")
    return {"stats": stats, "erreurs": erreurs, "brief": contenu, "markdown": markdown}


def main() -> int:
    p = config.parametres()
    db = Base(p.supabase_url, p.supabase_key)
    run_id = db.debut_run("weekly")
    if not p.anthropic_api_key:
        db.fin_run(run_id, "erreur", {}, ["ANTHROPIC_API_KEY absente"])
        print("ANTHROPIC_API_KEY absente")
        return 1

    budget = Budget(int(os.environ.get("MAX_APPELS_ANALYSE", "3")))
    client = ClientLLM(p.anthropic_api_key, budget)
    exp, mdp = os.environ.get("GMAIL_EXPEDITEUR"), os.environ.get("GMAIL_MOT_DE_PASSE")
    envoyer_mail = None
    if exp and mdp:
        from .mail import envoyer

        dest = os.environ.get("GMAIL_DESTINATAIRE") or exp
        envoyer_mail = lambda sujet, md: envoyer(exp, mdp, dest, sujet, md)  # noqa: E731

    erreurs_partagees: list[str] = []
    bilan = {"stats": {}, "erreurs": erreurs_partagees}
    statut = "ok"
    try:
        bilan = executer(db, p, client, date.today(), envoyer_mail, erreurs_partagees)
        if bilan["erreurs"]:
            statut = "partiel"
    except Exception as ex:
        statut = "erreur"
        bilan["erreurs"].append(f"Arrêt : {type(ex).__name__} : {str(ex)[:300]}")
        raise
    finally:
        stats = {k: v for k, v in bilan.get("stats", {}).items() if not k.startswith("_")}
        stats["nb_appels_llm"] = stats.get("nb_appels_llm", 0) + budget.appels
        db.fin_run(run_id, statut, stats, bilan["erreurs"])
        lignes = [bilan.get("markdown") or "## Brief non produit", "", "### Exécution", f"- Appels au modèle d'analyse : {budget.appels}"]
        lignes += [f"- {e}" for e in bilan["erreurs"]]
        publier_resume("\n".join(lignes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
