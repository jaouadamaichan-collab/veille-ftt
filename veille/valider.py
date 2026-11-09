"""Applique une décision humaine sur le statut des hypothèses (D19), en attendant le cockpit (lot 2).

Chaque changement est historisé dans hypotheses_versions avec l'auteur « humain » et le motif.

Usage :
  python -m veille.valider --activer-proposees --motif "Validées le 09/11/2026"
  python -m veille.valider H2-A H2-B --statut active --motif "..."
"""

from __future__ import annotations

import argparse
import sys

from . import config
from .db import Base, maintenant

STATUTS = ("proposee", "active", "renforcee", "affaiblie", "archivee")


def main(argv: list[str]) -> int:
    a = argparse.ArgumentParser()
    a.add_argument("ids", nargs="*")
    a.add_argument("--activer-proposees", action="store_true")
    a.add_argument("--statut", choices=STATUTS, default="active")
    a.add_argument("--motif", required=True)
    args = a.parse_args(argv)

    p = config.parametres()
    db = Base(p.supabase_url, p.supabase_key)
    hypotheses = db.t("hypotheses").select("*").order("id").execute().data
    if args.activer_proposees:
        cibles = [h for h in hypotheses if h["statut"] == "proposee"]
    else:
        connus = {h["id"]: h for h in hypotheses}
        inconnus = [i for i in args.ids if i not in connus]
        if inconnus or not args.ids:
            print(f"Identifiants inconnus ou absents : {inconnus or '(aucun)'}")
            return 1
        cibles = [connus[i] for i in args.ids]

    for h in cibles:
        db.t("hypotheses").update({"statut": args.statut, "maj_le": maintenant()}).eq("id", h["id"]).execute()
        db.t("hypotheses_versions").insert(
            {
                "hypothese_id": h["id"],
                "enonce": h["enonce"],
                "statut": args.statut,
                "confiance": h["confiance"],
                "motif": args.motif,
                "auteur": "humain",
            }
        ).execute()
        print(f"{h['id']} : {h['statut']} → {args.statut}")
    print(f"{len(cibles)} hypothèse(s) mise(s) à jour.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
