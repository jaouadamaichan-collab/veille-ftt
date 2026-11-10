"""Import de la configuration dans Supabase.

N'écrase jamais ce que l'humain a modifié dans le cockpit (statut, énoncé, fiabilité, activation) :
les lignes existantes sont ignorées. `--maj-sources` met à jour url/requête des sources existantes.

Usage : python -m veille.seed [--maj-sources]
"""

from __future__ import annotations

import sys

from . import config
from .db import Base


def main(argv: list[str], db: Base | None = None) -> int:
    erreurs = config.valider()
    if erreurs:
        print("Configuration invalide :\n- " + "\n- ".join(erreurs))
        return 1

    if db is None:
        p = config.parametres()
        db = Base(p.supabase_url, p.supabase_key)
    run_id = db.debut_run("seed")

    d = config.domaine()
    db.upsert("questions", [{"id": q["id"], "intitule": q["intitule"], "echiquier_principal": q.get("echiquier_principal")} for q in d["questions"]], ecraser=True)

    deja = db.ids_existants("hypotheses")
    nouvelles = [h for h in config.hypotheses() if h["id"] not in deja]
    db.upsert(
        "hypotheses",
        [
            {
                "id": h["id"],
                "question_id": h["question"],
                "type": h["type"],
                "enonce": " ".join(h["enonce"].split()),
                "contexte": " ".join((h.get("contexte") or "").split()) or None,
                "statut": "proposee",
                "confiance": h.get("confiance"),
            }
            for h in nouvelles
        ],
    )
    if nouvelles:
        db.t("hypotheses_versions").insert(
            [
                {
                    "hypothese_id": h["id"],
                    "enonce": " ".join(h["enonce"].split()),
                    "statut": "proposee",
                    "confiance": h.get("confiance"),
                    "motif": "Hypothèse initiale rédigée par l'agent (lot 1)",
                    "auteur": "agent",
                }
                for h in nouvelles
            ]
        ).execute()

    db.upsert(
        "indicateurs",
        [
            {"id": i["id"], "hypothese_id": h["id"], "description": i["description"], "sens": i["sens"], "requete": i["requete"]}
            for h in config.hypotheses()
            for i in h["indicateurs"]
        ],
    )

    champs = ("id", "nom", "type", "url", "requete", "echiquier", "langue", "fiabilite", "verifie")
    lignes = [{k: s.get(k) for k in champs} for s in config.sources()]
    db.upsert("sources", lignes, ecraser=False)
    if "--maj-sources" in argv:
        # Met à jour la définition technique (nom, type, url, requête) sans toucher à la fiabilité,
        # réglée dans le cockpit. Une source réécrite repart à zéro côté santé et est réactivée.
        en_base = {r["id"]: r for r in db.t("sources").select("id, type, url, requete").execute().data}
        for s in lignes:
            avant = en_base.get(s["id"])
            maj = {"nom": s["nom"], "type": s["type"], "url": s["url"], "requete": s["requete"]}
            if avant and (avant["type"], avant["url"], avant["requete"]) != (s["type"], s["url"], s["requete"]):
                maj |= {"actif": True, "echecs_consecutifs": 0, "derniere_erreur": None, "verifie": s["verifie"]}
            db.t("sources").update(maj).eq("id", s["id"]).execute()

    db.fin_run(run_id, "ok", {}, [])
    print(f"Import terminé : {len(nouvelles)} nouvelle(s) hypothèse(s), {len(lignes)} source(s) déclarée(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
