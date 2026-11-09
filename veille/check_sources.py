"""Contrôle de santé des flux RSS. Met à jour `verifie` / `echecs_consecutifs` et publie un tableau
dans le résumé GitHub Actions. Ne consomme aucun crédit Serper ni appel LLM.

Usage : python -m veille.check_sources
"""

from __future__ import annotations

import os
import sys

from . import config
from .collect import ErreurSource, collecter_rss, fenetre
from .db import Base


def main() -> int:
    p = config.parametres()
    db = Base(p.supabase_url, p.supabase_key)
    run_id = db.debut_run("check_sources")
    lignes = ["| Source | Échiquier | Langue | Résultat |", "|---|---|---|---|"]
    ko = []
    for s in db.t("sources").select("*").eq("type", "rss").order("id").execute().data:
        try:
            items = collecter_rss(s, fenetre(30))
            db.sante_source(s, True)
            res = f"✅ {len(items)} article(s) sur 30 jours"
        except ErreurSource as ex:
            db.sante_source(s, False, str(ex))
            res = f"❌ {ex}"
            ko.append(s["id"])
        lignes.append(f"| {s['nom']} | {s['echiquier']} | {s['langue']} | {res} |")

    rapport = "## Santé des flux RSS\n\n" + "\n".join(lignes)
    print(rapport)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(rapport + "\n")
    db.fin_run(run_id, "partiel" if ko else "ok", {}, [f"{k} en échec" for k in ko])
    return 0


if __name__ == "__main__":
    sys.exit(main())
