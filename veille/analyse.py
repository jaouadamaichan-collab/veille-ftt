"""Préparation de l'analyse hebdomadaire : dossier de preuves par hypothèse, corroboration (D18),
échiquiers silencieux (D24), candidats hors radar (D20), suggestions d'archivage (D19).

Tout ce qui peut être calculé l'est ici, en code : le modèle reçoit des faits comptés,
il n'a pas à les estimer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .config import ECHIQUIERS

STATUTS_ANALYSES = ("active", "renforcee", "affaiblie")
SEMAINES_AVANT_ARCHIVAGE = 6
MAX_SIGNAUX_DOSSIER = 120

SUFFIXES_INSTITUTIONS = (
    "europa.eu", "imo.org", "gouv.fr", ".gov", "gov.uk", "un.org", "unfccc.int",
    "oecd.org", "itf-oecd.org", "iea.org", "irena.org", "parlement.fr", "senat.fr", "assemblee-nationale.fr",
)
DOMAINES_SOCIETE_CIVILE = {
    "transportenvironment.org", "theicct.org", "carbonbrief.org", "globalmaritimeforum.org",
    "cleanshipping.org", "u-mas.co.uk", "oceanconservancy.org", "opportunitygreen.org",
    "seas-at-risk.org", "stand.earth", "pacificenvironment.org", "zeroemissionshipping.org",
}
NATURES = ("institution", "presse", "societe_civile")


def nature_source(domaine: str | None, echiquier_source: str | None) -> str:
    """Nature de l'émetteur, pour la règle « deux sources de nature différente » (D18)."""
    d = (domaine or "").lower()
    if any(d == s.lstrip(".") or d.endswith(s if s.startswith(".") else "." + s) for s in SUFFIXES_INSTITUTIONS):
        return "institution"
    if d in DOMAINES_SOCIETE_CIVILE or echiquier_source == "societe_civile":
        return "societe_civile"
    return "presse"


def corroboration(signaux: list[dict]) -> dict:
    """Signaux = éléments de preuve d'un même sens pour une même hypothèse.
    Une reprise ne compte pas ; une source jugée « douteuse » non plus."""
    retenus = [s for s in signaux if not s.get("reprise_de") and s.get("fiabilite") != "douteuse"]
    domaines = sorted({s["domaine"] for s in retenus if s.get("domaine")})
    natures = sorted({s["nature"] for s in retenus})
    return {
        "nb_signaux": len(signaux),
        "domaines_independants": len(domaines),
        "natures": natures,
        "suffisante": len(domaines) >= 2 and len(natures) >= 2,
    }


def echiquiers_silencieux(signaux_14j: list[dict]) -> tuple[dict, list[str]]:
    comptes = {e: 0 for e in ECHIQUIERS}
    for s in signaux_14j:
        if s.get("pertinent") and s.get("echiquier") in comptes:
            comptes[s["echiquier"]] += 1
    return comptes, [e for e, n in comptes.items() if n == 0]


def suggestions_archivage(hypotheses: list[dict], maintenant: datetime) -> list[dict]:
    limite = maintenant - timedelta(weeks=SEMAINES_AVANT_ARCHIVAGE)
    sortie = []
    for h in hypotheses:
        if h["statut"] not in STATUTS_ANALYSES:
            continue
        repere = h.get("dernier_signal_le") or h.get("maj_le") or h.get("cree_le")
        try:
            date_repere = datetime.fromisoformat(str(repere).replace("Z", "+00:00"))
        except ValueError:
            continue
        if date_repere < limite:
            sortie.append({"hypothese": h["id"], "depuis": str(repere)[:10], "motif": f"Aucun signal rattaché depuis plus de {SEMAINES_AVANT_ARCHIVAGE} semaines"})
    return sortie


