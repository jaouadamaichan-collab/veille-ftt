"""Applique une décision humaine sur le statut des hypothèses (D19) en ligne de commande.
Le cockpit fait la même chose via veille.decisions.

Usage :
  python -m veille.valider --activer-proposees --motif "Validées le 09/11/2026"
  python -m veille.valider H2-A H2-B --statut active --motif "..."
"""

from __future__ import annotations

import argparse
import sys

from . import config, decisions
from .db import Base


def main(argv: list[str], db: Base | None = None) -> int:
    a = argparse.ArgumentParser()
    a.add_argument("ids", nargs="*")
    a.add_argument("--activer-proposees", action="store_true")
    a.add_argument("--statut", choices=decisions.STATUTS, default="active")
    a.add_argument("--motif", required=True)
    args = a.parse_args(argv)

    if db is None:
        p = config.parametres()
        db = Base(p.supabase_url, p.supabase_key)
    hypotheses = db.t("hypotheses").select("*").order("id").execute().data
    if args.activer_proposees:
        cibles = [h["id"] for h in hypotheses if h["statut"] == "proposee"]
    else:
        connus = {h["id"] for h in hypotheses}
        inconnus = [i for i in args.ids if i not in connus]
        if inconnus or not args.ids:
            print(f"Identifiants inconnus ou absents : {inconnus or '(aucun)'}")
            return 1
        cibles = args.ids

    avant = {h["id"]: h["statut"] for h in hypotheses}
    for hid in cibles:
        decisions.changer_statut(db, hid, args.statut, args.motif)
        print(f"{hid} : {avant[hid]} → {args.statut}")
    print(f"{len(cibles)} hypothèse(s) mise(s) à jour.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
