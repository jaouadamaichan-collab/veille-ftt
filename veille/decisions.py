"""Décisions de l'analyste (D5, D19) : seul ce module modifie le statut ou l'énoncé d'une hypothèse,
statue un lien ou règle une source. Chaque décision sur une hypothèse est historisée (traçabilité, T de F-T-T).
Utilisé par le cockpit et par `python -m veille.valider`.
"""

from __future__ import annotations

from .config import FIABILITES, VRAISEMBLANCE
from .db import Base, maintenant

STATUTS = ("proposee", "active", "renforcee", "affaiblie", "archivee")
MOTIFS_REJET = ("pas_nouveau", "pas_source", "hors_sujet", "mauvaise_lecture")


class DecisionInvalide(ValueError):
    pass


def _hypothese(db: Base, hid: str) -> dict:
    lignes = db.t("hypotheses").select("*").eq("id", hid).execute().data
    if not lignes:
        raise DecisionInvalide(f"Hypothèse inconnue : {hid}")
    return lignes[0]


def _historiser(db: Base, h: dict, motif: str, auteur: str = "humain") -> None:
    db.t("hypotheses_versions").insert(
        {"hypothese_id": h["id"], "enonce": h["enonce"], "statut": h["statut"], "confiance": h.get("confiance"), "motif": motif, "auteur": auteur}
    ).execute()


def changer_statut(db: Base, hid: str, statut: str, motif: str, confiance: str | None = None) -> dict:
    if statut not in STATUTS:
        raise DecisionInvalide(f"Statut invalide : {statut}")
    if not motif.strip():
        raise DecisionInvalide("Un motif est obligatoire (traçabilité)")
    if confiance is not None and confiance not in VRAISEMBLANCE:
        raise DecisionInvalide(f"Vraisemblance hors vocabulaire : {confiance}")
    h = _hypothese(db, hid)
    maj = {"statut": statut, "maj_le": maintenant()}
    if confiance:
        maj["confiance"] = confiance
    db.t("hypotheses").update(maj).eq("id", hid).execute()
    h.update(maj)
    _historiser(db, h, motif.strip())
    return h


def reformuler(db: Base, hid: str, enonce: str, motif: str, confiance: str | None = None) -> dict:
    if len(enonce.strip()) < 20:
        raise DecisionInvalide("Énoncé trop court")
    if not motif.strip():
        raise DecisionInvalide("Un motif est obligatoire (traçabilité)")
    if confiance is not None and confiance not in VRAISEMBLANCE:
        raise DecisionInvalide(f"Vraisemblance hors vocabulaire : {confiance}")
    h = _hypothese(db, hid)
    maj = {"enonce": " ".join(enonce.split()), "maj_le": maintenant()}
    if confiance:
        maj["confiance"] = confiance
    db.t("hypotheses").update(maj).eq("id", hid).execute()
    h.update(maj)
    _historiser(db, h, motif.strip())
    return h


def ajouter_hypothese(db: Base, question_id: str, type_h: str, enonce: str, confiance: str, motif: str) -> dict:
    if type_h not in ("hypothese", "contre"):
        raise DecisionInvalide("Type invalide")
    if confiance not in VRAISEMBLANCE:
        raise DecisionInvalide("Vraisemblance hors vocabulaire")
    if len(enonce.strip()) < 20:
        raise DecisionInvalide("Énoncé trop court")
    existants = [h["id"] for h in db.t("hypotheses").select("id").execute().data if h["id"].startswith(f"H{question_id[1:]}-")]
    lettres = sorted(i.split("-")[1] for i in existants)
    suivante = chr(ord(lettres[-1]) + 1) if lettres else "A"
    h = {
        "id": f"H{question_id[1:]}-{suivante}",
        "question_id": question_id,
        "type": type_h,
        "enonce": " ".join(enonce.split()),
        "statut": "active",  # créée par l'analyste : pas besoin de validation
        "confiance": confiance,
    }
    db.t("hypotheses").insert(h).execute()
    _historiser(db, h, motif.strip() or "Hypothèse ajoutée par l'analyste")
    return h


def statuer_lien(db: Base, lien_id: int, statut: str, motif_rejet: str | None = None) -> None:
    if statut not in ("valide", "rejete", "propose"):
        raise DecisionInvalide(f"Statut de lien invalide : {statut}")
    if statut == "rejete" and motif_rejet not in MOTIFS_REJET:
        raise DecisionInvalide("Un rejet exige un motif structuré (D22)")
    db.t("liens").update({"statut": statut, "motif_rejet": motif_rejet if statut == "rejete" else None}).eq("id", lien_id).execute()
    if statut == "rejete":
        db.t("feedbacks").insert({"cible_type": "lien", "cible_id": str(lien_id), "verdict": "rejete", "motif": motif_rejet}).execute()


def regler_source(db: Base, source_id: str, fiabilite: str | None = None, actif: bool | None = None) -> None:
    maj = {}
    if fiabilite is not None:
        if fiabilite not in FIABILITES:
            raise DecisionInvalide("Fiabilité invalide")
        maj["fiabilite"] = fiabilite
    if actif is not None:
        maj["actif"] = actif
        if actif:
            maj["echecs_consecutifs"] = 0
    if maj:
        db.t("sources").update(maj).eq("id", source_id).execute()


def valider_brief(db: Base, semaine: str, note: str = "") -> None:
    db.t("briefs").update({"statut": "valide"}).eq("semaine", semaine).execute()
    db.t("feedbacks").insert({"cible_type": "mouvement", "cible_id": f"brief:{semaine}", "verdict": "utile", "note": note or None}).execute()
