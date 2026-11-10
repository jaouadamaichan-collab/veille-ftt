"""Renvoie le dernier brief enregistré, sans appel au modèle : sert à tester l'envoi Gmail et le lien
du cockpit (COCKPIT_URL), ou à renvoyer un brief perdu.

Usage : python -m veille.envoyer_brief
"""

from __future__ import annotations

import os
import sys

from . import brief, config
from .db import Base


def regenerer_markdown(contenu: dict, url_cockpit: str) -> str:
    """Le brief enregistré contient les signaux cités : on peut le re-rendre avec le lien du cockpit."""
    dossier = {"signaux": [{"id": k, **v} for k, v in (contenu.get("signaux") or {}).items()]}
    return brief.en_markdown(contenu, dossier, url_cockpit)


def main(db: Base | None = None, envoyer=None) -> int:
    if db is None:
        p = config.parametres()
        db = Base(p.supabase_url, p.supabase_key)
    lignes = db.t("briefs").select("*").order("semaine", desc=True).limit(1).execute().data
    if not lignes:
        print("Aucun brief enregistré.")
        return 1
    b = lignes[0]
    url = os.environ.get("COCKPIT_URL", "")
    markdown = regenerer_markdown(b["contenu"], url)
    print(f"Brief de la semaine du {b['semaine']} · lien cockpit : {url or 'ABSENT (variable COCKPIT_URL non définie)'}")

    if envoyer is None:
        exp, mdp = os.environ.get("GMAIL_EXPEDITEUR"), os.environ.get("GMAIL_MOT_DE_PASSE")
        if not (exp and mdp):
            print("GMAIL_EXPEDITEUR ou GMAIL_MOT_DE_PASSE absent : envoi impossible.")
            return 1
        from .mail import envoyer as envoyer_gmail

        dest = os.environ.get("GMAIL_DESTINATAIRE") or exp
        envoyer = lambda sujet, md: envoyer_gmail(exp, mdp, dest, sujet, md)  # noqa: E731
        print(f"Envoi à {dest[:3]}…@{dest.split('@')[-1]}")
    envoyer(f"Brief de veille — semaine du {brief.date_longue(b['semaine'])}", markdown)
    if b["statut"] != "valide":
        db.t("briefs").update({"markdown": markdown}).eq("semaine", b["semaine"]).execute()
    print("Mail envoyé.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