def construire_dossier(
    hypotheses: list[dict],
    indicateurs: list[dict],
    signaux: list[dict],
    liens: list[dict],
    sources: dict[str, dict],
    signaux_14j: list[dict],
    avocat: dict[str, dict],
    questions: list[dict],
    semaine: str,
    maintenant: datetime | None = None,
) -> dict:
    """Assemble le dossier transmis au modèle pour le brief, avec des identifiants « SIG<id> » stables."""
    maintenant = maintenant or datetime.now(timezone.utc)
    analysees = [h for h in hypotheses if h["statut"] in STATUTS_ANALYSES]
    ids_h = {h["id"] for h in analysees}

    par_id = {}
    for s in signaux:
        src = sources.get(s.get("source_id")) or {}
        par_id[s["id"]] = {
            **s,
            "nature": nature_source(s.get("domaine"), src.get("echiquier")),
            "fiabilite": src.get("fiabilite", "a_confirmer"),
        }

    liens_utiles = [l for l in liens if l["statut"] != "rejete" and l["hypothese_id"] in ids_h and l["signal_id"] in par_id]
    liens_par_signal: dict[int, list[dict]] = {}
    for l in liens_utiles:
        liens_par_signal.setdefault(l["signal_id"], []).append(l)

    # Sélection : d'abord les signaux rattachés, puis les plus utiles, puis les hors radar.
    def priorite(s):
        return (s["id"] in liens_par_signal, s.get("score") or 0)

    retenus = sorted((s for s in par_id.values() if s.get("pertinent")), key=priorite, reverse=True)[:MAX_SIGNAUX_DOSSIER]
    ids_retenus = {s["id"] for s in retenus}

    blocs_h = []
    for h in analysees:
        preuves = {"soutient": [], "contredit": []}
        for l in liens_utiles:
            if l["hypothese_id"] == h["id"] and l["signal_id"] in ids_retenus:
                preuves[l["relation"]].append(l["signal_id"])
        blocs_h.append(
            {
                "id": h["id"],
                "question": h["question_id"],
                "type": h["type"],
                "enonce": h["enonce"],
                "statut": h["statut"],
                "confiance": h.get("confiance"),
                "indicateurs": [
                    {"id": i["id"], "sens": i["sens"], "description": i["description"]}
                    for i in indicateurs
                    if i["hypothese_id"] == h["id"]
                ],
                "preuves": {k: [f"SIG{v}" for v in sorted(set(vs))] for k, vs in preuves.items()},
                "corroboration": {k: corroboration([par_id[i] for i in set(vs)]) for k, vs in preuves.items()},
                "avocat_du_diable": avocat.get(h["id"]),
            }
        )

    comptes, silencieux = echiquiers_silencieux(signaux_14j)
    candidats_hors_radar = [f"SIG{s['id']}" for s in sorted(retenus, key=lambda s: s.get("score") or 0, reverse=True) if s.get("hors_radar")][:6]

    return {
        "semaine": semaine,
        "questions": [{"id": q["id"], "intitule": q["intitule"]} for q in questions],
        "hypotheses": blocs_h,
        "hypotheses_en_attente": [{"id": h["id"], "enonce": h["enonce"]} for h in hypotheses if h["statut"] == "proposee"],
        "signaux": [
            {
                "id": f"SIG{s['id']}",
                "titre": s["titre"],
                "resume": s.get("resume"),
                "media": s.get("domaine"),
                "url": s.get("url"),
                "date": str(s.get("publie_le") or s.get("collecte_le") or "")[:10],
                "echiquier": s.get("echiquier"),
                "nature": s["nature"],
                "fiabilite": s["fiabilite"],
                "evenement": s.get("evenement_id"),
                "reprise": bool(s.get("reprise_de")),
                "score": s.get("score"),
                "liens": [
                    {"hypothese": l["hypothese_id"], "relation": l["relation"], "justification": l.get("justification"), "valide_par_analyste": l["statut"] == "valide"}
                    for l in liens_par_signal.get(s["id"], [])
                ],
            }
            for s in retenus
        ],
        "hors_radar_candidats": candidats_hors_radar,
        "echiquiers_14_jours": comptes,
        "echiquiers_silencieux": silencieux,
        "suggestions_archivage": suggestions_archivage(hypotheses, maintenant),
    }
